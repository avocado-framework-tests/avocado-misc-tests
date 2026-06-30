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
import signal
import subprocess
from avocado import Test
from avocado.utils import archive, process
from avocado.utils.podman import (
    Podman,
    PodmanException,
    get_container_port,
    wait_for_vllm_startup
)
from avocado.utils.software_manager.manager import SoftwareManager


class SenlibTests(Test):

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

    def run_container(self, container_name="spyre-senlib-test"):
        """
        Run the VLLM container with Spyre AIU support using Podman utility.

        :param container_name: Name for the container
        :return: Container ID
        """
        try:
            returncode, stdout, stderr = self.podman.run_vllm_container(
                image=f"{self.container_url}:{self.container_tag}",
                aiu_ids=self.aiu_pcie_ids,
                host_models_dir=self.host_models_dir,
                vllm_model_path=self.vllm_model_path,
                aiu_word_size=self.aiu_word_size,
                max_model_len=self.max_model_len,
                max_batch_size=self.max_batch_size,
                memory=self.memory,
                shm_size=self.shm_size,
                device=self.device,
                privileged=self.privileged,
                pids_limit=self.pids_limit,
                userns=self.userns,
                group_add=self.group_add,
                port_mapping=self.port_mapping,
                vllm_spyre_use_cb=self.vllm_spyre_use_cb,
                vllm_dt_chunk_len=self.vllm_dt_chunk_len,
                vllm_spyre_use_chunked_prefill=self.vllm_spyre_use_chunked_prefill,
                enable_prefix_caching=self.enable_prefix_caching,
                additional_vllm_args=self.additional_vllm_args,
                container_name=container_name
            )

            container_id = stdout.decode().strip()
            self.log.info("Container created successfully: %s", container_id)
            self.container_id = container_id
            return container_id

        except PodmanException as ex:
            self.fail(f"Failed to run container: {ex}")

    def _build_podman_run_command(self, container_name="spyre-senlib-test"):
        """
        Build the podman run command string for manual execution.

        :param container_name: Name for the container
        :return: Complete podman run command as string
        """
        cmd_parts = [
            "podman run -d -it",
            f"--device={self.device}",
            f"-v {self.host_models_dir}:/models",
            f"-e AIU_PCIE_IDS=\"{self.aiu_pcie_ids}\"",
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

        # Add VLLM arguments - use -tp instead of --tensor-parallel-size
        cmd_parts.append(f"--model \"{self.vllm_model_path}\"")
        cmd_parts.append(f"-tp \"{self.aiu_word_size}\"")
        cmd_parts.append(f"--max-model-len \"{self.max_model_len}\"")
        cmd_parts.append(f"--max-num-seqs {self.max_batch_size}")

        if self.enable_prefix_caching:
            cmd_parts.append("--enable-prefix-caching")

        if self.additional_vllm_args:
            # additional_vllm_args is a list, extend instead of append
            cmd_parts.extend(self.additional_vllm_args)

        return " ".join(cmd_parts)

    def _wait_for_vllm_startup(self, container_id, timeout=300, check_interval=10):
        """
        Wait for VLLM to start by checking container logs for startup message.
        Uses the utility function from podman.py.

        :param container_id: Container ID to monitor
        :param timeout: Maximum time to wait in seconds
        :param check_interval: Time between log checks in seconds
        :return: True if startup successful, False otherwise
        """
        return wait_for_vllm_startup(
            container_id=container_id,
            success_pattern="Application startup complete.",
            failure_pattern=None,
            additional_failure_checks=[("VFIO", False), ("fail", False)],
            timeout=timeout,
            check_interval=check_interval,
            user=None,  # Running as root
            log=self.log,
            show_live_logs=True,
            live_log_lines=20
        )

    def copy_rpm_to_container(self, container_id, rpm_path):
        """
        Copy RPM file from host to container.

        :param container_id: Container ID
        :param rpm_path: Path to RPM file on host
        :return: True if successful, False otherwise
        """
        try:
            rpm_filename = os.path.basename(rpm_path)
            self.log.info("Copying RPM %s to container %s",
                          rpm_filename, container_id)

            copy_cmd = f"podman cp {rpm_path} {container_id}:/tmp/{rpm_filename}"
            result = process.run(copy_cmd, shell=True,
                                 sudo=True, ignore_status=True)

            if result.exit_status == 0:
                self.log.info("RPM copied successfully to container")
                return True
            else:
                self.log.error(
                    "Failed to copy RPM to container: %s", result.stderr_text)
                return False

        except Exception as ex:
            self.log.error("Exception while copying RPM to container: %s", ex)
            return False

    def install_rpm_in_container(self, container_id, rpm_filename):
        """
        Install RPM inside the container.

        :param container_id: Container ID
        :param rpm_filename: Name of RPM file in /tmp
        :return: True if successful, False otherwise
        """
        try:
            self.log.info(
                "Installing RPM %s in container as root", rpm_filename)

            install_cmd = f"podman exec -u 0 {container_id} rpm -ivh /tmp/{rpm_filename}"
            result = process.run(install_cmd, shell=True,
                                 sudo=True, ignore_status=True)

            self.log.info("RPM installation output:\n%s", result.stdout_text)
            if result.stderr_text:
                self.log.info("RPM installation stderr:\n%s",
                              result.stderr_text)

            if result.exit_status == 0:
                self.log.info("RPM installed successfully in container")

                # Verify where files were installed - try different package name patterns
                for pkg_name in ["ibm-senlib-tests-dd2", "ibm-senlib-tests", "senlib"]:
                    query_cmd = f"podman exec -u 0 {container_id} rpm -ql {pkg_name}"
                    query_result = process.run(
                        query_cmd, shell=True, sudo=True, ignore_status=True)
                    if query_result.exit_status == 0 and query_result.stdout_text.strip():
                        self.log.info(
                            "RPM installed files (package: %s):\n%s", pkg_name, query_result.stdout_text)
                        break

                # Also search for the binary
                find_cmd = f"podman exec -u 0 {container_id} find /opt -name senlib_unit_test 2>/dev/null"
                find_result = process.run(
                    find_cmd, shell=True, sudo=True, ignore_status=True)
                if find_result.stdout_text.strip():
                    self.log.info("Found senlib_unit_test at:\n%s",
                                  find_result.stdout_text)

                return True
            else:
                self.log.error(
                    "Failed to install RPM in container: %s", result.stderr_text)
                return False

        except Exception as ex:
            self.log.error(
                "Exception while installing RPM in container: %s", ex)
            return False

    def start_continuous_inference(self, port=None):
        """
        Start continuous inference requests in the background.

        :param port: Port where VLLM is listening
        :return: Process object or None
        """
        try:
            if port is None:
                port = self._get_container_port(self.container_id)
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
            time.sleep(5)  # Give it time to start

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

    def _get_container_port(self, container_id):
        """
        Get the actual host port mapped to container port 8000.
        Uses the utility function from podman.py.

        :param container_id: Container ID
        :return: Host port number or None
        """
        return get_container_port(
            container_id=container_id,
            port=8000,
            user=None,  # Running as root
            log=self.log
        )

    def run_senlib_test_suite(self, test_filter):
        """
        Run a senlib test suite inside the container.

        :param test_filter: gtest filter string (e.g., "DoomFixture.*")
        :return: Tuple of (success, output)
        """
        try:
            self.log.info("Running senlib test suite: %s", test_filter)

            # Run the test from the bin directory
            test_cmd = f"podman exec -u 0 -w /opt/ibm/spyre/senlib/bin {self.container_id} ./senlib_unit_test --gtest_filter={test_filter}"

            result = process.run(test_cmd, shell=True,
                                 sudo=True, ignore_status=True)
            output = result.stdout_text + result.stderr_text

            self.log.info("Test output:\n%s", output)

            # Check for failures in output
            if "FAILED" in output or "Failure" in output:
                self.log.error("Test suite %s has FAILED tests", test_filter)
                return False, output

            # Check that tests were run (not all skipped)
            if "Passed" in output or "PASSED" in output:
                self.log.info("Test suite %s PASSED", test_filter)
                return True, output
            elif "Skipped" in output or "SKIPPED" in output:
                # All tests skipped is acceptable
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
        if "ppc" not in os.uname()[4]:
            self.cancel("supported only on Power platform")
        if 'PowerNV' in open('/proc/cpuinfo', 'r').read():
            self.cancel("senlib tests: not supported on the PowerNV platform")

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

        # Load parameters
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
        # Split by spaces to get individual arguments
        self.additional_vllm_args = additional_vllm_args_str.split(
        ) if additional_vllm_args_str else None

        # Senlib-specific parameters
        self.senlib_rpm_path = self.params.get("SENLIB_RPM_PATH", default="")
        if not self.senlib_rpm_path:
            self.cancel("SENLIB_RPM_PATH parameter is required")
        if not os.path.exists(self.senlib_rpm_path):
            self.cancel(f"Senlib RPM not found at: {self.senlib_rpm_path}")

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

        # Setup spyre group for root user
        self.log.info("Setting up spyre group access")
        self.run_cmd("servicereport -r -p spyre")
        self.run_cmd("servicereport -v -p spyre")

        # Check if spyre devices exist after servicereport
        if not self.spyre_exists():
            self.cancel("Spyre devices not configured properly")

        self.log.info("Adding root user to %s group", self.spyre_group)
        self.run_cmd(f"usermod -aG {self.spyre_group} root")

    def _setup_container_and_rpm(self):
        """
        Common setup: create container, wait for VLLM, copy and install RPM.

        :return: True if successful, False otherwise
        """
        self.log.info("=== ENTERING _setup_container_and_rpm ===")

        # Create container
        self.log.info("Creating container as root user")
        podman_cmd = self._build_podman_run_command()
        self.log.info("Podman command: %s", podman_cmd)
        container_output = self.run_cmd_out(podman_cmd)

        container_id = container_output.strip().split(
            '\n')[-1] if container_output else None
        if not container_id:
            self.log.error(
                "Failed to create container. Output: %s", container_output)
            return False

        self.container_id = container_id
        self.log.info("Container created: %s", container_id)

        # Wait for VLLM to start
        self.log.info("Waiting for VLLM to start...")
        if not self._wait_for_vllm_startup(container_id, timeout=300):
            self.log.error("VLLM failed to start")
            return False

        self.log.info("VLLM started successfully!")

        # Check if RPM file exists
        if not os.path.exists(self.senlib_rpm_path):
            self.log.error("RPM file does not exist: %s", self.senlib_rpm_path)
            return False

        self.log.info("RPM file found: %s", self.senlib_rpm_path)

        # Copy RPM to container
        rpm_filename = os.path.basename(self.senlib_rpm_path)
        if not self.copy_rpm_to_container(container_id, self.senlib_rpm_path):
            self.log.error("Failed to copy RPM to container")
            return False

        # Install RPM in container
        if not self.install_rpm_in_container(container_id, rpm_filename):
            self.log.error("Failed to install RPM in container")
            return False

        # Start continuous inference
        self.log.info("Starting continuous inference in background")
        self.start_continuous_inference()

        return True

    def test_doom_fixture(self):
        """
        Test DoomFixture test suite from senlib.
        Runs: ./senlib_unit_test --gtest_filter="DoomFixture.*"
        """
        self.log.info("=== Test: DoomFixture Test Suite ===")

        if not self._setup_container_and_rpm():
            self.fail("Failed to setup container and RPM")

        # Run the test suite
        success, output = self.run_senlib_test_suite("DoomFixture.*")

        if not success:
            self.log.error("DoomFixture test suite output:\n%s", output)
            self.fail("DoomFixture test suite failed - see logs for details")

        self.log.info("PASS: DoomFixture test suite completed successfully")

    def test_alloc_fixture(self):
        """
        Test AllocFixture test suite from senlib.
        Runs: ./senlib_unit_test --gtest_filter="AllocFixture.*"
        """
        self.log.info("=== Test: AllocFixture Test Suite ===")

        if not self._setup_container_and_rpm():
            self.fail("Failed to setup container and RPM")

        # Run the test suite
        success, output = self.run_senlib_test_suite("AllocFixture.*")

        if not success:
            self.log.error("AllocFixture test suite output:\n%s", output)
            self.fail("AllocFixture test suite failed - see logs for details")

        self.log.info("PASS: AllocFixture test suite completed successfully")

    def test_job_queue_fixture(self):
        """
        Test JobQueueFixture test suite from senlib.
        Runs: ./senlib_unit_test --gtest_filter="JobQueueFixture.*"
        """
        self.log.info("=== Test: JobQueueFixture Test Suite ===")

        if not self._setup_container_and_rpm():
            self.fail("Failed to setup container and RPM")

        # Run the test suite
        success, output = self.run_senlib_test_suite("JobQueueFixture.*")

        if not success:
            self.log.error("JobQueueFixture test suite output:\n%s", output)
            self.fail("JobQueueFixture test suite failed - see logs for details")

        self.log.info(
            "PASS: JobQueueFixture test suite completed successfully")

    def test_lrg_pf1_vf1(self):
        """
        Test LrgPF1VF1 test suite from senlib.
        Runs: ./senlib_unit_test --gtest_filter="LrgPF1VF1.*"
        """
        self.log.info("=== Test: LrgPF1VF1 Test Suite ===")

        if not self._setup_container_and_rpm():
            self.fail("Failed to setup container and RPM")

        # Run the test suite
        success, output = self.run_senlib_test_suite("LrgPF1VF1.*")

        if not success:
            self.log.error("LrgPF1VF1 test suite output:\n%s", output)
            self.fail("LrgPF1VF1 test suite failed - see logs for details")

        self.log.info("PASS: LrgPF1VF1 test suite completed successfully")

    def test_med_pf1_vf0(self):
        """
        Test MedPF1VF0 test suite from senlib.
        Runs: ./senlib_unit_test --gtest_filter="MedPF1VF0.*"
        """
        self.log.info("=== Test: MedPF1VF0 Test Suite ===")

        if not self._setup_container_and_rpm():
            self.fail("Failed to setup container and RPM")

        # Run the test suite
        success, output = self.run_senlib_test_suite("MedPF1VF0.*")

        if not success:
            self.log.error("MedPF1VF0 test suite output:\n%s", output)
            self.fail("MedPF1VF0 test suite failed - see logs for details")

        self.log.info("PASS: MedPF1VF0 test suite completed successfully")

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
