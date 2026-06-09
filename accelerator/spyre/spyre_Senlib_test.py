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
# Authors: Sai Janani (jananic@linux.ibm.com)

import os
import time
import subprocess
from threading import Thread, Event
from avocado import Test
from avocado.utils import cpu, process
from avocado.utils.podman import (
    Podman,
    PodmanException,
    wait_for_vllm_startup
)
from avocado.utils.software_manager.manager import SoftwareManager


class SenlibTests(Test):
    """
    Test IBM Senlib unit tests on Spyre AIU devices.
    Runs senlib test suites inside a containerized VLLM environment.
    """

    container_id = None
    podman = None
    inference_thread = None
    stop_inference_event = None

    def run_cmd(self, cmd):
        """Execute a command and fail test if it fails."""
        if process.system(cmd, sudo=True, shell=True):
            self.fail(f"Command failed: {cmd}")

    def run_cmd_out(self, cmd):
        """Execute a command and return output."""
        return process.system_output(
            cmd, shell=True, sudo=True).decode("utf-8").strip()

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
                    'ls -l /dev/vfio', shell=True,
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

    def run_inference(self):
        """Run inference in a loop until stop_inference is set."""
        prompts = [
            "write a sample python code for bubble sort",
            "explain the concept of recursion in programming",
            "what are the benefits of using design patterns",
            "describe how binary search works",
            "explain the difference between stack and queue"
        ]

        port = self.podman.get_container_port(self.container_id, port=8000)
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
                    f"http://127.0.0.1:{port}/v1/chat/completions",
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
        time.sleep(2)

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

    def run_senlib_test_suite(self, test_filter):
        """
        Run a senlib test suite inside the container using podman exec_command.

        :param test_filter: gtest filter string (e.g., "DoomFixture.*")
        :return: Tuple of (success, output)
        """
        try:
            self.log.info("Running senlib test suite: %s", test_filter)

            returncode, stdout, stderr = self.podman.exec_command(
                container_id=self.container_id,
                command=[
                    "sh", "-c", f"cd /opt/ibm/spyre/senlib/bin && ./senlib_unit_test --gtest_filter={test_filter}"],
                user="root"
            )

            output = stdout.decode() + stderr.decode()
            self.log.info("Test output:\n%s", output)

            if returncode != 0 and "PASSED" not in output and "SKIPPED" not in output:
                self.log.error(
                    "senlib_unit_test exited with code %d", returncode)
                return False, output

            if "FAILED" in output or "Failure" in output:
                self.log.error("Test suite %s has FAILED tests", test_filter)
                return False, output

            if "Passed" in output or "PASSED" in output:
                self.log.info("Test suite %s PASSED", test_filter)
                return True, output
            elif "Skipped" in output or "SKIPPED" in output:
                self.log.info("Test suite %s - all tests SKIPPED", test_filter)
                return True, output
            else:
                self.log.warning(
                    "Could not determine test result for %s", test_filter)
                return False, output

        except Exception as ex:
            self.log.error(
                "Exception while running test suite %s: %s", test_filter, ex)
            return False, str(ex)

    def setUp(self):
        """Set up test environment and initialize Podman."""
        if "powerpc" not in cpu.get_arch():
            self.cancel("supported only on Power platform")
        with open('/proc/cpuinfo', 'r') as cpuinfo:
            if 'PowerNV' in cpuinfo.read():
                self.cancel(
                    "senlib tests: not supported on the PowerNV platform")

        curr_user = self.run_cmd_out('whoami')
        if 'root' not in curr_user:
            self.cancel("Please login as root user and continue")

        smm = SoftwareManager()
        for package in ['podman', 'curl']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel(
                    f"Failed to install {package} required for this test.")

        # Get parameters from YAML
        self.rhaiis_version = self.params.get("RHAIIS_VERSION", default="")
        self.senlib_rpm_path = self.params.get("SENLIB_RPM_PATH", default="")
        self.spyre_group = self.params.get("SPYRE_GROUP", default="")
        self.aiu_pcie_ids = self.params.get("AIU_PCIE_IDS", default="")
        self.host_models_dir = self.params.get("HOST_MODELS_DIR", default="")
        self.vllm_model_path = self.params.get("VLLM_MODEL_PATH", default="")
        self.aiu_world_size = self.params.get("AIU_WORLD_SIZE", default="")
        self.max_model_len = self.params.get("MAX_MODEL_LEN", default="")
        self.max_batch_size = self.params.get("MAX_BATCH_SIZE", default="")
        self.memory = self.params.get("MEMORY", default="")
        self.container_url = self.params.get("CONTAINER_URL", default="")
        self.container_tag = self.params.get("CONTAINER_TAG", default="")
        self.api_key = self.params.get("API_KEY", default="")
        self.device = self.params.get("DEVICE", default="/dev/vfio")
        self.userns = self.params.get("USERNS", default="keep-id")
        self.group_add = self.params.get("GROUP_ADD", default="keep-groups")
        self.security_opt = self.params.get(
            "SECURITY_OPT", default="label=disable")
        self.pids_limit = self.params.get("PIDS_LIMIT", default="0")
        self.port_mapping = self.params.get(
            "PORT_MAPPING", default="127.0.0.1:8000:8000")

        # Validate required parameters
        required_params = {
            "RHAIIS_VERSION": self.rhaiis_version,
            "SENLIB_RPM_PATH": self.senlib_rpm_path,
            "AIU_PCIE_IDS": self.aiu_pcie_ids,
            "CONTAINER_URL": self.container_url,
            "CONTAINER_TAG": self.container_tag,
        }
        missing = [p for p, v in required_params.items() if not v]
        if missing:
            self.cancel(f"Missing required parameters: {', '.join(missing)}")

        # Check if RPM file exists
        if not os.path.exists(self.senlib_rpm_path):
            self.cancel(
                f"SENLIB_RPM_PATH does not exist: {self.senlib_rpm_path}")

        # Initialize Podman
        self.log.info("Initializing Podman utility")
        try:
            self.podman = Podman()
            self.log.info("Podman utility initialized successfully")
        except PodmanException as ex:
            self.cancel(f"Failed to initialize Podman: {ex}")

        # Login to registry if API key provided
        if self.api_key and self.container_url:
            try:
                registry = self.container_url.split('/')[0]
                self.log.info("Logging in to registry: %s", registry)
                self.podman.login(registry=registry, api_key=self.api_key)
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
        image = f"{self.container_url}:{self.container_tag}"
        try:
            self.log.info("Pulling container image: %s", image)
            self.podman.pull(image)
            self.log.info("Successfully pulled container image")
        except PodmanException as ex:
            self.cancel("Failed to pull container image: %s", ex)

        # Create container once for all tests
        self.log.info("Creating VLLM container for senlib tests")
        container_name = "spyre-senlib-test"

        # Clean up any existing container
        self.run_cmd(f"podman rm -f {container_name} 2>/dev/null || true")

        # Build podman run command
        podman_options = [
            "-d",
            "-it",
            "--name", container_name,
            f"--device={self.device}",
            "-v", f"{self.host_models_dir}:/models",
            "-e", f"AIU_PCIE_IDS={self.aiu_pcie_ids}",
        ]

        # Add RHAIIS 3.4 specific environment variable
        if self.rhaiis_version == "3.4":
            podman_options.extend(["-e", "VLLM_SPYRE_USE_CB=1"])

        # Continue with podman options
        podman_options.extend([
            f"--userns={self.userns}",
            f"--group-add={self.group_add}",
            f"--security-opt={self.security_opt}",
            f"--pids-limit={self.pids_limit}",
            f"--memory={self.memory}",
            "-p", self.port_mapping,
        ])

        podman_options.append(f"{self.container_url}:{self.container_tag}")
        podman_options.extend([
            "--model", self.vllm_model_path,
            "-tp", str(self.aiu_world_size),
            f"--max-model-len={self.max_model_len}",
            f"--max-num-seqs={self.max_batch_size}",
        ])

        # Add version-specific VLLM argument for 3.4
        if self.rhaiis_version == "3.4":
            podman_options.append("--enable-prefix-caching")

        self.log.info("Full podman command: podman run %s",
                      " ".join(podman_options))

        # Create container
        try:
            returncode, stdout, stderr = self.podman.run(
                podman_options=podman_options)
            if returncode != 0:
                self.log.error("stderr: %s", stderr.decode() if stderr else "")
                self.cancel("Container creation failed")

            container_id = stdout.decode().strip() if stdout else None
            if not container_id or len(container_id) < 12:
                self.cancel(
                    f"Failed to extract container ID from output: {stdout}")

            self.container_id = container_id
            self.log.info("Container created successfully: %s", container_id)
        except PodmanException as ex:
            self.cancel(f"Failed to create container: {ex}")

        # Wait for VLLM to start
        self.log.info("Waiting for VLLM to start...")
        if not wait_for_vllm_startup(
            container_id=container_id,
            success_pattern="Application startup complete.",
            failure_pattern="BACKTRACE",
            additional_failure_checks=[("VFIO", False), ("fail", False)],
            timeout=600,
            check_interval=10,
            user=None,
            log=self.log,
            show_live_logs=True,
            live_log_lines=20
        ):
            self.log.error("VLLM failed to start within timeout")
            self.cancel("VLLM startup failed")

        # Copy RPM to container
        rpm_filename = os.path.basename(self.senlib_rpm_path)
        self.log.info("Copying RPM to container: %s", rpm_filename)
        try:
            self.podman.copy_to_container(
                container_id=self.container_id,
                src=self.senlib_rpm_path,
                dst=f"/tmp/{rpm_filename}"
            )
            self.log.info("RPM copied successfully")
        except PodmanException as ex:
            self.cancel(f"Failed to copy RPM to container: {ex}")

        # Install RPM in container
        self.log.info("Installing RPM in container as root")
        try:
            returncode, stdout, stderr = self.podman.exec_command(
                container_id=self.container_id,
                command=["rpm", "-ivh", f"/tmp/{rpm_filename}"],
                user="root"  # Run as root inside container
            )

            if returncode != 0:
                self.log.error("RPM installation failed")
                self.log.error("stdout: %s", stdout.decode())
                self.log.error("stderr: %s", stderr.decode())
                self.cancel("Failed to install RPM in container")

            self.log.info("RPM installed successfully")
            self.log.info("Installation output: %s", stdout.decode())
        except PodmanException as ex:
            self.cancel(f"Failed to install RPM: {ex}")

        # Start inference
        self.log.info("Starting inference in background")
        self.start_inference()

    def test_doom_fixture(self):
        """Test DoomFixture test suite from senlib."""
        self.log.info("=== Test: DoomFixture Test Suite ===")
        success, output = self.run_senlib_test_suite("DoomFixture.*")
        if not success:
            self.log.error("DoomFixture test suite output:\n%s", output)
            self.fail("DoomFixture test suite failed - see logs for details")
        self.log.info("PASS: DoomFixture test suite completed successfully")

    def test_alloc_fixture(self):
        """Test AllocFixture test suite from senlib."""
        self.log.info("=== Test: AllocFixture Test Suite ===")
        success, output = self.run_senlib_test_suite("AllocFixture.*")
        if not success:
            self.log.error("AllocFixture test suite output:\n%s", output)
            self.fail("AllocFixture test suite failed - see logs for details")
        self.log.info("PASS: AllocFixture test suite completed successfully")

    def test_job_queue_fixture(self):
        """Test JobQueueFixture test suite from senlib."""
        self.log.info("=== Test: JobQueueFixture Test Suite ===")
        success, output = self.run_senlib_test_suite("JobQueueFixture.*")
        if not success:
            self.log.error("JobQueueFixture test suite output:\n%s", output)
            self.fail("JobQueueFixture test suite failed - see logs for details")
        self.log.info(
            "PASS: JobQueueFixture test suite completed successfully")

    def test_lrg_pf1_vf1(self):
        """Test LrgPF1VF1 test suite from senlib."""
        self.log.info("=== Test: LrgPF1VF1 Test Suite ===")
        success, output = self.run_senlib_test_suite("LrgPF1VF1.*")
        if not success:
            self.log.error("LrgPF1VF1 test suite output:\n%s", output)
            self.fail("LrgPF1VF1 test suite failed - see logs for details")
        self.log.info("PASS: LrgPF1VF1 test suite completed successfully")

    def test_med_pf1_vf0(self):
        """Test MedPF1VF0 test suite from senlib."""
        self.log.info("=== Test: MedPF1VF0 Test Suite ===")
        success, output = self.run_senlib_test_suite("MedPF1VF0.*")
        if not success:
            self.log.error("MedPF1VF0 test suite output:\n%s", output)
            self.fail("MedPF1VF0 test suite failed - see logs for details")
        self.log.info("PASS: MedPF1VF0 test suite completed successfully")

    def tearDown(self):
        """Clean up: stop inference and remove container."""
        # Stop inference thread
        self.stop_inference()

        # Clean up container
        if self.container_id and self.podman:
            try:
                self.log.info(
                    "=== Cleanup: Retrieving Final Container Logs ===")
                try:
                    log_file = self.podman.save_container_logs(
                        self.container_id, self.workdir, test_name="senlib_tests")
                    if log_file:
                        self.log.info("Container logs saved to: %s", log_file)
                except Exception as log_ex:
                    self.log.warning("Failed to save final logs: %s", log_ex)

                self.log.info("Stopping container: %s", self.container_id)
                self.podman.stop(self.container_id)

                self.log.info("Removing container: %s", self.container_id)
                self.podman.remove(self.container_id, force=True)
                self.log.info("Container cleanup completed")
            except Exception as ex:
                self.log.warning("Failed to cleanup container: %s", ex)
                try:
                    result = process.system(
                        f"podman rm -f {self.container_id}", sudo=True, shell=True, ignore_status=True)
                    if result == 0:
                        self.log.info(
                            "Container cleanup completed via command line")
                    else:
                        self.log.warning("Failed to cleanup via command line")
                except Exception as cmd_ex:
                    self.log.warning(
                        "Failed to cleanup via command line: %s", cmd_ex)
