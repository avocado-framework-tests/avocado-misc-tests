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
# Authors: Abdul Haleem (abdhalee@linux.ibm.com)

import os
from avocado import Test
from avocado.utils import process
from avocado.utils.podman import (Podman, PodmanException,
                                  install_huggingface_cli,
                                  download_model_from_hf,
                                  wait_for_vllm_startup,
                                  validate_model_with_sha)
from avocado.utils.software_manager.manager import SoftwareManager


class SpyreRerankerTest(Test):
    """
    Test Reranker container deployments
    with different models on Spyre AIU devices.
    """

    container_id = None
    podman = None

    def run_cmd(self, cmd, user=None):
        """Execute a command and track failures."""
        if user and user != "root":
            escaped_cmd = cmd.replace("'", "'\"'\"'")
            cmd = f"su - {user} -c '{escaped_cmd}'"
        if process.system(cmd, sudo=True, shell=True):
            return False
        return True

    @staticmethod
    def run_cmd_out(cmd, user=None):
        """Execute a command and return output."""
        if user and user != "root":
            escaped_cmd = cmd.replace("'", "'\"'\"'")
            cmd = f"su - {user} -c '{escaped_cmd}'"
        return process.system_output(
            cmd, shell=True, sudo=True).decode("utf-8").strip()

    def collect_system_info(self, container_id):
        """Collect and log system and container information."""
        self.log.info("1. Container pip list:")
        try:
            cmd = f"podman exec {container_id} pip list"
            out = self.run_cmd_out(cmd, user=self.user)
            self.log.info(out if out else "Failed to get pip list")
        except Exception as ex:
            self.log.warning("pip list error: %s", ex)

        self.log.info("\n2. Container OS:")
        try:
            cmd = f"podman exec {container_id} cat /etc/os-release"
            out = self.run_cmd_out(cmd, user=self.user)
            self.log.info(out if out else "Failed to get OS version")
        except Exception as ex:
            self.log.warning("OS version error: %s", ex)

        for num, (desc, command) in enumerate([
            ("podman ps", "podman ps"),
            ("podman images", "podman images")
        ], start=2):
            self.log.info(f"\n{num}. {desc}:")
            try:
                output = self.run_cmd_out(command, user=self.user)
                self.log.info(output if output else f"No output from {desc}")
            except Exception as ex:
                self.log.warning(f"{desc} error: %s", ex)

    def setUp(self):
        """Set up test environment."""
        if "ppc" not in os.uname()[4]:
            self.cancel("supported only on Power platform")

        curr_user = self.run_cmd_out('whoami')
        if 'root' not in curr_user:
            self.cancel("Please login as root user and continue")

        smm = SoftwareManager()
        for package in ['podman', 'curl']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel(
                    f"Failed to install {package} required for this test.")

        self.rhaiis_version = self.params.get("RHAIIS_VERSION", default="")
        self.aiu_ids = self.params.get("AIU_PCIE_IDS", default=None)
        self.host_models_dir = self.params.get("HOST_MODELS_DIR", default="")
        self.vllm_model_path = self.params.get("VLLM_MODEL_PATH", default="")
        self.aiu_world_size = self.params.get("AIU_WORLD_SIZE", default="")
        self.prompt_lens = self.params.get("PROMPT_LENS", default="")
        self.batch_sizes = self.params.get("BATCH_SIZES", default="")
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
        self.hf_model_name = self.params.get("HF_MODEL_NAME", default="")

        if self.aiu_ids:
            self.aiu_ids = self.aiu_ids.split()[0]
        else:
            self.cancel("Missing required parameters: AIU_PCIE_IDS")

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

        self.log.info("Step 3: Initializing Podman utility")
        try:
            self.podman = Podman()
            self.log.info("Podman utility initialized successfully")
        except PodmanException as ex:
            self.cancel(f"Failed to initialize Podman: {ex}")

        if self.api_key and self.container_url:
            try:
                registry = self.container_url.split('/')[0]
                self.log.info("Logging in to registry: %s", registry)
                self.podman.login(registry=registry,
                                  api_key=self.api_key, user=self.user)
                self.log.info("Successfully logged in to registry")
            except PodmanException as ex:
                self.cancel(f"Failed to login to registry: {ex}")

        # Step 4: Run servicereport commands
        self.log.info("Step 4: Running servicereport -r -p spyre")
        self.run_cmd("servicereport -r -p spyre")
        self.log.info("Running servicereport -v -p spyre")
        res = self.run_cmd_out("servicereport -v -p spyre")
        if "FAIL" in res:
            self.cancel("Servicereport configuration failed !")

        # Step 5: Download container image as specified user
        if self.container_url and self.container_tag:
            image = f"{self.container_url}:{self.container_tag}"
            try:
                self.log.info(
                    "Step 5: Pulling container image as user '%s': %s", self.user, image)
                if self.user:
                    pull_cmd = f"su - {self.user} -c 'podman pull {image}'"
                else:
                    pull_cmd = f"podman pull {image}"
                result = process.run(pull_cmd, shell=True)
                if result.exit_status == 0:
                    self.log.info(
                        "Successfully pulled container image as user '%s'", self.user)
                else:
                    self.cancel(
                        f"Failed to pull container image: {result.stderr_text}")
            except Exception as ex:
                self.log.warning("Failed to pull container image: %s", ex)

    def test_reranker_container(self):
        """
        Test reranker model container deployment on IBM Spyre AIU hardware.

        This test validates:
            1. Container creation with Spyre AIU device access
            2. Wait for vLLM startup and initialization
            3. Validates model availability
            4. API endpoint availability
            5. verifies container health and API endpoint availability
        Raises:
            TestFail: If model not found, container creation fails, VLLM startup times out,
                     or container enters non-running state.
        """
        self.log.info("=== Starting Reranker Container Test ===")
        model_name = os.path.basename(self.vllm_model_path)
        model_dir = os.path.join(self.host_models_dir, model_name)
        if not os.path.exists(model_dir):
            self.fail(
                f"Model directory not found: {model_dir}. Please ensure model is downloaded.")

        model_files = os.listdir(model_dir)
        if not model_files:
            self.fail(f"Model directory is empty: {model_dir}")

        self.log.info("  Sample files: %s", ', '.join(model_files[:5]))

        container_name = f"spyre-reranker-test-{self.rhaiis_version.replace('.', '-')}"
        self.log.info("Cleaning up any existing container: %s", container_name)
        self.run_cmd(f"podman rm -f {container_name} 2>/dev/null || true")

        podman_options = [
            "-d",
            "--name", container_name,
            f"--device={self.device}",
            "-v", f"{self.host_models_dir}:/models",
            "-e", f"AIU_PCIE_IDS={self.aiu_ids}",
        ]
        # Add RHAIIS 3.4 specific environment variable
        if self.rhaiis_version == "3.4":
            podman_options.extend(
                ["-e", f"VLLM_SPYRE_WARMUP_BATCH_SIZES={self.batch_sizes}"])
            podman_options.extend(
                ["-e", f"VLLM_SPYRE_WARMUP_PROMPT_LENS={self.prompt_lens}"])
            podman_options.extend(["-e", "VLLM_SPYRE_USE_CHUNKED_PREFILL=0"])
        else:
            podman_options.extend(
                ["-e", f"SENDNN_INFERENCE_WARMUP_BATCH_SIZES={self.batch_sizes}"])
            podman_options.extend(
                ["-e", f"SENDNN_INFERENCE_WARMUP_PROMPT_LENS={self.prompt_lens}"])

        # Continue with podman options in exact order
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
        ])
        self.log.info("=== Reranker Container Test Configuration ===")
        self.log.info("RHAIIS Version: %s", self.rhaiis_version)
        self.log.info("Model Path: %s", self.vllm_model_path)
        self.log.info("HuggingFace Model: %s", self.hf_model_name)
        self.log.info("AIU IDs: %s", self.aiu_ids)
        self.log.info("AIU World Size: %s", self.aiu_world_size)
        self.log.info("Starting VLLM container as user '%s'...", self.user)
        self.log.info("Image: %s:%s", self.container_url, self.container_tag)
        self.log.info("Container name: %s", container_name)
        self.log.info("Full podman command: podman run %s",
                      " ".join(podman_options))
        # Create container using simplified Podman utility
        try:
            returncode, stdout, stderr = self.podman.run(
                podman_options=podman_options,
                user=self.user
            )
            if returncode != 0:
                self.log.error(
                    "Failed to create container as user '%s'", self.user)
                self.log.error("stderr: %s", stderr.decode() if stderr else "")
                self.fail("Container creation failed")
            container_id = stdout.decode().strip() if stdout else None
            if not container_id or len(container_id) < 12:
                self.fail(
                    f"Failed to extract container ID from output: {stdout}")
            self.container_id = container_id
            self.log.info(
                "Container created successfully as user '%s': %s", self.user, container_id)
        except PodmanException as ex:
            self.fail(f"Failed to create container: {ex}")

        self.log.info(
            "Waiting for VLLM to start (checking as user '%s')...", self.user)
        if not wait_for_vllm_startup(
            container_id=container_id,
            success_pattern="Application startup complete.",
            failure_pattern="BACKTRACE",
            additional_failure_checks=[("VFIO", False), ("fail", False)],
            timeout=600,
            check_interval=10,
            user=self.user,
            log=self.log,
            show_live_logs=True,
            live_log_lines=10
        ):
            self.log.error("VLLM failed to start within timeout")
            log_file = self.podman.save_container_logs(
                 container_id, self.workdir, test_name=container_name,
                 user=self.user)
            if log_file:
                self.log.info("Container logs saved to: %s", log_file)
            self.fail("VLLM startup failed")

        # Collect system and container information
        self.collect_system_info(container_id)

        # Check container status (as specified user)
        try:
            container_info = self.podman.get_container_info(
                container_id, user=self.user)
            status = container_info.get('State', 'unknown')
            self.log.info("Container status: %s", status)
            if status != 'running':
                self.log.error("Container is not in running state")
                self.fail(f"Container status: {status}")
        except PodmanException as ex:
            self.log.warning("Failed to get container info: %s", ex)

        # Get and display container port (as specified user)
        host_port = self.podman.get_container_port(
            container_id, port=8000, user=self.user)
        if host_port:
            self.log.info("VLLM API available on port: %d", host_port)
        else:
            self.log.warning("Could not determine container port")

        # Save final logs (as specified user)
        log_file = self.podman.save_container_logs(
            container_id, self.workdir, test_name=container_name,
            user=self.user)
        if log_file:
            self.log.info("Container logs saved to: %s", log_file)

        self.log.info("=== Reranker Container Test Completed Successfully ===")

    def tearDown(self):
        """Clean up: stop and remove container if it exists."""
        if self.container_id and self.podman:
            try:
                self.log.info(
                    "=== Cleanup: Retrieving Final Container Logs (as user '%s') ===", self.user)
                try:
                    self.podman.logs(self.container_id, user=self.user)
                except Exception as log_ex:
                    self.log.warning(
                        "Failed to retrieve final logs: %s", log_ex)

                self.log.info("Stopping container as user '%s': %s",
                              self.user, self.container_id)
                try:
                    self.podman.stop(self.container_id, user=self.user)
                except Exception as stop_ex:
                    self.log.warning(
                        "Failed to stop via podman utility: %s", stop_ex)
                    stop_cmd = f"su - {self.user} -c 'podman stop {self.container_id}'"
                    process.run(stop_cmd, shell=True)

                self.log.info("Removing container as user '%s': %s",
                              self.user, self.container_id)
                self.podman.remove(self.container_id, user=self.user)
                self.log.info("Container cleanup completed")
            except Exception as ex:
                self.log.warning("Failed to cleanup container: %s", ex)
                try:
                    self.run_cmd(
                        f"su - {self.user} -c 'podman rm -f {self.container_id}'")
                    self.log.info(
                        "Container cleanup completed via command line")
                except Exception as cmd_ex:
                    self.log.warning(
                        "Failed to cleanup via command line: %s", cmd_ex)
