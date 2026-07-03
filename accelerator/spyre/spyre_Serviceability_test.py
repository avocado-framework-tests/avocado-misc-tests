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
# Authors: Abdul Haleem (abdhalee@linux.vnet.ibm.com)

import os
import pwd
import time
from avocado import Test
from avocado.utils import process
from avocado.utils.podman import (Podman, PodmanException,
                                  install_huggingface_cli,
                                  download_model_from_hf,
                                  validate_model_with_sha,
                                  setup_user_and_group,
                                  wait_for_vllm_startup)
from avocado.utils.software_manager.manager import SoftwareManager


class SpyreServiceabilityTest(Test):

    container_id = None
    podman = None
    container_user = None

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

    def _build_podman_options(self, container_name="spyre-fvt-test"):
        """
        Build the podman run options list for use with self.podman.run().

        :param container_name: Name for the container
        :return: List of podman run option strings
        """
        podman_options = [
            "-d",
            "--name", container_name,
            f"--device={self.device}",
            "-v", f"{self.host_models_dir}:/models",
            "-e", f"AIU_PCIE_IDS={self.aiu_ids}",
        ]
        # Add RHAIIS 3.4 specific environment variable
        if self.rhaiis_version == "3.4":
            podman_options.extend(["-e", "VLLM_SPYRE_USE_CB=1"])
        # Continue with podman options in exact order
        podman_options.extend([
            f"--userns={self.userns}",
            f"--group-add={self.group_add}",
            f"--security-opt={self.security_opt}",
            f"--pids-limit={self.pids_limit}",
            f"--memory={self.memory}",
            f"--shm-size={self.shm_size}",
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

        return podman_options

    def _setup_user_and_group(self, username, password, add_to_group):
        """
        Helper method to setup user and manage group membership.

        :param username: Username to setup (None for root)
        :param password: Password for user (not used for root)
        :param add_to_group: True to add user to spyre group, False to remove
        :return: None
        """
        if add_to_group:
            setup_user_and_group(username, password,
                                 self.spyre_group, add_to_group, self.log)
            if username and username != "root":
                self.log.info(
                    "Enable lingering for user %s (run as root)", username)
                self.run_cmd(f"loginctl enable-linger {username}")
        else:
            user_display = username if username else "root"
            self.log.info("Remove %s from %s group",
                          user_display, self.spyre_group)
            self.run_cmd(f"gpasswd -d {user_display} {self.spyre_group}")

    def _verify_group_membership(self, username, should_be_in_group):
        """
        Helper method to verify group membership.

        :param username: Username to check (None or "root" for root)
        :param should_be_in_group: True if user should be in group, False otherwise
        :return: None (raises fail if verification fails)
        """
        user_display = username if username else "root"
        self.log.info("Verify %s group membership in /etc/group", user_display)
        group_line = self.run_cmd_out(
            f"grep '^{self.spyre_group}:' /etc/group")
        self.log.info("%s group line: %s", self.spyre_group, group_line)
        user_in_group = user_display in group_line
        if should_be_in_group and not user_in_group:
            self.fail(
                f"Failed to add {user_display} to {self.spyre_group} group")
        elif not should_be_in_group and user_in_group:
            self.fail(
                f"Failed to remove {user_display} from {self.spyre_group} group")

        self.log.info("Verify groups in fresh %s session", user_display)
        if username and username != "root":
            fresh_groups = self.run_cmd_out(f"su - {username} -c 'groups'")
        else:
            fresh_groups = self.run_cmd_out("su - root -c 'groups'")

        self.log.info("%s groups in fresh session: %s",
                      user_display, fresh_groups)

        if should_be_in_group and self.spyre_group not in fresh_groups:
            self.log.warning(
                "%s not showing %s group in fresh session", user_display, self.spyre_group)
            if username and username != "root":
                fresh_id = self.run_cmd_out(f"su - {username} -c 'id'")
            else:
                fresh_id = self.run_cmd_out("su - root -c 'id'")
            self.log.info("%s id in fresh session: %s", user_display, fresh_id)
        elif not should_be_in_group and self.spyre_group in fresh_groups:
            self.log.warning(
                "%s still showing %s group in fresh session", user_display, self.spyre_group)

    def _start_container_as_user(self, username, container_name):
        """
        Helper method to start container as specific user using self.podman.run().

        :param username: Username to run container as (None or "root" for root)
        :param container_name: Name for the container
        :return: container_id or None if failed
        """
        user_display = username if username else "root"

        self.log.info(
            "Cleaning up any existing container named: %s", container_name)
        self.run_cmd(f"podman rm -f {container_name} 2>/dev/null || true",
                     user=user_display)

        podman_options = self._build_podman_options(
            container_name=container_name)
        self.log.info("Starting container as %s", user_display)
        self.log.info("Full podman command: podman run %s",
                      " ".join(podman_options))

        try:
            returncode, stdout, stderr = self.podman.run(
                podman_options=podman_options,
                user=user_display
            )
            if returncode != 0:
                self.log.error(
                    "Failed to create container as user '%s'", user_display)
                self.log.error("stderr: %s", stderr.decode() if stderr else "")
                return None
            container_id = stdout.decode().strip() if stdout else None
            if not container_id or len(container_id) < 12:
                self.log.warning(
                    "Could not extract container ID from output: %s", stdout)
                return None
            self.container_id = container_id
            self.container_user = user_display
            self.log.info("Container created successfully as '%s': %s",
                          user_display, container_id)
            return container_id
        except PodmanException as ex:
            self.log.error("Failed to create container: %s", ex)
            return None

    def _verify_vfio_access(self, container_id, username, should_succeed, run_inference=False):
        """
        Helper method to verify VFIO device access and optionally run inference.

        :param container_id: Container ID to check
        :param username: Username that created container (None or "root" for root)
        :param should_succeed: True if VFIO access should succeed, False if should fail
        :param run_inference: True to run inference tests with metrics
        :return: None (raises fail if verification fails)
        """
        user_display = username if username else "root"

        self.log.info("Monitor container logs for VLLM startup")
        timeout = 600 if should_succeed else 120
        startup_success = wait_for_vllm_startup(
            container_id=container_id,
            success_pattern="Application startup complete.",
            failure_pattern="BACKTRACE",
            additional_failure_checks=[("VFIO", False), ("fail", False)],
            timeout=timeout,
            check_interval=10,
            user=username,
            log=self.log,
            show_live_logs=True,
            live_log_lines=10
        )

        inference_success = False
        metrics_file = None
        if should_succeed and run_inference and startup_success:
            self.log.info("Run inference tests with AIU metrics collection")
            inference_success, metrics_file = self.run_inference_with_metrics(
                container_id=container_id,
                port=None,  # Auto-detect port
                num_requests=5,
                metrics_duration=120,
                user=username
            )

        try:
            _, logs, _ = self.podman.logs(
                container_id, tail=200, user=username)
            log_content = logs.decode()
            self.log.info("Container logs:\n%s", log_content)

            has_vfio_error = "VFIO" in log_content and (
                "fail" in log_content.lower() or
                "error" in log_content.lower() or
                "permission denied" in log_content.lower()
            )

            if should_succeed:
                if has_vfio_error:
                    self.fail(
                        f"FAIL: VFIO device access failure detected but {user_display} is in {self.spyre_group} group")
                elif not startup_success:
                    self.log.warning(
                        "VLLM startup message not detected within timeout, but checking container status")
                    self.fail(
                        f"FAIL: Container failed to start despite {user_display} being in {self.spyre_group} group")
                elif run_inference and inference_success:
                    self.log.info("PASS: Container started successfully with VFIO device access and inference completed (%s in %s group)",
                                  user_display, self.spyre_group)
                    if metrics_file:
                        self.log.info(
                            "AIU metrics collected at: %s", metrics_file)
                elif run_inference:
                    self.fail(
                        f"FAIL: Inference requests failed despite {user_display} being in {self.spyre_group} group")
                else:
                    self.log.info("PASS: Container started successfully with VFIO device access (%s in %s group)",
                                  user_display, self.spyre_group)
            else:
                if has_vfio_error:
                    self.log.info(
                        "PASS: VFIO device access failure detected as expected")
                elif startup_success:
                    self.fail(
                        "FAIL: Container started successfully but should have failed VFIO access")
                else:
                    self.log.info(
                        "PASS: Container failed to start as expected (no %s group access)", self.spyre_group)

        except PodmanException as ex:
            self.log.warning("Failed to get final logs: %s", ex)

    def run_inference_with_metrics(self, container_id, port=None, num_requests=5,
                                   metrics_duration=120, user=None):
        """
        Run VLLM inference requests while collecting AIU metrics.

        :param container_id: Container ID to test
        :param port: Port where VLLM is listening (if None, will auto-detect)
        :param num_requests: Number of inference requests to send (default: 5)
        :param metrics_duration: Duration to collect metrics in seconds (default: 120)
        :param user: Username if container was created by specific user
        :return: Tuple of (inference_success, metrics_file_path)
        """
        self.log.info(
            "=== Starting Inference Test with Metrics Collection ===")
        if port is None:
            port = self.podman.get_container_port(
                container_id, port=8000, user=user)
            if port is None:
                self.log.error(
                    "Could not determine container port, skipping inference tests")
                return False, None

        metrics_dir = os.path.join(self.workdir, "metrics")
        os.makedirs(metrics_dir, exist_ok=True)
        metrics_file = os.path.join(
            metrics_dir, f"{container_id}_aiu_metrics.csv")

        # When a non-root user runs podman, tee writes the output file under
        # that user's context. Pre-create the file and grant write permission
        # so the non-root user can actually write to it (workdir is root-owned).
        if user and user != "root":
            try:
                # create empty file as root
                open(metrics_file, 'w').close()
                uid = pwd.getpwnam(user).pw_uid
                gid = pwd.getpwnam(user).pw_gid
                # hand ownership to test user
                os.chown(metrics_file, uid, gid)
                self.log.info("Pre-created metrics file for user %s: %s",
                              user, metrics_file)
            except Exception as ex:
                self.log.warning("Could not pre-create metrics file: %s", ex)

        self.log.info("1 - Starting AIU metrics collection")
        metrics_process = None
        try:
            metrics_process = self.podman.collect_container_aiu_metrics(
                container_id=container_id,
                output_file=metrics_file,
                stats_command="/aiu-perf-toolkit/bin/aiu-smi --csv",
                timeout=metrics_duration,
                user=user
            )
            self.log.info("AIU metrics collection started in background")
            time.sleep(2)
        except Exception as ex:
            self.log.error("Failed to start AIU metrics collection: %s", ex)

        self.log.info("2 - Sending VLLM inference requests")
        inference_success = True
        test_prompts = [
            "What is artificial intelligence?",
            "Explain quantum computing in simple terms.",
            "What are the benefits of machine learning?",
            "Describe the future of AI technology.",
            "How does natural language processing work?"
        ]

        for i in range(min(num_requests, len(test_prompts))):
            try:
                self.log.info("Sending inference request %d/%d",
                              i+1, num_requests)
                returncode, response, error = self.podman.send_vllm_inference_request(
                    port=port,
                    model_path=self.vllm_model_path,
                    prompt=test_prompts[i],
                    max_tokens=256,
                    temperature=0.7,
                    host="127.0.0.1",
                    use_jq=False
                )
                if returncode == 0:
                    self.log.info(
                        "Inference request %d completed successfully", i+1)
                    self.log.debug("Response preview: %s", response[:200])
                else:
                    self.log.error(
                        "Inference request %d failed with code %d", i+1, returncode)
                    self.log.error("Error: %s", error)
                    inference_success = False
                time.sleep(2)
            except Exception as ex:
                self.log.error(
                    "Failed to send inference request %d: %s", i+1, ex)
                inference_success = False

        self.log.info("3 - Stopping metrics collection")
        if metrics_process is not None:
            try:
                metrics_process.terminate()
                self.log.info("AIU metrics collection stopped")
            except Exception as ex:
                self.log.warning("Error stopping metrics process: %s", ex)

        if os.path.exists(metrics_file):
            file_size = os.path.getsize(metrics_file)
            self.log.info(
                "Metrics file created: %s (size: %d bytes)", metrics_file, file_size)
            try:
                with open(metrics_file, 'r') as f:
                    lines = f.readlines()[:10]
                    self.log.info(
                        "Metrics file preview (first 10 lines):\n%s", ''.join(lines))
            except Exception as ex:
                self.log.warning("Could not read metrics file: %s", ex)
        else:
            self.log.warning("Metrics file was not created: %s", metrics_file)
            metrics_file = None

        self.log.info(
            "=== Inference Test with Metrics Collection Complete ===")
        return inference_success, metrics_file

    def setUp(self):
        """Set up test environment and initialize Podman."""
        if "ppc" not in os.uname()[4]:
            self.cancel("supported only on Power platform")
        if 'PowerNV' in open('/proc/cpuinfo', 'r').read():
            self.cancel("Test is not supported on the PowerNV platform")

        curr_user = self.run_cmd_out('whoami')
        if 'root' not in curr_user:
            self.cancel("Please login as root user and continue")

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
                    new_status = self.run_cmd_out("getenforce")
                    self.log.info(
                        "SELinux status after change: %s", new_status)
                else:
                    self.log.warning("Failed to set SELinux to Permissive mode: %s",
                                     result.stderr.decode())
            else:
                self.log.info("SELinux is not Enforcing, no action needed")
        except Exception as ex:
            self.log.warning("Could not check/modify SELinux status: %s", ex)

        smm = SoftwareManager()
        for package in ['make', 'gcc', 'podman']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel(
                    f"Fail to install {package} required for this test.")

        self.rhaiis_version = self.params.get("RHAIIS_VERSION", default="")
        self.spyre_group = self.params.get("SPYRE_GROUP", default="")
        self.aiu_ids = self.params.get("AIU_PCIE_IDS", default="")
        self.aiu_world_size = self.params.get("AIU_WORLD_SIZE", default="")
        self.max_model_len = self.params.get("MAX_MODEL_LEN", default="")
        self.max_batch_size = self.params.get("MAX_BATCH_SIZE", default="")
        self.host_models_dir = self.params.get("HOST_MODELS_DIR", default="")
        self.vllm_model_path = self.params.get("VLLM_MODEL_PATH", default="")

        if self.host_models_dir:
            if not os.path.exists(self.host_models_dir):
                self.log.info(
                    "HOST_MODELS_DIR does not exist, creating: %s", self.host_models_dir)
                try:
                    os.makedirs(self.host_models_dir, exist_ok=True)
                    self.log.info(
                        "Successfully created HOST_MODELS_DIR: %s", self.host_models_dir)
                except Exception as ex:
                    self.cancel(
                        f"Failed to create HOST_MODELS_DIR {self.host_models_dir}: {ex}")
            else:
                self.log.info("HOST_MODELS_DIR exists: %s",
                              self.host_models_dir)

        model_name = os.path.basename(self.vllm_model_path)
        hf_model_name = self.params.get(
            "HF_MODEL_NAME", default="ibm-granite/granite-3.3-8b-instruct")
        model_dir = os.path.join(self.host_models_dir, model_name)
        self.log.info("Model configuration:")
        self.log.info("  Base directory: %s", self.host_models_dir)
        self.log.info("  Model name: %s", model_name)
        self.log.info("  HuggingFace Model Name: %s", hf_model_name)
        self.log.info("  Full model path: %s", model_dir)

        self.log.info("Checking Hugging Face CLI installation...")
        if not install_huggingface_cli():
            self.log.warning(
                "Failed to install Hugging Face CLI. Model download may fail.")

        if not os.path.exists(model_dir) or not os.listdir(model_dir):
            self.log.info("Downloading model: %s", hf_model_name)
            download_success = download_model_from_hf(
                hf_model_id=hf_model_name,
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
                    self.log.info(
                        "Model validation PASSED: All checks successful")
                else:
                    self.log.warning(
                        "Model validation FAILED: Please review validation messages above")
                    self.log.warning("Consider re-downloading the model")
            else:
                self.log.warning(
                    "Failed to download model. Please download manually to: %s", model_dir)
        else:
            self.log.info("Model directory already exists: %s", model_dir)
            self.log.info("Validating existing model...")
            is_valid, messages = validate_model_with_sha(model_dir)
            for msg in messages:
                self.log.info("  %s", msg)
            if is_valid:
                self.log.info(
                    "Existing model validation PASSED: All checks successful")
            else:
                self.log.warning(
                    "Existing model validation FAILED: Please review validation messages above")
                self.log.warning(
                    "Model may be incomplete or corrupted. Consider re-downloading.")

        self.memory = self.params.get("MEMORY", default="")
        self.shm_size = self.params.get("SHM_SIZE", default="")
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
        self.username = self.params.get("USER", default=None)
        if not self.username:
            self.cancel("USER parameter is required for this test")
        self.password = self.params.get("PASSWORD", default=None)
        if not self.password:
            self.cancel("PASSWORD parameter is required for this test")
        self.log.info("Step: Initializing Podman utility")
        try:
            self.podman = Podman()
            self.log.info("Podman utility initialized successfully")
        except PodmanException as ex:
            self.cancel(f"Failed to initialize Podman: {ex}")

        if self.api_key and self.container_url:
            try:
                registry = self.container_url.split('/')[0]
                self.log.info("Logging in to registry: %s", registry)
                self.podman.login(registry=registry, api_key=self.api_key)
                self.log.info(
                    "Successfully logged in to registry: %s", registry)
            except PodmanException as ex:
                self.cancel(f"Failed to login to registry: {ex}")

        if self.container_url and self.container_tag:
            image = f"{self.container_url}:{self.container_tag}"
            try:
                self.log.info(
                    "Pulling container image for root user: %s", image)
                self.podman.pull(image)
                self.log.info(
                    "Successfully pulled image for root user: %s", image)
            except PodmanException as ex:
                self.log.warning("Failed to pull image for root user: %s", ex)

            if self.username:
                try:
                    user_exists_cmd = f"id -u {self.username} 2>/dev/null"
                    user_check = process.run(
                        user_exists_cmd, shell=True, sudo=True, ignore_status=True)
                    if user_check.exit_status != 0:
                        self.log.info(
                            "User %s does not exist, creating user", self.username)
                        create_user_cmd = f"useradd -m {self.username}"
                        result = process.run(
                            create_user_cmd, shell=True, sudo=True, ignore_status=True)
                        if result.exit_status == 0:
                            self.log.info(
                                "Successfully created user: %s", self.username)
                            set_pass_cmd = f"echo '{self.username}:{self.password}' | chpasswd"
                            process.run(set_pass_cmd, shell=True,
                                        sudo=True, ignore_status=True)
                            self.log.info(
                                "Password set for user: %s", self.username)
                        else:
                            self.log.warning("Failed to create user %s: %s",
                                             self.username, result.stderr_text)
                    else:
                        self.log.info("User %s already exists", self.username)

                    uid_cmd = f"id -u {self.username}"
                    uid_result = process.run(
                        uid_cmd, shell=True, sudo=True, ignore_status=True)
                    if uid_result.exit_status == 0:
                        user_uid = uid_result.stdout_text.strip()
                        runtime_dir = f"/run/user/{user_uid}"
                        self.log.info(
                            "Setting up runtime directory for user %s: %s",
                            self.username, runtime_dir)
                        process.run(
                            f"mkdir -p {runtime_dir}", shell=True, sudo=True, ignore_status=True)
                        process.run(f"chown {self.username}:{self.username} {runtime_dir}",
                                    shell=True, sudo=True, ignore_status=True)
                        process.run(
                            f"chmod 700 {runtime_dir}", shell=True, sudo=True, ignore_status=True)

                    if self.api_key:
                        registry = self.container_url.split('/')[0]
                        self.podman.login(
                            registry=registry, api_key=self.api_key, user=self.username)

                    pull_cmd = (
                        f"su - {self.username} -c "
                        f"'XDG_RUNTIME_DIR=/run/user/$(id -u) podman pull {image}'"
                    )
                    result = process.run(
                        pull_cmd, shell=True, sudo=True, ignore_status=True)
                    if result.exit_status == 0:
                        self.log.info(
                            "Successfully pulled image for user %s: %s", self.username, image)
                    else:
                        self.log.warning(
                            "Failed to pull image for user %s: %s",
                            self.username, result.stderr_text)
                except Exception as ex:
                    self.log.warning(
                        "Failed to pull image for user %s: %s", self.username, ex)

    def test_root_in_spyre_group(self):
        """
        Test VFIO Spyre device access when root user IS in spyre group.
        Expected: Container should successfully access VFIO devices and VLLM should start.
        """
        self.log.info("=== Test: Root user IN spyre_group group ===")
        self.log.info("1 - Initiate Spyre device configuration")
        self.run_cmd("servicereport -r -p spyre")
        self.log.info("2 - Validate Spyre device configuration")
        res = self.run_cmd_out("servicereport -v -p spyre")
        if "FAIL" in res:
            self.cancel("Servicereport configuration failed!")
        self.log.info("3 - Checking VFIO Spyre device")
        if not self.spyre_exists():
            self.cancel("Please check for spyre configuration")
        self.log.info("4 - List the users in groups")
        self.run_cmd("groups")
        self.log.info("5 - List ids in groups")
        self.run_cmd("id")
        self.log.info("6 - List pci devices")
        self.run_cmd("lspci -nn")
        self._setup_user_and_group(
            username="root", password=None, add_to_group=True)
        self._verify_group_membership(username="root", should_be_in_group=True)
        self.log.info("7 - Check device group")
        if self.spyre_exists():
            groups = self.run_cmd_out("ls -l /dev/vfio")
            if self.spyre_group not in groups:
                self.fail("Device files group not spyre_group")
        container_id = self._start_container_as_user(
            username="root", container_name="spyre-fvt-test")
        if not container_id:
            self.fail("Failed to create container")
        self.log.info("8 - Check container status")
        try:
            container_info = self.podman.get_container_info(container_id)
            self.log.info("Container state: %s",
                          container_info.get('State', 'unknown'))
        except PodmanException as ex:
            self.fail(f"Failed to get container info: {ex}")
        self.log.info("9 - Get container logs")
        try:
            _, logs, _ = self.podman.logs(container_id, tail=200)
            self.log.info("Container logs:\n%s", logs.decode())
        except PodmanException as ex:
            self.log.warning("Failed to get container logs: %s", ex)
        self._verify_vfio_access(
            container_id, username="root", should_succeed=True, run_inference=True)

        log_file = self.podman.save_container_logs(
            container_id, self.workdir, test_name="spyre-fvt-test")
        if log_file:
            self.log.info("Container logs saved to: %s", log_file)

    def test_root_not_in_spyre_group(self):
        """
        Test VFIO Spyre device access when root user is NOT in spyre_group group.
        Expected: Container should fail to access VFIO devices.
        """
        self.log.info("=== Test: Root user NOT in spyre_group group ===")
        self._setup_user_and_group(
            username="root", password=None, add_to_group=False)
        self._verify_group_membership(
            username="root", should_be_in_group=False)
        container_id = self._start_container_as_user(
            username="root", container_name="spyre-fvt-test-nospyre_group")
        if not container_id:
            self.log.info(
                "PASS: Container creation failed as expected (no %s group access)", self.spyre_group)
            return
        self._verify_vfio_access(
            container_id, username="root", should_succeed=False, run_inference=False)

    def test_user_in_spyre_group(self):
        """
        Test VFIO Spyre device access when non-root user IS in spyre group.
        Expected: Container should successfully access VFIO devices and VLLM should start.
        """
        self.log.info("=== Test: Non-root user IN spyre_group group ===")
        self._setup_user_and_group(
            username=self.username, password=self.password, add_to_group=True)
        self._verify_group_membership(
            username=self.username, should_be_in_group=True)
        self.log.info("Check VFIO device permissions")
        if self.spyre_exists():
            vfio_perms = self.run_cmd_out("ls -l /dev/vfio")
            self.log.info("VFIO device permissions:\n%s", vfio_perms)
        container_id = self._start_container_as_user(
            username=self.username, container_name=f"spyre-fvt-{self.username}")
        if not container_id:
            self.fail("Failed to create container")
        self._verify_vfio_access(
            container_id, username=self.username, should_succeed=True, run_inference=True)

        log_file = self.podman.save_container_logs(
            container_id, self.workdir, test_name=f"spyre-fvt-{self.username}",
            user=self.username)
        if log_file:
            self.log.info("Container logs saved to: %s", log_file)

    def test_user_not_in_spyre_group(self):
        """
        Test VFIO Spyre device access when non-root user is NOT in spyre group.
        Expected: Container should fail to access VFIO devices.
        """
        self.log.info("=== Test: Non-root user NOT in spyre_group group ===")
        self._setup_user_and_group(
            username=self.username, password=self.password, add_to_group=False)
        self._verify_group_membership(
            username=self.username, should_be_in_group=False)
        self.log.info("Check VFIO device permissions")
        if self.spyre_exists():
            vfio_perms = self.run_cmd_out("ls -l /dev/vfio")
            self.log.info("VFIO device permissions:\n%s", vfio_perms)
        container_id = self._start_container_as_user(
            username=self.username, container_name=f"spyre-fvt-{self.username}-nospyre_group")
        if not container_id:
            self.log.info(
                "PASS: Container creation failed as expected (no %s group access)", self.spyre_group)
            return
        self._verify_vfio_access(
            container_id, username=self.username, should_succeed=False, run_inference=False)

    def tearDown(self):
        """Clean up: stop and remove container if it exists."""
        if self.container_id and self.podman:
            try:
                self.log.info("=== Cleanup: Retrieving Final Container Logs (user: '%s') ===",
                              self.container_user)
                try:
                    self.podman.logs(self.container_id,
                                     user=self.container_user)
                except Exception as log_ex:
                    self.log.warning(
                        "Failed to retrieve final logs: %s", log_ex)

                self.log.info("Stopping container '%s': %s",
                              self.container_user, self.container_id)
                try:
                    self.podman.stop(self.container_id,
                                     user=self.container_user)
                except Exception as stop_ex:
                    self.log.warning(
                        "Failed to stop via podman utility: %s", stop_ex)
                    stop_cmd = f"su - {self.container_user} -c 'podman stop {self.container_id}'"
                    process.run(stop_cmd, shell=True)

                self.log.info("Removing container '%s': %s",
                              self.container_user, self.container_id)
                self.podman.remove(self.container_id, user=self.container_user)
                self.log.info("Container cleanup completed")
            except Exception as ex:
                self.log.warning("Failed to cleanup container: %s", ex)
                try:
                    self.run_cmd(
                        f"podman rm -f {self.container_id}",
                        user=self.container_user)
                    self.log.info(
                        "Container cleanup completed via command line")
                except Exception as cmd_ex:
                    self.log.warning(
                        "Failed to cleanup via command line: %s", cmd_ex)
