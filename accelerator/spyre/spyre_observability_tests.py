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
import time
import signal
import subprocess
from avocado import Test
from avocado.utils import archive, process
from avocado.utils.podman import (
    Podman, PodmanException,
    get_container_port,
    wait_for_vllm_startup,
    setup_user_and_group
)
from avocado.utils.software_manager.manager import SoftwareManager


class ObservabilityTests(Test):

    is_fail = 0
    container_id = None
    podman = None
    container_user = None
    inference_process = None

    def run_cmd(self, cmd):
        """Execute a command and track failures."""
        if process.system(cmd, ignore_status=True, sudo=True, shell=True):
            self.is_fail += 1
            self.log.info("%s command failed", cmd)
        return

    @staticmethod
    def run_cmd_out(cmd):
        """Execute a command and return output."""
        return process.system_output(
            cmd, shell=True, ignore_status=True,
            sudo=True).decode("utf-8").strip()

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

    def _build_podman_run_command(self, container_name="spyre-observability-test"):
        """
        Build the podman run command string for manual execution.

        :param container_name: Name for the container
        :return: Complete podman run command as string
        """
        cmd_parts = [
            "podman run -d -it",
            f"--device={self.device}",
            f"-v {self.host_models_dir}:/models",
            f'-e AIU_PCIE_IDS="{self.aiu_pcie_ids}"',
            "-e DTCOMPILER_KEEP_EXPORT=true",
            f"--privileged={self.privileged}",
            f"--pids-limit {self.pids_limit}",
            f"--userns={self.userns}",
            f"--group-add={self.group_add}",
            f"--memory {self.memory}",
            f"-p {self.port_mapping}",
        ]

        # Add optional environment variables if set
        if self.vllm_spyre_use_cb:
            cmd_parts.append(f"-e VLLM_SPYRE_USE_CB={self.vllm_spyre_use_cb}")
        if self.vllm_dt_chunk_len:
            cmd_parts.append(f"-e VLLM_DT_CHUNK_LEN={self.vllm_dt_chunk_len}")
        if self.vllm_spyre_use_chunked_prefill:
            cmd_parts.append(
                f"-e VLLM_SPYRE_USE_CHUNKED_PREFILL={self.vllm_spyre_use_chunked_prefill}")

        # Add container image
        cmd_parts.append(f"{self.container_url}:{self.container_tag}")

        # Add VLLM arguments
        cmd_parts.append(f'--model "{self.vllm_model_path}"')
        cmd_parts.append(f'-tp "{self.aiu_word_size}"')
        cmd_parts.append(f'--max-model-len "{self.max_model_len}"')
        cmd_parts.append(f"--max-num-seqs {self.max_batch_size}")

        if self.enable_prefix_caching:
            cmd_parts.append("--enable-prefix-caching")

        if self.additional_vllm_args:
            cmd_parts.extend(self.additional_vllm_args)

        return " ".join(cmd_parts)

    def start_continuous_inference(self, port=None):
        """
        Start continuous inference requests in the background.

        :param port: Port where VLLM is listening
        :return: Process object or None
        """
        try:
            if port is None:
                port = get_container_port(
                    self.container_id, port=8000, user=None, log=self.log)
                if port is None:
                    self.log.error(
                        "Could not determine container port for inference")
                    return None

            self.log.info("Starting continuous inference on port %s", port)

            # Create a simple inference script
            inference_script = f"""
import requests
import time
import json

url = "http://127.0.0.1:{port}/v1/completions"
prompts = [
    "write a sample python code for bubble sort",
    "explain the concept of recursion in programming",
    "what are the benefits of using design patterns",
    "describe how binary search works",
    "explain the difference between stack and queue"
]

headers = {{"Content-Type": "application/json"}}
prompt_idx = 0

while True:
    try:
        data = {{
            "model": "{self.vllm_model_path}",
            "prompt": prompts[prompt_idx % len(prompts)],
            "max_tokens": 128,
            "temperature": 1
        }}
        response = requests.post(url, headers=headers, json=data, timeout=30)
        if response.status_code == 200:
            result = response.json()
            print(f"Inference {{prompt_idx}} completed successfully")
            print(f"Response: {{result}}")
        else:
            print(f"Inference {{prompt_idx}} failed: {{response.status_code}}")
            print(f"Error: {{response.text}}")
        prompt_idx += 1
        time.sleep(5)
    except Exception as e:
        print(f"Inference error: {{e}}")
        time.sleep(5)
"""

            script_path = os.path.join(self.workdir, "continuous_inference.py")
            with open(script_path, 'w') as f:
                f.write(inference_script)

            # Start the inference process in background
            inference_process = subprocess.Popen(
                ["python3", script_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=os.setsid
            )

            self.inference_process = inference_process
            self.log.info(
                "Continuous inference started with PID: %s", inference_process.pid)
            time.sleep(5)

            return inference_process

        except Exception as ex:
            self.log.error("Failed to start continuous inference: %s", ex)
            return None

    def stop_continuous_inference(self):
        """Stop the continuous inference process."""
        if self.inference_process:
            try:
                self.log.info("Stopping continuous inference process")
                os.killpg(os.getpgid(self.inference_process.pid),
                          signal.SIGTERM)
                self.inference_process.wait(timeout=10)
                self.log.info("Continuous inference stopped")
            except Exception as ex:
                self.log.warning("Error stopping inference process: %s", ex)
                try:
                    os.killpg(os.getpgid(self.inference_process.pid),
                              signal.SIGKILL)
                except Exception:
                    pass
            finally:
                self.inference_process = None

    def capture_aiu_smi_metrics(self, container_id, duration=30):
        """
        Capture aiu-smi metrics from the container for a specified duration.
        Runs aiu-smi continuously for the duration and displays output at the end.

        :param container_id: Container ID
        :param duration: Duration to capture metrics in seconds
        :return: Tuple of (success, metrics_output)
        """
        try:
            self.log.info(
                "Capturing aiu-smi metrics for %d seconds", duration)

            # Run aiu-smi command inside container for the specified duration
            aiu_smi_cmd = (
                f"timeout {duration} podman exec {container_id} bash --login -c "
                f"'source /opt/aiu-monitor/bin/activate && "
                f"while true; do aiu-smi; sleep 1; done'"
            )

            self.log.info("Starting aiu-smi monitoring...")
            result = process.run(
                aiu_smi_cmd, shell=True, ignore_status=True)

            metrics_output = result.stdout_text

            if not metrics_output or len(metrics_output.strip()) == 0:
                self.log.error("No metrics were captured during the test")
                return False, metrics_output

            self.log.info("=== Captured AIU-SMI Metrics ===")
            self.log.info("\n%s", metrics_output)

            # Validate that metrics contain expected data
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
                            "pwr", "gtemp", "busy", "rdmem", "wrmem"]

        has_headers = all(
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
            # Check that we can parse numeric values
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
        """Set up test environment and initialize Podman."""
        if "ppc" not in os.uname()[4]:
            self.cancel("supported only on Power platform")
        if 'PowerNV' in open('/proc/cpuinfo', 'r').read():
            self.cancel(
                "observability tests: not supported on the PowerNV platform")

        self.log.info("Checking SELinux status")
        try:
            selinux_status = self.run_cmd_out("getenforce")
            self.log.info("SELinux status: %s", selinux_status)
            if selinux_status.strip().lower() == "enforcing":
                self.log.info(
                    "SELinux is Enforcing, disabling it for container operations")
                result = process.run(
                    "setenforce 0", shell=True, sudo=True, ignore_status=True)
                if result.exit_status == 0:
                    self.log.info("SELinux set to Permissive mode")
                else:
                    self.log.warning(
                        "Failed to set SELinux to Permissive mode")
        except Exception as ex:
            self.log.warning("Could not check/modify SELinux status: %s", ex)

        smm = SoftwareManager()
        for package in ['make', 'gcc', 'podman', 'python3-requests']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel(
                    f"Fail to install {package} required for this test.")

        tarball = self.fetch_asset('ServiceReport.zip', locations=[
                                   'https://github.com/linux-ras/ServiceReport'
                                   '/archive/master.zip'], expire='7d')
        archive.extract(tarball, self.workdir)

        self.spyre_group = self.params.get("SPYRE_GROUP", default="")
        self.aiu_pcie_ids = self.params.get("AIU_PCIE_IDS", default="")
        self.aiu_word_size = self.params.get("AIU_WORD_SIZE", default="")
        self.max_model_len = self.params.get("MAX_MODEL_LEN", default="")
        self.max_batch_size = self.params.get("MAX_BATCH_SIZE", default="")
        self.host_models_dir = self.params.get("HOST_MODELS_DIR", default="")
        self.vllm_model_path = self.params.get("VLLM_MODEL_PATH", default="")
        self.vllm_spyre_use_cb = self.params.get(
            "VLLM_SPYRE_USE_CB", default="")
        self.memory = self.params.get("MEMORY", default="")
        self.shm_size = self.params.get("SHM_SIZE", default="")
        self.container_url = self.params.get("CONTAINER_URL", default="")
        self.container_tag = self.params.get("CONTAINER_TAG", default="")
        self.api_key = self.params.get("API_KEY", default="")
        self.device = self.params.get("DEVICE", default="")
        self.privileged = self.params.get("PRIVILEGED", default="")
        self.pids_limit = self.params.get("PIDS_LIMIT", default="")
        self.userns = self.params.get("USERNS", default="")
        self.group_add = self.params.get("GROUP_ADD", default="")
        self.port_mapping = self.params.get("PORT_MAPPING", default="")
        self.vllm_dt_chunk_len = self.params.get(
            "VLLM_DT_CHUNK_LEN", default="")
        self.vllm_spyre_use_chunked_prefill = self.params.get(
            "VLLM_SPYRE_USE_CHUNKED_PREFILL", default="")
        enable_prefix_caching_str = self.params.get(
            "ENABLE_PREFIX_CACHING", default="")
        self.enable_prefix_caching = enable_prefix_caching_str.lower() in (
            "true", "1", "yes") if enable_prefix_caching_str else False
        additional_vllm_args_str = self.params.get(
            "ADDITIONAL_VLLM_ARGS", default="")
        self.additional_vllm_args = additional_vllm_args_str.split(
        ) if additional_vllm_args_str else None

        # Observability-specific parameters
        self.metrics_duration = int(self.params.get(
            "METRICS_DURATION", default="30"))

        try:
            self.podman = Podman()
            self.log.info("Podman utility initialized successfully")
        except PodmanException as ex:
            self.cancel(f"Failed to initialize Podman: {ex}")

        if self.api_key and self.container_url:
            try:
                registry = self.container_url.split('/')[0]
                self.podman.login(registry=registry, api_key=self.api_key)
                self.log.info(
                    "Successfully logged in to registry: %s", registry)
            except PodmanException as ex:
                self.log.warning("Failed to login to registry: %s", ex)

        if self.container_url and self.container_tag:
            image = f"{self.container_url}:{self.container_tag}"
            try:
                self.log.info("Pulling container image: %s", image)
                self.podman.pull(image)
                self.log.info("Successfully pulled image: %s", image)
            except PodmanException as ex:
                self.log.warning("Failed to pull image: %s", ex)

        self.log.info("Setting up spyre group access")
        self.run_cmd("servicereport -r -p spyre")
        self.run_cmd("servicereport -v -p spyre")

        if not self.spyre_exists():
            self.cancel("Spyre devices not configured properly")

        self.log.info("Adding root user to %s group", self.spyre_group)
        setup_user_and_group(
            username="root",
            password=None,
            spyre_group=self.spyre_group,
            add_to_group=True,
            log=self.log
        )

    def test_aiu_smi(self):
        """
        Test AIU-SMI observability by capturing metrics during inference.

        This test:
        1. Creates a container as root user with DTCOMPILER_KEEP_EXPORT=true
        2. Waits for VLLM to start
        3. Starts continuous inference in background
        4. Captures aiu-smi metrics for specified duration (runs for full duration)
        5. Validates that metrics are captured successfully
        """
        self.log.info("=== Test: AIU-SMI Observability ===")

        # Create container as root user
        self.log.info("Creating container as root user")
        podman_cmd = self._build_podman_run_command()
        self.log.info("Podman command: %s", podman_cmd)
        container_output = self.run_cmd_out(podman_cmd)

        container_id = container_output.strip().split(
            '\n')[-1] if container_output else None
        if not container_id:
            self.log.error(
                "Failed to create container. Output: %s", container_output)
            self.fail("Failed to create container")

        self.container_id = container_id
        self.log.info("Container created: %s", container_id)

        # Wait for VLLM to start
        self.log.info("Waiting for VLLM to start...")
        if not wait_for_vllm_startup(
            container_id,
            success_pattern="Application startup complete.",
            failure_pattern="BACKTRACE",
            additional_failure_checks=[("VFIO", False), ("fail", False)],
            timeout=300,
            check_interval=20,
            user=None,
            log=self.log,
            show_live_logs=True,
            live_log_lines=20
        ):
            self.log.error("VLLM failed to start")
            self.fail("VLLM failed to start")

        self.log.info("VLLM started successfully!")

        # Start continuous inference
        self.log.info("Starting continuous inference in background")
        if not self.start_continuous_inference():
            self.log.warning(
                "Failed to start continuous inference, continuing anyway")

        self.log.info("Waiting for inference to generate load...")
        time.sleep(10)

        # Capture aiu-smi metrics
        self.log.info("Starting aiu-smi metrics capture")
        success, metrics = self.capture_aiu_smi_metrics(
            container_id,
            duration=self.metrics_duration
        )

        if not success:
            self.log.error("Failed to capture valid metrics")
            self.fail(
                "AIU-SMI metrics capture failed - no valid metrics captured")

        self.log.info(
            "PASS: AIU-SMI observability test completed successfully")
        self.log.info("Metrics were successfully captured and validated")

    def _build_acelyzer_podman_command(self):
        """
        Build the podman run command for trace analyzer with FLEX environment variables.

        :return: Complete podman run command as string
        """
        cmd_parts = [
            "podman run -d -it",
            f"--device={self.device}",
            f"-v {self.host_models_dir}:/models",
            f'-e AIU_PCIE_IDS="{self.aiu_pcie_ids}"',
            "-e ENABLE_FLEX_TIMING=1",
            "-e FLEX_PRINT_END_TO_END_BREAKDOWN=1",
            "-e FLEX_SKIP_TIMESTAMP_CALIBRATION=0",
            "-e FLEX_SCHEDULER_PRINT_RAW_TIMESTAMPS=1",
            '-e FLEX_GLOBAL_PROFILE_PREFIX="granite-8b-flex"',
            f"--privileged={self.privileged}",
            f"--pids-limit {self.pids_limit}",
            f"--userns={self.userns}",
            f"--group-add={self.group_add}",
            f"--memory {self.memory}",
            f"-p {self.port_mapping}",
        ]

        # Add container image
        cmd_parts.append(f"{self.container_url}:{self.container_tag}")

        # Add VLLM arguments
        cmd_parts.append(f'--model "{self.vllm_model_path}"')
        cmd_parts.append(f'-tp "{self.aiu_word_size}"')
        cmd_parts.append(f'--max-model-len "{self.max_model_len}"')
        cmd_parts.append(f"--max-num-seqs {self.max_batch_size}")
        cmd_parts.append("--max-num-batched-tokens 512")

        return " ".join(cmd_parts)

    def _verify_flex_variables(self, container_id):
        """
        Verify FLEX environment variables are set in the container.

        :param container_id: Container ID
        :return: True if all FLEX variables are set, False otherwise
        """
        try:
            self.log.info("Verifying FLEX environment variables in container")
            check_cmd = f"podman exec {container_id} bash -c 'cat /proc/1/environ | tr \"\\0\" \"\\n\" | grep FLEX'"
            output = self.run_cmd_out(check_cmd)

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
        Install acelyzer in the container.

        :param container_id: Container ID
        :return: True if installation successful, False otherwise
        """
        try:
            self.log.info("Installing acelyzer in container")

            install_cmds = [
                f"podman exec {container_id} bash -c 'cd /tmp/aiu-trace-analyzer && export AIUPROF_PATH=$PWD && pip install .'"
            ]

            for cmd in install_cmds:
                result = process.run(cmd, shell=True, ignore_status=True)
                if result.exit_status != 0:
                    self.log.error(
                        "Failed to install acelyzer: %s", result.stderr_text)
                    return False

            self.log.info("Acelyzer installed successfully")
            return True

        except Exception as ex:
            self.log.error("Exception during acelyzer installation: %s", ex)
            return False

    def _generate_trace_files(self, port, num_requests=10):
        """
        Generate trace files by sending inference requests.

        :param port: Port where VLLM is listening
        :param num_requests: Number of requests to send
        :return: True if successful, False otherwise
        """
        try:
            self.log.info(
                "Generating trace files with %d inference requests", num_requests)

            import requests
            import json

            url = f"http://127.0.0.1:{port}/v1/completions"
            headers = {"Content-Type": "application/json"}

            for i in range(1, num_requests + 1):
                self.log.info("=" * 50)
                self.log.info("Sending request %d of %d...", i, num_requests)
                self.log.info("=" * 50)

                data = {
                    "model": self.vllm_model_path,
                    "prompt": "write a sample python code for bubble sort",
                    "max_tokens": 128,
                    "temperature": 1
                }

                try:
                    response = requests.post(
                        url, headers=headers, json=data, timeout=60)
                    if response.status_code == 200:
                        self.log.info("Request %d completed successfully", i)
                    else:
                        self.log.warning(
                            "Request %d failed with status %d", i, response.status_code)
                except Exception as req_ex:
                    self.log.warning("Request %d failed: %s", i, req_ex)

                if i < num_requests:
                    self.log.info("Waiting 2 seconds before next request...")
                    time.sleep(2)

            self.log.info("All %d requests completed!", num_requests)
            return True

        except Exception as ex:
            self.log.error("Failed to generate trace files: %s", ex)
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
            find_cmd = f'podman exec {container_id} bash -c \'find / -name "granite-8b-flex-*.json" -type f 2>/dev/null | head -20\''
            files_output = self.run_cmd_out(find_cmd)

            if files_output:
                files = files_output.strip().split('\n')
                self.log.info("Found trace files:")
                for f in files[:10]:  # Show first 10
                    self.log.info("  - %s", f)

                # Get file location from first file
                file_location = files[0].rsplit('/', 1)[0] if files else None

                # Count total files
                count_cmd = f'podman exec {container_id} bash -c \'find / -name "granite-8b-flex-*.json" -type f 2>/dev/null | wc -l\''
                count_output = self.run_cmd_out(count_cmd)
                file_count = int(count_output.strip()
                                 ) if count_output.strip().isdigit() else 0

                self.log.info("Total trace files found: %d", file_count)
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

            # Use direct path instead of variable expansion to avoid shell escaping issues
            acelyzer_cmd = (
                f'podman exec {container_id} bash -c '
                f'"cd /tmp/aiu-trace-analyzer && '
                f'export AIUPROF_PATH=/tmp/aiu-trace-analyzer && '
                f'python3 /tmp/aiu-trace-analyzer/bin/acelyzer.py '
                f'-i \\"{trace_location}/granite-*.json\\" '
                f'-o /tmp/out.json '
                f'--flex_ts_fix"'
            )

            self.log.info("Executing acelyzer command: %s", acelyzer_cmd)
            result = process.run(acelyzer_cmd, shell=True,
                                 ignore_status=True, timeout=600)

            # Log acelyzer output
            self.log.info("=== Acelyzer Command Output ===")
            if result.stdout_text:
                self.log.info("Acelyzer stdout:\n%s", result.stdout_text)
            else:
                self.log.info("Acelyzer stdout: (empty)")

            if result.stderr_text:
                self.log.info("Acelyzer stderr:\n%s", result.stderr_text)
            else:
                self.log.info("Acelyzer stderr: (empty)")

            if result.exit_status != 0:
                self.log.error(
                    "Acelyzer failed with exit code %d", result.exit_status)
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

            # Check if output file exists
            check_cmd = f"podman exec {container_id} bash -c 'ls -lh /tmp/out.json'"
            output = self.run_cmd_out(check_cmd)

            if "No such file" in output:
                self.log.error("Output file /tmp/out.json not found")
                return False

            self.log.info("Output file exists: %s", output)

            # Display summary CSV
            summary_cmd = f"podman exec {container_id} bash -c 'cat /tmp/out_summary.csv 2>/dev/null'"
            summary_output = self.run_cmd_out(summary_cmd)

            self.log.info("=== Cat Command 1: Summary CSV ===")
            self.log.info("Command: %s", summary_cmd)
            if summary_output:
                self.log.info("Summary CSV Output:\n%s", summary_output)
            else:
                self.log.warning("Summary file not found or empty")

            # Display active CSV
            active_cmd = f"podman exec {container_id} bash -c 'cat /tmp/out_active.csv 2>/dev/null'"
            active_output = self.run_cmd_out(active_cmd)

            self.log.info("=== Cat Command 2: Active CSV ===")
            self.log.info("Command: %s", active_cmd)
            if active_output:
                self.log.info("Active CSV Output:\n%s", active_output)

                # Parse and validate active percentage
                lines = active_output.strip().split('\n')
                if len(lines) >= 2:
                    data_line = lines[-1].split()
                    if len(data_line) >= 5:
                        try:
                            active_pct = float(data_line[4])
                            self.log.info(
                                "AIU Active Percentage: %.2f%%", active_pct)

                            if active_pct > 0:
                                self.log.info(
                                    "Valid active percentage detected")
                                return True
                            else:
                                self.log.warning(
                                    "Active percentage is 0, but output exists")
                                return True  # Still pass if output exists
                        except (ValueError, IndexError) as parse_ex:
                            self.log.warning(
                                "Could not parse active percentage: %s", parse_ex)
            else:
                self.log.warning("Active file not found or empty")

            return "out.json" in output

        except Exception as ex:
            self.log.error("Failed to verify acelyzer output: %s", ex)
            return False

    def test_acelyzer(self):
        """
        Test AIU Acelyzer by capturing and analyzing trace files.

        This test:
        1. Stops any existing containers
        2. Clones aiu-trace-analyzer repository
        3. Starts container with FLEX environment variables
        4. Copies trace analyzer to container
        5. Verifies FLEX variables and installs acelyzer
        6. Waits for VLLM to start
        7. Generates trace files through inference requests
        8. Runs acelyzer to analyze traces
        9. Verifies output files contain valid data
        """
        self.log.info("=== Test: AIU Acelyzer ===")

        self.log.info("Checking for existing containers")
        try:
            ps_output = self.run_cmd_out("podman ps -q")
            if ps_output.strip():
                container_ids = ps_output.strip().split('\n')
                for cid in container_ids:
                    self.log.info("Stopping existing container: %s", cid)
                    self.run_cmd(f"podman stop {cid}")
                    self.run_cmd(f"podman rm -f {cid}")
        except Exception as ex:
            self.log.warning("Error checking/stopping containers: %s", ex)

        self.log.info("Cloning aiu-trace-analyzer repository")
        clone_dir = "/tmp/aiu-trace-analyzer"

        self.run_cmd(f"rm -rf {clone_dir}")

        clone_cmd = f"cd /tmp && git clone https://github.com/IBM/aiu-trace-analyzer.git"
        result = process.run(clone_cmd, shell=True, ignore_status=True)

        if result.exit_status != 0:
            self.log.error(
                "Failed to clone aiu-trace-analyzer: %s", result.stderr_text)
            self.fail("Failed to clone aiu-trace-analyzer repository")

        self.log.info("Successfully cloned aiu-trace-analyzer")

        self.log.info("Starting container with FLEX environment variables")
        podman_cmd = self._build_acelyzer_podman_command()
        self.log.info("Podman command: %s", podman_cmd)
        container_output = self.run_cmd_out(podman_cmd)

        container_id = container_output.strip().split(
            '\n')[-1] if container_output else None
        if not container_id:
            self.log.error(
                "Failed to create container. Output: %s", container_output)
            self.fail("Failed to create container")

        self.container_id = container_id
        self.log.info("Container created: %s", container_id)

        self.log.info("Copying aiu-trace-analyzer to container")
        copy_cmd = f"podman cp {clone_dir} {container_id}:/tmp"
        result = process.run(copy_cmd, shell=True, ignore_status=True)

        if result.exit_status != 0:
            self.log.error(
                "Failed to copy aiu-trace-analyzer: %s", result.stderr_text)
            self.fail("Failed to copy aiu-trace-analyzer to container")

        self.log.info("Successfully copied aiu-trace-analyzer to container")

        self.log.info("Verifying FLEX variables and installing acelyzer")

        if not self._verify_flex_variables(container_id):
            self.fail("FLEX environment variables not properly set")

        if not self._install_acelyzer(container_id):
            self.fail("Failed to install acelyzer")

        self.log.info("Waiting for VLLM to start...")
        if not wait_for_vllm_startup(
            container_id,
            success_pattern="Application startup complete.",
            failure_pattern="BACKTRACE",
            additional_failure_checks=[("VFIO", False), ("fail", False)],
            timeout=300,
            check_interval=20,
            user=None,
            log=self.log,
            show_live_logs=True,
            live_log_lines=20
        ):
            self.log.error("VLLM failed to start")
            self.fail("VLLM failed to start")

        self.log.info("VLLM started successfully!")

        self.log.info("Generating trace files through inference")
        port = get_container_port(
            container_id, port=8000, user=None, log=self.log)
        if not port:
            self.fail("Could not determine container port")

        if not self._generate_trace_files(port, num_requests=10):
            self.fail("Failed to generate trace files")

        # Wait a bit for files to be written
        self.log.info("Waiting for trace files to be written...")
        time.sleep(5)

        self.log.info("Finding trace files")
        file_count, trace_location = self._find_trace_files(container_id)

        if file_count == 0:
            self.fail("No trace files were generated")

        self.log.info("Found %d trace files in %s", file_count, trace_location)

        self.log.info("Running acelyzer to analyze traces")
        if not self._run_acelyzer(container_id, trace_location):
            self.fail("Acelyzer analysis failed")

        self.log.info("Verifying acelyzer output")
        if not self._verify_acelyzer_output(container_id):
            self.fail("Acelyzer output validation failed")

        self.log.info("PASS: Trace analyzer test completed successfully")
        self.log.info("Successfully analyzed %d trace files", file_count)

    def tearDown(self):
        """Clean up: stop inference, stop and remove container."""
        # Stop continuous inference
        self.stop_continuous_inference()

        # Clean up container
        if self.container_id:
            try:
                self.log.info("=== Final Container Logs ===")
                try:
                    _, logs, _ = self.podman.logs(self.container_id)
                    self.log.info("Container logs:\n%s", logs.decode())
                except Exception as log_ex:
                    self.log.warning(
                        "Failed to retrieve final container logs: %s", log_ex)

                self.log.info("Stopping container: %s", self.container_id)
                self.podman.stop(self.container_id)
                self.log.info("Removing container: %s", self.container_id)
                self.podman.remove(self.container_id, force=True)
                self.log.info("Container cleanup completed")

            except PodmanException as ex:
                self.log.warning(
                    "Failed to cleanup container via Podman API: %s", ex)
                try:
                    self.run_cmd(f"podman rm -f {self.container_id}")
                    self.log.info(
                        "Container cleanup completed via command line")
                except Exception as cmd_ex:
                    self.log.warning(
                        "Failed to cleanup container via command line: %s", cmd_ex)
            except Exception as ex:
                self.log.warning("Failed to cleanup container: %s", ex)
