#!/usr/bin/env python

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#
# See LICENSE for more details.
# Copyright: 2026 IBM
# Authors: Sai Janani C (jananic@linux.ibm.com)

import os
import shlex
import time
import subprocess
from threading import Thread, Event
from avocado import Test
from avocado.utils import process
from avocado.utils import git
from avocado.utils.podman import (
    Podman,
    PodmanException,
    install_huggingface_cli,
    download_model_from_hf,
    validate_model_with_sha,
    wait_for_vllm_startup
)
from avocado.utils.software_manager.manager import SoftwareManager


class ObservabilityTests(Test):
    """
    Test AIU observability features including aiu-smi metrics and trace analysis.
    Runs observability tests on Spyre AIU devices with VLLM inference workload.
    """

    TRACE_ANALYZER_PATH = "/tmp/aiu-trace-analyzer"
    CONTAINER_ID_FILE = "/tmp/spyre_observability_container_ids.txt"

    _root_container_id = None
    _nonroot_container_id = None
    _podman = None
    inference_thread = None
    stop_inference_event = None
    current_container_id = None  # Track which container is currently active

    @staticmethod
    def _save_container_ids():
        """Save container IDs to file for sharing between test processes."""
        try:
            with open(ObservabilityTests.CONTAINER_ID_FILE, 'w') as f:
                f.write(
                    f"root={ObservabilityTests._root_container_id or ''}\n")
                f.write(
                    f"nonroot={ObservabilityTests._nonroot_container_id or ''}\n")
        except Exception:
            pass

    @staticmethod
    def _load_container_ids():
        """Load container IDs from file (shared between test processes)."""
        try:
            if os.path.exists(ObservabilityTests.CONTAINER_ID_FILE):
                with open(ObservabilityTests.CONTAINER_ID_FILE, 'r') as f:
                    for line in f:
                        if line.startswith('root='):
                            cid = line.split('=', 1)[1].strip()
                            if cid:
                                ObservabilityTests._root_container_id = cid
                        elif line.startswith('nonroot='):
                            cid = line.split('=', 1)[1].strip()
                            if cid:
                                ObservabilityTests._nonroot_container_id = cid
        except Exception:
            pass

    def run_cmd(self, cmd):
        """Execute a command and fail test if it fails."""
        if process.system(cmd, sudo=True, shell=True):
            self.fail(f"Command failed: {cmd}")

    @staticmethod
    def run_cmd_out(cmd):
        """Execute a command and return output."""
        return process.system_output(
            cmd, shell=True, sudo=True).decode("utf-8").strip()

    def run_inference(self):
        """Run inference in a loop until stop_inference is set."""
        prompts = [
            "write a sample python code for bubble sort",
            "explain the concept of recursion in programming",
            "what are the benefits of using design patterns",
            "describe how binary search works",
            "explain the difference between stack and queue"
        ]

        if self.current_container_id == ObservabilityTests._nonroot_container_id:
            port = int(self.port_mapping.split(":")[-2])
            self.log.info(
                "Nonroot container — using host port %s from PORT_MAPPING", port)
        else:
            port = ObservabilityTests._podman.get_container_port(
                self.current_container_id, port=8000)
        if port is None:
            self.log.error("Could not determine container port for inference")
            return

        self.log.info("Starting inference on port %s", port)
        prompt_index = 0

        while not self.stop_inference_event.is_set():
            try:
                prompt = prompts[prompt_index % len(prompts)]
                curl_cmd = [
                    "curl", "-s",
                    f"http://127.0.0.1:{port}/v1/completions",
                    "-H", "Content-Type: application/json",
                    "-d", f'{{"model": "{self.vllm_model_path}", "prompt": "{prompt}", "max_tokens": 128, "temperature": 1}}'
                ]

                result = subprocess.run(
                    curl_cmd,
                    capture_output=True,
                    timeout=30
                )

                if result.returncode == 0:
                    self.log.debug(
                        "Inference request %d completed successfully", prompt_index)
                else:
                    self.log.debug("Inference request %d failed", prompt_index)

                prompt_index += 1
                time.sleep(5)

            except subprocess.TimeoutExpired:
                self.log.debug("Inference request timed out")
            except Exception as ex:
                self.log.debug("Inference error: %s", ex)
                time.sleep(5)

        self.log.info("Inference stopped")

    def start_inference(self):
        """Start inference in a separate thread."""
        if self.inference_thread and self.inference_thread.is_alive():
            self.log.warning("Inference thread already running")
            return

        self.stop_inference_event = Event()
        self.inference_thread = Thread(target=self.run_inference)
        self.inference_thread.daemon = True
        self.inference_thread.start()
        self.log.info("Inference thread started")

    def stop_inference(self):
        """Stop the inference thread."""
        if self.stop_inference_event:
            self.log.info("Stopping inference thread")
            self.stop_inference_event.set()

        if self.inference_thread and self.inference_thread.is_alive():
            self.inference_thread.join(timeout=10)
            if self.inference_thread.is_alive():
                self.log.debug(
                    "Inference thread did not stop gracefully (expected during cleanup)")
            else:
                self.log.info("Inference thread stopped")

    def spyre_exists(self):
        """
        Check if VFIO Spyre devices exist and verify group ownership.

        :return: True if VFIO devices exist with correct spyre_group, False otherwise
        """
        if not os.path.exists('/dev/vfio'):
            return False
        files = os.listdir('/dev/vfio')
        has_numeric_device = any(file.isdigit() for file in files)
        if not has_numeric_device:
            return False
        if hasattr(self, 'spyre_group') and self.spyre_group:
            try:
                device_listing = process.system_output(
                    'ls -l /dev/vfio', shell=True, ignore_status=True,
                    sudo=True).decode("utf-8").strip()
                if self.spyre_group not in device_listing:
                    self.log.warning(
                        "VFIO devices exist but spyre_group '%s' not found in device listing",
                        self.spyre_group)
                    return False
                self.log.info(
                    "VFIO devices exist with correct spyre_group '%s'",
                    self.spyre_group)
            except Exception as ex:
                self.log.warning(
                    "Failed to verify device group ownership: %s", ex)
                return False
        return True

    def capture_aiu_smi_metrics(self, container_id, duration=30):
        """
        Capture aiu-smi metrics from the container for a specified duration.
        Uses podman.collect_container_aiu_metrics utility function.

        :param container_id: Container ID
        :param duration: Duration to capture metrics in seconds
        :return: Tuple of (success, metrics_output)
        """
        try:
            self.log.info("Capturing aiu-smi metrics for %d seconds", duration)

            is_nonroot = (container_id ==
                          ObservabilityTests._nonroot_container_id)

            # Check if /opt/aiu-monitor exists in the container
            if is_nonroot:
                rc, out, _ = self._run_as_user(
                    f"podman exec {container_id} bash -c "
                    f"'[ -d /opt/aiu-monitor ] && echo exists || echo notfound'")
                check_result = out.strip()
            else:
                returncode, stdout, stderr = ObservabilityTests._podman.exec_command(
                    container_id=container_id,
                    command=[
                        "bash", "-c", "[ -d /opt/aiu-monitor ] && echo exists || echo notfound"]
                )
                check_result = stdout.decode(
                    'utf-8').strip() if isinstance(stdout, bytes) else stdout.strip()

            # Build aiu-smi command based on whether /opt/aiu-monitor exists
            if "exists" in check_result:
                self.log.info("Using aiu-smi with virtual environment")
                stats_command = "source /opt/aiu-monitor/bin/activate && aiu-smi"
            else:
                self.log.info("Using aiu-smi directly")
                stats_command = "aiu-smi"

            if is_nonroot:
                output_file = f"/tmp/aiu_metrics_{self.user}.log"
            else:
                output_file = os.path.join(self.workdir, "aiu_metrics.log")

            self.log.info("Collecting metrics for %d seconds", duration)
            ObservabilityTests._podman.collect_container_aiu_metrics(
                container_id=container_id,
                output_file=output_file,
                stats_command=stats_command,
                timeout=duration,
                user=self.user if is_nonroot else None
            )
            time.sleep(duration + 2)

            # Read captured metrics
            if not os.path.exists(output_file):
                self.log.error(
                    "Metrics output file not found: %s", output_file)
                return False, ""

            with open(output_file, 'r') as f:
                metrics_output = f.read()

            if not metrics_output or len(metrics_output.strip()) == 0:
                self.log.error("No metrics were captured during the test")
                return False, metrics_output

            self.log.info("=== Captured AIU-SMI Metrics ===")
            self.log.info("\n%s", metrics_output)

            # Validate metrics
            if self._validate_metrics(metrics_output):
                self.log.info("Metrics validation PASSED")
                return True, metrics_output
            else:
                self.log.error("Metrics validation FAILED")
                return False, metrics_output

        except Exception as ex:
            self.log.error("Exception while capturing metrics: %s", ex)
            return False, str(ex)

    def _validate_metrics(self, metrics_output):
        """
        Validate that the metrics output contains expected data.

        :param metrics_output: The captured metrics output
        :return: True if valid, False otherwise
        """
        # Check for required headers
        required_headers = ["#ID", "Date", "Time", "hostcpu", "hostmem",
                            "pwr", "busy", "rdmem", "wrmem"]
        temp_header_present = "gtemp" in metrics_output or "tempr" in metrics_output

        has_headers = temp_header_present and all(
            header in metrics_output for header in required_headers)
        if not has_headers:
            self.log.error("Metrics missing required headers")
            return False

        # Check for actual data lines (lines starting with device ID)
        lines = metrics_output.split('\n')
        data_lines = [line for line in lines if line.strip()
                      and not line.strip().startswith('#')
                      and len(line.split()) >= 10]

        if not data_lines:
            self.log.error("No data lines found in metrics output")
            return False

        self.log.info("Found %d data lines in metrics output", len(data_lines))

        try:
            first_data = data_lines[0].split()
            device_id = int(first_data[0])
            hostcpu = float(first_data[3])
            hostmem = float(first_data[4])
            power = float(first_data[5])
            temp = float(first_data[6])

            self.log.info(
                "Sample metrics - Device: %d, CPU: %.1f%%, Mem: %.1f%%, "
                "Power: %.1fW, Temp: %.1fC",
                device_id, hostcpu, hostmem, power, temp)
            return True

        except (ValueError, IndexError) as ex:
            self.log.error("Failed to parse metrics data: %s", ex)
            return False

    def setUp(self):
        """Set up test environment."""
        if "ppc" not in os.uname()[4]:
            self.cancel("supported only on Power platform")

        curr_user = self.run_cmd_out('whoami')
        if 'root' not in curr_user:
            self.cancel("Please login as root user and continue")

        # Load container IDs from previous tests (if any)
        ObservabilityTests._load_container_ids()

        smm = SoftwareManager()
        for package in ['podman', 'curl', 'git']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel(
                    f"Failed to install {package} required for this test.")

        self.rhaiis_version = self.params.get("RHAIIS_VERSION", default="")
        all_ids = self.params.get("AIU_PCIE_IDS", default="")
        ids = all_ids.split()
        self.aiu_pcie_ids = ids[0]
        self.host_models_dir = self.params.get("HOST_MODELS_DIR", default="")
        self.vllm_model_path = self.params.get("VLLM_MODEL_PATH", default="")
        self.aiu_world_size = self.params.get("AIU_WORLD_SIZE", default="")
        self.memory = self.params.get("MEMORY", default="")
        self.container_url = self.params.get("CONTAINER_URL", default=None)
        self.container_tag = self.params.get("CONTAINER_TAG", default=None)
        self.api_key = self.params.get("API_KEY", default=None)
        self.device = self.params.get("DEVICE", default="/dev/vfio")
        self.userns = self.params.get("USERNS", default="keep-id")
        self.group_add = self.params.get("GROUP_ADD", default="keep-groups")
        self.security_opt = self.params.get(
            "SECURITY_OPT", default="label=disable")
        self.pids_limit = self.params.get("PIDS_LIMIT", default="0")
        self.port_mapping = self.params.get(
            "PORT_MAPPING", default="127.0.0.1:8000:8000")
        self.user = self.params.get("USER", default="")
        self.spyre_group = self.params.get("SPYRE_GROUP", default="")
        self.hf_model_name = self.params.get("HF_MODEL_NAME", default="")

        # Observability-specific parameters
        self.metrics_duration = int(self.params.get(
            "METRICS_DURATION", default="30"))

        required_params = {
            "RHAIIS_VERSION": self.rhaiis_version,
            "CONTAINER_URL": self.container_url,
            "CONTAINER_TAG": self.container_tag,
            "MEMORY": self.memory,
            "GROUP_ADD": self.group_add,
            "API_KEY": self.api_key,
        }
        missing = [p for p, v in required_params.items() if not v]
        if missing:
            self.cancel(f"Missing required parameters: {', '.join(missing)}")

        if self.host_models_dir:
            if not os.path.exists(self.host_models_dir):
                self.log.info("Creating HOST_MODELS_DIR: %s",
                              self.host_models_dir)
                try:
                    os.makedirs(self.host_models_dir, exist_ok=True)
                    self.log.info("Successfully created HOST_MODELS_DIR")
                except Exception as ex:
                    self.cancel(f"Failed to create HOST_MODELS_DIR: {ex}")

        # Step 1: Hugging Face login and model download
        self.log.info("Step 1: Checking Hugging Face CLI installation...")
        if not install_huggingface_cli():
            self.cancel(
                "Failed to install Hugging Face CLI. Model download will fail.")

        if self.hf_model_name:
            model_name = os.path.basename(self.vllm_model_path)
            model_dir = os.path.join(self.host_models_dir, model_name)
            self.log.info("Step 2: Checking if model exists: %s", model_dir)
            self.log.info("  Host path: %s", model_dir)
            self.log.info("  Container path: %s", self.vllm_model_path)
            model_exists = False
            if os.path.exists(model_dir) and os.path.isdir(model_dir):
                files = os.listdir(model_dir)
                required_files = ['config.json']
                has_required = all(
                    any(f.startswith(req.split('.')[0]) for f in files) for req in required_files)
                if files and has_required:
                    model_exists = True
                    self.log.info(
                        "Model directory exists with %d files", len(files))
                    self.log.info("Sample files: %s", ', '.join(files[:5]))

            if not model_exists:
                self.log.info(
                    "Downloading model from HuggingFace: %s", self.hf_model_name)
                self.log.info(
                    "This may take several minutes depending on model size...")
                download_success = download_model_from_hf(
                    hf_model_id=self.hf_model_name,
                    local_dir=self.host_models_dir,
                    model_name=model_name
                )
                if download_success:
                    self.log.info("Model download completed successfully")
                    self.log.info("Validating downloaded model...")
                    is_valid, messages = validate_model_with_sha(model_dir)
                    for msg in messages:
                        self.log.info("  %s", msg)
                    if is_valid:
                        self.log.info("Model validation PASSED")
                    else:
                        self.log.warning(
                            "Model validation FAILED - continuing anyway")
                    if os.path.exists(model_dir):
                        files = os.listdir(model_dir)
                        self.log.info(
                            "Model directory contains %d files", len(files))
                        self.log.info("Files: %s", ', '.join(files[:10]))
                    else:
                        self.cancel(
                            f"Model directory not found after download: {model_dir}")
                else:
                    self.cancel(
                        f"Failed to download model {self.hf_model_name}. Cannot proceed without model.")
            else:
                self.log.info("Model already exists: %s", model_dir)
                files = os.listdir(model_dir)
                self.log.info("Model directory contains %d files", len(files))

        # Initialize Podman
        self.log.info("Initializing Podman utility")
        try:
            ObservabilityTests._podman = Podman()
            self.log.info("Podman utility initialized successfully")
        except PodmanException as ex:
            self.cancel(f"Failed to initialize Podman: {ex}")

        # Login to registry if API key provided
        if self.api_key and self.container_url:
            try:
                registry = self.container_url.split('/')[0]
                self.log.info("Logging in to registry: %s", registry)
                ObservabilityTests._podman.login(
                    registry=registry, api_key=self.api_key)
                self.log.info("Successfully logged in to registry")
            except PodmanException as ex:
                self.cancel(f"Failed to login to registry: {ex}")

        # Run servicereport commands
        self.log.info("Running servicereport -r -p spyre")
        self.run_cmd("servicereport -r -p spyre")

        self.log.info("Running servicereport -v -p spyre")
        res = self.run_cmd_out("servicereport -v -p spyre")
        if "FAIL" in res:
            self.cancel("Servicereport configuration failed!")

        # Check if Spyre devices exist
        if not self.spyre_exists():
            self.cancel(
                "Spyre VFIO devices not found or not properly configured")

        # Pull container image
        if self.container_url and self.container_tag:
            image = f"{self.container_url}:{self.container_tag}"
            try:
                self.log.info("Pulling container image: %s", image)
                ObservabilityTests._podman.pull(image)
                self.log.info("Successfully pulled container image")
            except PodmanException as ex:
                self.cancel(f"Failed to pull container image: {ex}")

        self.log.info(
            "Setup complete - containers will be created by individual tests")

    def _run_as_user(self, cmd):
        """
        Run a shell command as self.user using runuser.

        :param cmd: Shell command string to execute
        :return: (returncode, stdout_str, stderr_str)
        """
        full_cmd = f"runuser -l {self.user} -c {shlex.quote(cmd)}"
        result = process.run(full_cmd, shell=True,
                             sudo=True, ignore_status=True)
        stdout = result.stdout.decode(
            'utf-8') if isinstance(result.stdout, bytes) else result.stdout
        stderr = result.stderr.decode(
            'utf-8') if isinstance(result.stderr, bytes) else result.stderr
        return result.exit_status, stdout, stderr

    def _create_container(self, user_type="root"):
        """
        Create a VLLM container for the specified user type.

        For root containers the podman command is run directly (as root).
        For nonroot containers the podman command is run as self.user via
        runuser so that the container is owned by the non-root user.

        :param user_type: Either "root" or "nonroot"
        :return: container_id if successful, None otherwise
        """
        self.log.info("Creating VLLM container for %s user", user_type)
        container_name = f"spyre-observability-{user_type}-{self.rhaiis_version.replace('.', '-')}"

        # Clean up any existing container with the same name.
        if user_type == "nonroot" and self.user:
            self._run_as_user(
                f"podman rm -f {container_name} 2>/dev/null || true")
        else:
            try:
                ObservabilityTests._podman.remove(container_name, force=True)
            except PodmanException:
                pass

        # Build the podman run argument list (common options)
        podman_args = [
            "-d",
            "-it",
            "--name", container_name,
            f"--device={self.device}",
            "-v", f"{self.host_models_dir}:/models",
            "-e", f"AIU_PCIE_IDS={self.aiu_pcie_ids}",
            "-e", "DTCOMPILER_KEEP_EXPORT=true",
            "-e", "ENABLE_FLEX_TIMING=1",
            "-e", "FLEX_PRINT_END_TO_END_BREAKDOWN=1",
            "-e", "FLEX_SKIP_TIMESTAMP_CALIBRATION=0",
            "-e", "FLEX_SCHEDULER_PRINT_RAW_TIMESTAMPS=1",
            "-e", "FLEX_GLOBAL_PROFILE_PREFIX=granite-8b-flex",
        ]

        # Add RHAIIS version specific parameters
        if self.rhaiis_version in ("3.3", "3.4"):
            podman_args.extend(["-e", "VLLM_SPYRE_USE_CB=1"])
            max_model_len = "3072"
            max_batch_size = "16"
        elif self.rhaiis_version == "3.5":
            max_model_len = "3072"
            max_batch_size = "16"
        elif self.rhaiis_version == "3.6":
            max_model_len = "4096"
            max_batch_size = "32"

        podman_args.extend([
            f"--userns={self.userns}",
            f"--group-add={self.group_add}",
            f"--security-opt={self.security_opt}",
            f"--pids-limit={self.pids_limit}",
            f"--memory={self.memory}",
            "-p", self.port_mapping,
        ])

        podman_args.append(f"{self.container_url}:{self.container_tag}")
        podman_args.extend([
            "--model", self.vllm_model_path,
            "-tp", str(self.aiu_world_size),
            f"--max-model-len={max_model_len}",
            f"--max-num-seqs={max_batch_size}",
        ])

        # Add version-specific VLLM argument for 3.3/3.4
        if self.rhaiis_version in ("3.3", "3.4"):
            podman_args.append("--enable-prefix-caching")

        # ---- Launch the container ----
        if user_type == "nonroot":
            # Run podman as the non-root user so the container belongs to them
            if not self.user:
                self.log.error(
                    "USER parameter is required for nonroot container")
                return None
            podman_cmd = "podman run " + " ".join(podman_args)
            self.log.info("Full podman command (as %s): %s",
                          self.user, podman_cmd)
            returncode, stdout, stderr = self._run_as_user(podman_cmd)
            if returncode != 0:
                self.log.error("Failed to create nonroot container")
                self.log.error("stderr: %s", stderr)
                return None
            container_id = stdout.strip()
        else:
            self.log.info("Full podman command: podman run %s",
                          " ".join(podman_args))
            try:
                returncode, stdout, stderr = ObservabilityTests._podman.run(
                    podman_options=podman_args)
                if returncode != 0:
                    self.log.error("Failed to create container")
                    self.log.error("stderr: %s", stderr.decode()
                                   if isinstance(stderr, bytes) else stderr)
                    return None
                container_id = stdout.decode().strip() if isinstance(
                    stdout, bytes) else stdout.strip()
            except PodmanException as ex:
                self.log.error("Failed to create container: %s", ex)
                return None

        if not container_id or len(container_id) < 12:
            self.log.error(
                "Failed to extract container ID from output: '%s'", container_id)
            return None

        self.log.info("Container created successfully: %s", container_id)

        # Wait for VLLM to start.
        self.log.info("Waiting for VLLM to start...")
        if not wait_for_vllm_startup(
            container_id=container_id,
            success_pattern="Application startup complete.",
            failure_pattern="BACKTRACE",
            additional_failure_checks=[("VFIO", False), ("fail", False)],
            timeout=600,
            check_interval=10,
            user=self.user if user_type == "nonroot" else None,
            log=self.log,
            show_live_logs=True,
            live_log_lines=20
        ):
            self.log.error("VLLM startup failed")
            return None

        return container_id

    def _run_aiu_smi_test(self, user_type):
        """
        Common logic for aiu-smi tests.

        :param user_type: "root" or "nonroot"
        """
        if user_type == "root":
            ObservabilityTests._root_container_id = self._create_container(
                user_type="root")
            if not ObservabilityTests._root_container_id:
                self.fail("Failed to create root user container")
            ObservabilityTests._save_container_ids()
            container_id = ObservabilityTests._root_container_id
        else:
            ObservabilityTests._nonroot_container_id = self._create_container(
                user_type="nonroot")
            if not ObservabilityTests._nonroot_container_id:
                self.fail("Failed to create non-root user container")
            ObservabilityTests._save_container_ids()
            container_id = ObservabilityTests._nonroot_container_id

        self.current_container_id = container_id

        self.log.info("Starting inference in background")
        self.start_inference()
        if not self.inference_thread or not self.inference_thread.is_alive():
            self.fail("Inference thread failed to start")

        self.log.info("Starting aiu-smi metrics capture")
        success, metrics = self.capture_aiu_smi_metrics(
            container_id, duration=self.metrics_duration)

        self.stop_inference()

        if not success:
            self.log.error("Failed to capture valid metrics")
            self.fail(
                "AIU-SMI metrics capture failed - no valid metrics captured")

        self.log.info("PASS: AIU-SMI observability test (%s) completed successfully",
                      user_type)

    def _run_trace_analyzer_test(self, user_type):
        """
        Common logic for trace analyzer tests.

        :param user_type: "root" or "nonroot"
        """
        if user_type == "root":
            container_id = ObservabilityTests._root_container_id
            if not container_id:
                self.fail("Root container not available from previous test")
        else:
            container_id = ObservabilityTests._nonroot_container_id
            if not container_id:
                self.fail("Non-root container not available from previous test")

        self.current_container_id = container_id

        # Clone aiu-trace-analyzer repository
        clone_dir = self.TRACE_ANALYZER_PATH
        self.log.info("Cloning aiu-trace-analyzer repository")
        if os.path.exists(clone_dir):
            process.system(f"rm -rf {clone_dir}", shell=True, sudo=True)

        repo_url = self.params.get("TRACE_ANALYZER_REPO",
                                   default="https://github.com/IBM/aiu-trace-analyzer.git")
        try:
            git.get_repo(uri=repo_url, branch="main",
                         destination_dir=clone_dir)
            self.log.info("Repository cloned successfully")
        except Exception as ex:
            self.fail(f"Failed to clone repository: {ex}")

        self.log.info("Copying trace analyzer to container")
        try:
            if user_type == "nonroot":
                rc, out, err = self._run_as_user(
                    f"podman cp {clone_dir} {container_id}:/tmp/")
                if rc != 0:
                    self.fail(
                        f"Failed to copy trace analyzer to container: {err}")
            else:
                ObservabilityTests._podman.copy_to_container(
                    container_id=container_id, src=clone_dir, dst="/tmp/")
        except Exception as ex:
            self.fail(f"Failed to copy trace analyzer to container: {ex}")

        if not self._verify_flex_variables(container_id):
            self.fail("FLEX environment variables not set correctly")

        if not self._install_acelyzer(container_id):
            self.fail("Failed to install acelyzer")

        self.log.info("Starting inference to generate trace files")
        self.start_inference()
        time.sleep(60)
        self.stop_inference()

        file_count, trace_location = self._find_trace_files(container_id)
        if not file_count or not trace_location:
            self.fail("No trace files generated")

        self.log.info("Found %d trace files at: %s",
                      file_count, trace_location)

        if not self._run_acelyzer(container_id, trace_location):
            self.fail("Acelyzer analysis failed")

        if not self._verify_acelyzer_output(container_id):
            self.fail("Acelyzer output verification failed")

        self.log.info("PASS: Trace analyzer test (%s) completed successfully",
                      user_type)

    def test_aiu_smi_root(self):
        """
        Test 1: AIU-SMI observability with root user container.
        Creates a container as root user and captures aiu-smi metrics.
        """
        self._run_aiu_smi_test(user_type="root")

    def test_trace_analyzer_root(self):
        """
        Test 2: Trace analyzer (acelyzer) with root user container.
        Uses the root container from test_01 and analyzes FLEX timing traces.
        """
        self._run_trace_analyzer_test(user_type="root")

    def test_aiu_smi_nonroot(self):
        """
        Test 3: AIU-SMI observability with non-root user container.
        Creates a container as non-root user and captures aiu-smi metrics.
        """
        self._run_aiu_smi_test(user_type="nonroot")

    def test_trace_analyzer_nonroot(self):
        """
        Test 4: Trace analyzer (acelyzer) with non-root user container.
        Uses the non-root container from test_03 and analyzes FLEX timing traces.
        """
        self._run_trace_analyzer_test(user_type="nonroot")

    def _verify_flex_variables(self, container_id):
        """
        Verify FLEX environment variables are set in the container.

        :param container_id: Container ID
        :return: True if all FLEX variables are set, False otherwise
        """
        try:
            self.log.info("Verifying FLEX environment variables in container")
            is_nonroot = (container_id ==
                          ObservabilityTests._nonroot_container_id)
            if is_nonroot:
                inner = "cat /proc/1/environ | tr '\\0' '\\n' | grep FLEX || true"
                _, output, _ = self._run_as_user(
                    f"podman exec {container_id} bash -c {shlex.quote(inner)}")
            else:
                _, stdout, _ = ObservabilityTests._podman.exec_command(
                    container_id=container_id,
                    command=["bash", "-c",
                             "cat /proc/1/environ | tr '\\0' '\\n' | grep FLEX"]
                )
                output = stdout.decode(
                    'utf-8') if isinstance(stdout, bytes) else stdout
            output = output.strip()

            required_vars = [
                "ENABLE_FLEX_TIMING=1",
                "FLEX_PRINT_END_TO_END_BREAKDOWN=1",
                "FLEX_SKIP_TIMESTAMP_CALIBRATION=0",
                "FLEX_SCHEDULER_PRINT_RAW_TIMESTAMPS=1",
                "FLEX_GLOBAL_PROFILE_PREFIX=granite-8b-flex"
            ]

            for var in required_vars:
                if var in output:
                    self.log.info("✓ Found: %s", var)
                else:
                    self.log.error("✗ Missing: %s", var)
                    return False

            self.log.info(
                "All FLEX environment variables verified successfully")
            return True

        except Exception as ex:
            self.log.error("Failed to verify FLEX variables: %s", ex)
            return False

    def _install_acelyzer(self, container_id):
        """
        Install acelyzer in the container as root user.

        :param container_id: Container ID
        :return: True if installation successful, False otherwise
        """
        try:
            self.log.info("Installing acelyzer in container")

            install_cmd = (
                f"cd {self.TRACE_ANALYZER_PATH} && "
                f"export AIUPROF_PATH=$PWD && "
                f"export SETUPTOOLS_SCM_PRETEND_VERSION=1.0.0 && "
                f"pip install ."
            )

            is_nonroot = (container_id ==
                          ObservabilityTests._nonroot_container_id)
            if is_nonroot:
                returncode, stdout, stderr = self._run_as_user(
                    f"podman exec -u 0 {container_id} bash -c "
                    + shlex.quote(install_cmd))
            else:
                returncode, stdout_raw, stderr_raw = ObservabilityTests._podman.exec_command(
                    container_id=container_id,
                    command=["bash", "-c", install_cmd],
                    user="0"
                )
                stdout = stdout_raw.decode(
                    'utf-8') if isinstance(stdout_raw, bytes) else stdout_raw
                stderr = stderr_raw.decode(
                    'utf-8') if isinstance(stderr_raw, bytes) else stderr_raw

            if returncode != 0:
                self.log.error("Failed to install acelyzer: %s", stderr)
                return False

            self.log.info("Acelyzer installed successfully")
            return True

        except Exception as ex:
            self.log.error("Exception during acelyzer installation: %s", ex)
            return False

    def _find_trace_files(self, container_id):
        """
        Find and count trace files in the container.

        :param container_id: Container ID
        :return: Tuple of (file_count, file_location)
        """
        try:
            self.log.info("Searching for trace files in container")

            # Find trace files
            is_nonroot = (container_id ==
                          ObservabilityTests._nonroot_container_id)
            if is_nonroot:
                _, files_output, _ = self._run_as_user(
                    f"podman exec {container_id} bash -c "
                    + shlex.quote("find / -name 'granite-8b-flex-*.json' -type f 2>/dev/null | head -20"))
            else:
                _, files_out_raw, _ = ObservabilityTests._podman.exec_command(
                    container_id=container_id,
                    command=[
                        "bash", "-c", "find / -name 'granite-8b-flex-*.json' -type f 2>/dev/null | head -20"]
                )
                files_output = files_out_raw.decode(
                    'utf-8') if isinstance(files_out_raw, bytes) else files_out_raw
            files_output = files_output.strip()

            if files_output:
                files = files_output.split('\n')
                self.log.info("Found trace files:")
                for f in files[:10]:
                    self.log.info("  - %s", f)

                # Get directory of first file
                file_location = files[0].strip().rsplit(
                    '/', 1)[0] if files else None

                # Count total files
                if is_nonroot:
                    _, count_output, _ = self._run_as_user(
                        f"podman exec {container_id} bash -c "
                        + shlex.quote("find / -name 'granite-8b-flex-*.json' -type f 2>/dev/null | wc -l"))
                else:
                    _, count_raw, _ = ObservabilityTests._podman.exec_command(
                        container_id=container_id,
                        command=[
                            "bash", "-c", "find / -name 'granite-8b-flex-*.json' -type f 2>/dev/null | wc -l"]
                    )
                    count_output = count_raw.decode(
                        'utf-8') if isinstance(count_raw, bytes) else count_raw
                count_output = count_output.strip()
                file_count = int(count_output) if count_output.isdigit() else 0

                self.log.info("Total trace files found: %d at location: %s",
                              file_count, file_location)
                return file_count, file_location
            else:
                self.log.warning("No trace files found")
                return 0, None

        except Exception as ex:
            self.log.error("Failed to find trace files: %s", ex)
            return 0, None

    def _run_acelyzer(self, container_id, trace_location):
        """
        Run acelyzer to analyze trace files.

        :param container_id: Container ID
        :param trace_location: Location of trace files
        :return: True if successful, False otherwise
        """
        try:
            self.log.info("Running acelyzer to analyze trace files")

            acelyzer_command = (
                f"cd {self.TRACE_ANALYZER_PATH} && "
                f"export AIUPROF_PATH={self.TRACE_ANALYZER_PATH} && "
                f"python3 {self.TRACE_ANALYZER_PATH}/bin/acelyzer.py "
                f"-i '{trace_location}/granite-*.json' "
                f"-o /tmp/out.json "
                f"--flex_ts_fix"
            )

            self.log.info("Executing acelyzer command")
            is_nonroot = (container_id ==
                          ObservabilityTests._nonroot_container_id)
            if is_nonroot:
                returncode, stdout, stderr = self._run_as_user(
                    f"podman exec {container_id} bash -c "
                    + shlex.quote(acelyzer_command))
            else:
                returncode, stdout_raw, stderr_raw = ObservabilityTests._podman.exec_command(
                    container_id=container_id,
                    command=["bash", "-c", acelyzer_command]
                )
                stdout = stdout_raw.decode(
                    'utf-8') if isinstance(stdout_raw, bytes) else stdout_raw
                stderr = stderr_raw.decode(
                    'utf-8') if isinstance(stderr_raw, bytes) else stderr_raw

            # Log acelyzer output
            self.log.info("=== Acelyzer Command Output ===")
            if stdout:
                self.log.info("Acelyzer stdout:\n%s", stdout)
            else:
                self.log.info("Acelyzer stdout: (empty)")

            if stderr:
                self.log.info("Acelyzer stderr:\n%s", stderr)
            else:
                self.log.info("Acelyzer stderr: (empty)")

            if returncode != 0:
                self.log.error(
                    "Acelyzer failed with exit code %d", returncode)
                return False

            self.log.info("Acelyzer completed successfully")
            return True

        except Exception as ex:
            self.log.error("Exception during acelyzer execution: %s", ex)
            return False

    def _verify_acelyzer_output(self, container_id):
        """
        Verify acelyzer output files exist and contain valid data.

        :param container_id: Container ID
        :return: True if output is valid, False otherwise
        """
        try:
            self.log.info("Verifying acelyzer output files")

            is_nonroot = (container_id ==
                          ObservabilityTests._nonroot_container_id)

            # Check if output file exists
            if is_nonroot:
                rc, output, _ = self._run_as_user(
                    f"podman exec {container_id} bash -c "
                    + shlex.quote("ls -lh /tmp/out.json 2>&1"))
            else:
                _, out_raw, _ = ObservabilityTests._podman.exec_command(
                    container_id=container_id,
                    command=["bash", "-c", "ls -lh /tmp/out.json 2>&1"]
                )
                output = out_raw.decode(
                    'utf-8') if isinstance(out_raw, bytes) else out_raw
            output = output.strip()

            if "No such file" in output:
                self.log.error("Output file /tmp/out.json not found")
                return False

            self.log.info("Output file exists: %s", output)

            # Display summary CSV
            if is_nonroot:
                _, summary_output, _ = self._run_as_user(
                    f"podman exec {container_id} bash -c "
                    + shlex.quote("cat /tmp/out_summary.csv 2>/dev/null"))
            else:
                _, sum_raw, _ = ObservabilityTests._podman.exec_command(
                    container_id=container_id,
                    command=["bash", "-c",
                             "cat /tmp/out_summary.csv 2>/dev/null"]
                )
                summary_output = sum_raw.decode(
                    'utf-8') if isinstance(sum_raw, bytes) else sum_raw
            summary_output = summary_output.strip()

            self.log.info("=== Summary CSV ===")
            if summary_output:
                self.log.info("Summary CSV Output:\n%s", summary_output)
            else:
                self.log.warning("Summary file not found or empty")

            # Display active CSV
            if is_nonroot:
                _, active_output, _ = self._run_as_user(
                    f"podman exec {container_id} bash -c "
                    + shlex.quote("cat /tmp/out_active.csv 2>/dev/null"))
            else:
                _, act_raw, _ = ObservabilityTests._podman.exec_command(
                    container_id=container_id,
                    command=["bash", "-c",
                             "cat /tmp/out_active.csv 2>/dev/null"]
                )
                active_output = act_raw.decode(
                    'utf-8') if isinstance(act_raw, bytes) else act_raw
            active_output = active_output.strip()

            self.log.info("=== Active CSV ===")
            if not active_output:
                self.log.error(
                    "Active CSV (out_active.csv) not found or empty")
                return False

            self.log.info("Active CSV Output:\n%s", active_output)

            # Parse and validate active percentage
            lines = active_output.split('\n')
            if len(lines) >= 2:
                data_line = lines[-1].split()
                if len(data_line) >= 5:
                    try:
                        active_pct = float(data_line[4])
                        self.log.info(
                            "AIU Active Percentage: %.2f%%", active_pct)
                    except (ValueError, IndexError) as parse_ex:
                        self.log.warning(
                            "Could not parse active percentage: %s", parse_ex)

            return True

        except Exception as ex:
            self.log.error("Failed to verify acelyzer output: %s", ex)
            return False

    def tearDown(self):
        """Clean up: stop inference, remove containers, and clean all temporary files."""
        self.log.info("=== Starting Cleanup ===")

        test_name = self._testMethodName
        self.log.info("Cleaning up after test: %s", test_name)

        self.log.info("Stopping inference thread")
        self.stop_inference()

        try:
            self.log.info("Killing any lingering curl processes")
            self.run_cmd("pkill -9 -f 'curl.*v1/completions' || true")
        except Exception as ex:
            self.log.debug("Failed to kill curl processes: %s", ex)

        self.log.info("Cleaning up containers")
        containers_to_cleanup = []

        if test_name in ("test_aiu_smi_root", "test_trace_analyzer_root"):
            if ObservabilityTests._root_container_id:
                if test_name == "test_trace_analyzer_root" or getattr(self, 'status', 'PASS') not in ('PASS', None):
                    containers_to_cleanup.append(
                        ("root", ObservabilityTests._root_container_id))

        if test_name in ("test_aiu_smi_nonroot", "test_trace_analyzer_nonroot"):
            if ObservabilityTests._nonroot_container_id:
                if test_name == "test_trace_analyzer_nonroot" or getattr(self, 'status', 'PASS') not in ('PASS', None):
                    containers_to_cleanup.append(
                        ("nonroot", ObservabilityTests._nonroot_container_id))

        for container_type, container_id in containers_to_cleanup:
            if container_id and ObservabilityTests._podman:
                try:
                    self.log.info("Cleaning up %s container: %s",
                                  container_type, container_id)
                    is_nr = (container_type == "nonroot")

                    try:
                        self.log.info("Stopping %s container: %s",
                                      container_type, container_id)
                        if is_nr:
                            self._run_as_user(
                                f"podman stop -t 0 {container_id} || true")
                        else:
                            ObservabilityTests._podman.stop(container_id)
                    except Exception as stop_ex:
                        self.log.warning(
                            "Failed to stop %s container: %s", container_type, stop_ex)

                    try:
                        self.log.info("Removing %s container: %s",
                                      container_type, container_id)
                        if is_nr:
                            self._run_as_user(
                                f"podman rm -f {container_id} || true")
                        else:
                            ObservabilityTests._podman.remove(
                                container_id, force=True)
                        self.log.info(
                            "%s container removed successfully", container_type.capitalize())
                    except Exception as rm_ex:
                        self.log.warning(
                            "Failed to remove %s container: %s", container_type, rm_ex)

                except Exception as ex:
                    self.log.error("%s container cleanup failed: %s",
                                   container_type.capitalize(), ex)

        # Remove the host-side trace analyzer clone
        try:
            self.run_cmd(f"rm -rf {self.TRACE_ANALYZER_PATH}")
            self.log.info("Removed: %s", self.TRACE_ANALYZER_PATH)
        except Exception as ex:
            self.log.warning("Failed to remove %s: %s",
                             self.TRACE_ANALYZER_PATH, ex)

        self.log.info("Resetting instance variables")
        for container_type, _ in containers_to_cleanup:
            if container_type == "root":
                ObservabilityTests._root_container_id = None
                ObservabilityTests._save_container_ids()
            elif container_type == "nonroot":
                ObservabilityTests._nonroot_container_id = None
                ObservabilityTests._save_container_ids()
        if test_name == "test_trace_analyzer_nonroot":
            try:
                if os.path.exists(ObservabilityTests.CONTAINER_ID_FILE):
                    os.remove(ObservabilityTests.CONTAINER_ID_FILE)
                    self.log.info("Removed container ID file")
            except Exception as ex:
                self.log.debug("Failed to remove container ID file: %s", ex)

        self.log.info("=== Cleanup Finished ===")
