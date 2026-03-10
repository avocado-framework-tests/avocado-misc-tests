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
from avocado.utils import archive, process
from avocado.utils.podman import Podman, PodmanException
from avocado.utils.software_manager.manager import SoftwareManager


class serviceability(Test):

    is_fail = 0
    container_id = None
    podman = None
    container_user = None  # Track which user created the container

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

    @staticmethod
    def spyre_exists():
        """Check if VFIO Spyre devices exist."""
        if os.path.exists('/dev/vfio'):
            files = os.listdir('/dev/vfio')
            for file in files:
                if file.isdigit():
                    return True
        return False

    def run_container(self, container_name="spyre-fvt-test"):
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
                aiu_world_size=self.aiu_world_size,
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

    def _build_podman_run_command(self, container_name="spyre-fvt-test"):
        """
        Build the podman run command string for manual execution.
        This is used when we need to run podman in a different session context.

        :param container_name: Name for the container
        :return: Complete podman run command as string
        """
        # Build the command with all parameters
        cmd_parts = [
            "podman run -d",
            f"--name {container_name}",
            f"--device {self.device}",
            f"--privileged={self.privileged}",
            f"--pids-limit={self.pids_limit}",
            f"--userns={self.userns}",
            f"--group-add={self.group_add}",
            f"-p {self.port_mapping}",
            f"-v {self.host_models_dir}:/models:Z",
            f"--memory={self.memory}",
            f"--shm-size={self.shm_size}",
            f"-e VLLM_SPYRE_USE_CB={self.vllm_spyre_use_cb}",
            f"-e AIU_PCIE_IDS='{self.aiu_pcie_ids}'",
        ]

        # Add optional environment variables
        if self.vllm_dt_chunk_len:
            cmd_parts.append(f"-e VLLM_DT_CHUNK_LEN={self.vllm_dt_chunk_len}")
        if self.vllm_spyre_use_chunked_prefill:
            cmd_parts.append(f"-e VLLM_SPYRE_USE_CHUNKED_PREFILL={self.vllm_spyre_use_chunked_prefill}")

        # Add image and vllm arguments
        cmd_parts.append(f"{self.container_url}:{self.container_tag}")
        cmd_parts.append(f"--model {self.vllm_model_path}")
        cmd_parts.append(f"--tensor-parallel-size {self.aiu_world_size}")
        cmd_parts.append(f"--max-model-len {self.max_model_len}")
        cmd_parts.append(f"--max-num-seqs {self.max_batch_size}")

        if self.enable_prefix_caching:
            cmd_parts.append("--enable-prefix-caching")

        if self.additional_vllm_args:
            cmd_parts.extend(self.additional_vllm_args)

        return " ".join(cmd_parts)

    def wait_for_vllm_startup(self, container_id, timeout=300, check_interval=10, user=None):
        """
        Wait for VLLM to start by checking container logs for startup message.

        :param container_id: Container ID to monitor
        :param timeout: Maximum time to wait in seconds
        :param check_interval: Time between log checks in seconds
        :param user: Username if container was created by a specific user (for su context)
        :return: True if startup successful, False otherwise
        """
        import time
        elapsed = 0

        while elapsed < timeout:
            try:
                # Get logs based on who created the container
                if user:
                    # Container created by specific user - write logs to file first
                    import tempfile
                    import pwd
                    # Use mkstemp for secure temporary file creation
                    fd, log_file = tempfile.mkstemp(suffix=".log", prefix=f"podman_logs_{user}_")
                    os.close(fd)  # Close the file descriptor

                    # Read the log file
                    try:
                        # Change ownership of temp file to the user so they can write to it
                        user_info = pwd.getpwnam(user)
                        os.chown(log_file, user_info.pw_uid, user_info.pw_gid)

                        # Now the user can write to the file
                        write_log_cmd = f"su - {user} -c 'podman logs {container_id} > {log_file} 2>&1'"
                        process.run(write_log_cmd, shell=True, sudo=True, ignore_status=True)

                        with open(log_file, 'r') as f:
                            log_content = f.read()
                    except Exception as e:
                        self.log.warning("Failed to read log file: %s", e)
                        log_content = ""
                    finally:
                        # Always clean up the temp file
                        if os.path.exists(log_file):
                            os.remove(log_file)
                elif self.podman:
                    # Container created by root - use Podman API
                    _, logs, _ = self.podman.logs(container_id, tail=200)
                    log_content = logs.decode()
                else:
                    # Fallback to direct podman command
                    log_content = self.run_cmd_out(f"podman logs --tail 200 {container_id}")

                if "Application startup complete." in log_content:
                    self.log.info("VLLM started successfully")
                    return True

                if "VFIO" in log_content and "fail" in log_content.lower():
                    self.log.error("VFIO device access failure detected in logs")
                    return False

                self.log.info("Waiting for VLLM startup... (%d/%d seconds)", elapsed, timeout)
                time.sleep(check_interval)
                elapsed += check_interval

            except PodmanException as ex:
                self.log.warning("Failed to get container logs via API: %s", ex)
                time.sleep(check_interval)
                elapsed += check_interval
            except Exception as ex:
                self.log.warning("Failed to get container logs: %s", ex)
                time.sleep(check_interval)
                elapsed += check_interval

        self.log.error("Timeout waiting for VLLM startup")
        return False

    def setUp(self):
        """Set up test environment and initialize Podman."""
        if "ppc" not in os.uname()[4]:
            self.cancel("supported only on Power platform")
        if 'PowerNV' in open('/proc/cpuinfo', 'r').read():
            self.cancel("servicelog: is not supported on the PowerNV platform")

        # Check and disable SELinux if enforcing
        self.log.info("Checking SELinux status")
        try:
            selinux_status = self.run_cmd_out("getenforce")
            self.log.info("SELinux status: %s", selinux_status)

            if selinux_status.strip().lower() == "enforcing":
                self.log.info("SELinux is Enforcing, disabling it for container operations")
                result = process.run("setenforce 0", shell=True, sudo=True, ignore_status=True)
                if result.exit_status == 0:
                    self.log.info("SELinux set to Permissive mode")
                    # Verify the change
                    new_status = self.run_cmd_out("getenforce")
                    self.log.info("SELinux status after change: %s", new_status)
                else:
                    self.log.warning("Failed to set SELinux to Permissive mode: %s",
                                     result.stderr.decode())
            else:
                self.log.info("SELinux is not Enforcing, no action needed")
        except Exception as ex:
            self.log.warning("Could not check/modify SELinux status: %s", ex)

        # Install required packages
        smm = SoftwareManager()
        for package in ['make', 'gcc', 'podman']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel(f"Fail to install {package} required for this test.")

        # Fetch and extract ServiceReport
        tarball = self.fetch_asset('ServiceReport.zip', locations=[
                                   'https://github.com/linux-ras/ServiceReport'
                                   '/archive/master.zip'], expire='7d')
        archive.extract(tarball, self.workdir)

        # Get test parameters
        self.spyre_group = self.params.get("SPYRE_GROUP", default="")
        self.aiu_pcie_ids = self.params.get("AIU_PCIE_IDS", default="")
        self.aiu_world_size = self.params.get("AIU_WORLD_SIZE", default="")
        self.max_model_len = self.params.get("MAX_MODEL_LEN", default="")
        self.max_batch_size = self.params.get("MAX_BATCH_SIZE", default="")
        self.host_models_dir = self.params.get("HOST_MODELS_DIR", default="")
        self.vllm_model_path = self.params.get("VLLM_MODEL_PATH", default="")
        self.vllm_spyre_use_cb = self.params.get("VLLM_SPYRE_USE_CB", default="")
        self.memory = self.params.get("MEMORY", default="")
        self.shm_size = self.params.get("SHM_SIZE", default="")
        self.container_url = self.params.get("CONTAINER_URL", default="")
        self.container_tag = self.params.get("CONTAINER_TAG", default="")
        self.image_id = self.params.get("IMAGE_ID", default="")
        self.clog_file = self.params.get("CLOG_FILE", default="")
        self.precompiled_decoders = self.params.get("PRECOMPILED_DECODERS", default="")
        self.cache_dir = self.params.get("CACHE_DIR", default="")
        self.senlib_config_file = self.params.get("SENLIB_CONFIG_FILE", default="")
        self.api_key = self.params.get("API_KEY", default="")
        # Container runtime parameters
        self.device = self.params.get("DEVICE", default="")
        self.privileged = self.params.get("PRIVILEGED", default="")
        self.pids_limit = self.params.get("PIDS_LIMIT", default="")
        self.userns = self.params.get("USERNS", default="")
        self.group_add = self.params.get("GROUP_ADD", default="")
        self.port_mapping = self.params.get("PORT_MAPPING", default="")
        # Optional VLLM parameters
        self.vllm_dt_chunk_len = self.params.get("VLLM_DT_CHUNK_LEN", default="")
        self.vllm_spyre_use_chunked_prefill = self.params.get("VLLM_SPYRE_USE_CHUNKED_PREFILL", default="")
        # VLLM-specific options
        enable_prefix_caching_str = self.params.get("ENABLE_PREFIX_CACHING", default="")
        self.enable_prefix_caching = enable_prefix_caching_str.lower() in ("true", "1", "yes") if enable_prefix_caching_str else False
        additional_vllm_args_str = self.params.get("ADDITIONAL_VLLM_ARGS", default="")
        self.additional_vllm_args = [arg.strip() for arg in additional_vllm_args_str.split(",") if arg.strip()] if additional_vllm_args_str else None

        # Initialize Podman utility
        try:
            self.podman = Podman()
            print(dir(self.podman))
            self.log.info("Podman utility initialized successfully")
        except PodmanException as ex:
            self.cancel(f"Failed to initialize Podman: {ex}")

        # Login to container registry if API key provided
        if self.api_key and self.container_url:
            try:
                registry = self.container_url.split('/')[0]  # Extract registry from URL
                self.podman.login(registry=registry, api_key=self.api_key)
                self.log.info("Successfully logged in to registry: %s", registry)
            except PodmanException as ex:
                self.log.warning("Failed to login to registry: %s", ex)

        # Pull container image for root and test user
        if self.container_url and self.container_tag:
            image = f"{self.container_url}:{self.container_tag}"
            # Pull for root user
            try:
                self.log.info("Pulling container image for root user: %s", image)
                self.podman.pull(image)
                self.log.info("Successfully pulled image for root user: %s", image)
            except PodmanException as ex:
                self.log.warning("Failed to pull image for root user: %s", ex)

            # Pull for test user (if configured)
            test_username = self.params.get("TEST_USERNAME", default="")
            if test_username:
                try:
                    self.log.info("Pulling container image for user %s: %s", test_username, image)

                    # Login to registry as the user if API key provided
                    if self.api_key:
                        registry = self.container_url.split('/')[0]
                        login_cmd = f"su - {test_username} -c 'echo {self.api_key} | podman login {registry} --username=iamapikey --password-stdin'"
                        result = process.run(login_cmd, shell=True, sudo=True, ignore_status=True)
                        if result.exit_status == 0:
                            self.log.info("User %s logged in to registry: %s", test_username, registry)
                        else:
                            self.log.warning("Failed to login user %s to registry", test_username)

                    # Pull image as the user
                    pull_cmd = f"su - {test_username} -c 'podman pull {image}'"
                    result = process.run(pull_cmd, shell=True, sudo=True, ignore_status=True)
                    if result.exit_status == 0:
                        self.log.info("Successfully pulled image for user %s: %s", test_username, image)
                    else:
                        self.log.warning("Failed to pull image for user %s", test_username)
                except Exception as ex:
                    self.log.warning("Failed to pull image for user %s: %s", test_username, ex)

    def test_root_in_spyre_group(self):
        """
        The test checks VFIO Spyre devices are accessible
        with root user is part of spyre group
        """
        curr_user = self.run_cmd_out('whoami')
        self.log.info("1 - Initiate Spyre device configuration")
        self.run_cmd("servicereport -r -p spyre")

        self.log.info("2 - Validate Spyre device configuration")
        self.run_cmd("servicereport -v -p spyre")

        self.log.info("3 - Checking VFIO Spyre device")
        if not self.spyre_exists():
            self.cancel("Please check for spyre configuration")

        self.log.info("4 - List the users in groups")
        self.run_cmd("groups")

        self.log.info("5 - List ids in groups")
        self.run_cmd("id")

        if 'root' in curr_user:
            self.log.info("6 - Add root user to %s group", self.spyre_group)
            self.run_cmd(f"usermod -aG {self.spyre_group} root")
        else:
            self.cancel("Please login as root user and continue")

        self.log.info("7 - Check if root is added into %s group (checking /etc/group)", self.spyre_group)
        group_line = self.run_cmd_out(f"grep '^{self.spyre_group}:' /etc/group")
        self.log.info("%s group line: %s", self.spyre_group, group_line)
        if "root" not in group_line:
            self.fail(f"Failed to add root to {self.spyre_group} group in /etc/group")

        self.log.info("8 - Verify groups in a fresh root session")
        fresh_groups = self.run_cmd_out("su - root -c 'groups'")
        self.log.info("Root user groups in fresh session: %s", fresh_groups)

        if self.spyre_group not in fresh_groups:
            self.log.warning("Root not showing %s group in fresh session", self.spyre_group)
            fresh_id = self.run_cmd_out("su - root -c 'id'")
            self.log.info("Root user id in fresh session: %s", fresh_id)

        self.log.info("9 - List pci devices")
        self.run_cmd("lspci -nn")

        self.log.info("10 - Check device group")
        if self.spyre_exists():
            groups = self.run_cmd_out("ls -l /dev/vfio")
            if self.spyre_group not in groups:
                self.fail("Device files group not spyre_group")

        self.log.info("11 - Start the container in fresh root session")
        # Build the podman command
        container_name = "spyre-fvt-test"
        podman_cmd = self._build_podman_run_command(container_name=container_name)
        self.log.info("Podman command to execute: %s", podman_cmd)

        # Execute podman in a fresh root session
        container_output = self.run_cmd_out(f"su - root -c '{podman_cmd}'")
        self.log.info("Container creation output: %s", container_output)

        # Extract container ID from output
        container_id = container_output.strip().split('\n')[-1] if container_output else None
        if container_id:
            self.container_id = container_id
            self.container_user = "root"  # Track that root created this container
            self.log.info("Container ID: %s", container_id)
        else:
            self.log.warning("Could not extract container ID from output")
            self.fail("Failed to create container")

        # Wait for container to be ready
        self.log.info("12 - Check container status")
        try:
            container_info = self.podman.get_container_info(container_id)
            self.log.info("Container state: %s", container_info.get('State', 'unknown'))
        except PodmanException as ex:
            self.fail(f"Failed to get container info: {ex}")

        # Get container logs
        self.log.info("13 - Get container logs")
        try:
            _, logs, _ = self.podman.logs(container_id, tail=200)
            self.log.info("Container logs:\n%s", logs.decode())
        except PodmanException as ex:
            self.log.warning("Failed to get container logs: %s", ex)

        # 4. Wait and check for VLLM startup success
        self.log.info("12 - Monitor container logs for VLLM startup")
        startup_success = self.wait_for_vllm_startup(container_id, timeout=300, user="root")

        # 5. Get final logs
        try:
            # Get logs using su since container was created in fresh root session
            log_cmd = f"su - root -c 'podman logs --tail 200 {container_id}'"
            log_content = self.run_cmd_out(log_cmd)
            self.log.info("Container logs:\n%s", log_content)

            # Expect successful VFIO device access since root is in spyre group
            if "VFIO" in log_content and ("fail" in log_content.lower() or "error" in log_content.lower()):
                self.fail(f"FAIL: VFIO device access failure detected but root is in {self.spyre_group} group")
            elif startup_success:
                self.log.info("PASS: Container started successfully with VFIO device access (root in %s group)", self.spyre_group)
            else:
                self.fail(f"FAIL: Container failed to start despite root being in {self.spyre_group} group")

        except PodmanException as ex:
            self.log.warning("Failed to get final logs: %s", ex)

    def test_root_not_in_spyre_group(self):
        """
        Test VFIO Spyre device access when root user is NOT in spyre_group group.
        Expected: Container should fail to access VFIO devices.
        Note: Uses 'sg' command to create a new session with updated group membership.
        """
        self.log.info("=== Test: Root user NOT in spyre_group group ===")

        # 1. Remove root from spyre_group group
        self.log.info("1 - Remove root user from spyre_group group")
        self.run_cmd("gpasswd -d root %s" % self.spyre_group)

        # 2. Verify root is not in spyre_group group (check /etc/group file)
        self.log.info("2 - Verify root is not in spyre_group group (checking /etc/group)")
        spyre_group_group_line = self.run_cmd_out(f"grep '^{self.spyre_group}:' /etc/group")
        self.log.info("Spyre group line: %s", spyre_group_group_line)
        if "root" in spyre_group_group_line:
            self.fail("Failed to remove root from spyre_group group in /etc/group")

        # 3. Create a new login session for root to pick up updated groups
        # Using 'sg' (switch group) with '-' to start a new login shell
        self.log.info("3 - Verify groups in a fresh root session")
        # Use 'su - root' to create a fresh login session and check groups
        fresh_groups = self.run_cmd_out("su - root -c 'groups'")
        self.log.info("Root user groups in fresh session: %s", fresh_groups)

        if self.spyre_group in fresh_groups:
            self.log.warning("Root still appears in %s group in fresh session", self.spyre_group)
            # Try alternative verification
            fresh_id = self.run_cmd_out("su - root -c 'id'")
            self.log.info("Root user id in fresh session: %s", fresh_id)

        # 4. Start container using a fresh root session
        # This ensures the container runs with updated group membership
        self.log.info("4 - Start container as root in fresh session (not in %s)", self.spyre_group)

        # Build the podman command that will be executed in the fresh session
        podman_cmd = self._build_podman_run_command(container_name="spyre-fvt-test-nospyre_group")
        self.log.info("Podman command to execute: %s", podman_cmd)

        # Execute podman in a fresh root session
        container_output = self.run_cmd_out(f"su - root -c '{podman_cmd}'")
        self.log.info("Container creation output: %s", container_output)

        # Extract container ID from output
        container_id = container_output.strip().split('\n')[-1] if container_output else None
        if container_id:
            self.container_id = container_id
            self.container_user = "root"  # Track that root created this container
            self.log.info("Container ID: %s", container_id)
        else:
            self.log.warning("Could not extract container ID from output")
            return

        # 5. Wait and check for VFIO access failure
        self.log.info("5 - Monitor container logs for VFIO access errors")
        startup_success = self.wait_for_vllm_startup(container_id, timeout=120, user="root")

        # 6. Get final logs
        try:
            _, logs, _ = self.podman.logs(container_id, tail=200)
            log_content = logs.decode()
            self.log.info("Container logs:\n%s", log_content)

            # Expect VFIO device access failure
            if "VFIO" in log_content and ("fail" in log_content.lower() or "error" in log_content.lower() or "permission denied" in log_content.lower()):
                self.log.info("PASS: VFIO device access failure detected as expected")
            elif startup_success:
                self.fail("FAIL: Container started successfully but should have failed VFIO access")
            else:
                self.log.info("PASS: Container failed to start as expected (no spyre_group group access)")

        except PodmanException as ex:
            self.log.warning("Failed to get final logs: %s", ex)

    def test_user_in_spyre_group(self):
        """
        Test VFIO Spyre device access when non-root user IS in spyre group.
        Expected: Container should successfully access VFIO devices and VLLM should start.
        Note: Uses fresh login session to ensure updated group membership is active.
        """
        self.log.info("=== Test: Non-root user IN spyre_group group ===")

        username = self.params.get("TEST_USERNAME", default="")
        password = self.params.get("TEST_PASSWORD", default=None)

        if not password:
            self.cancel("TEST_PASSWORD parameter is required for this test")

        # 1. Create new user
        self.log.info("1 - Create user: %s", username)
        self.run_cmd(f"useradd -m {username}")
        self.run_cmd(f"echo '{username}:{password}' | chpasswd")

        # 2. Add user to spyre group
        self.log.info("2 - Add %s to %s group", username, self.spyre_group)
        self.run_cmd(f"usermod -aG {self.spyre_group} {username}")

        # 3. Verify user is in spyre group (check /etc/group file)
        self.log.info("3 - Verify %s is in %s group (checking /etc/group)", username, self.spyre_group)
        group_line = self.run_cmd_out(f"grep '^{self.spyre_group}:' /etc/group")
        self.log.info("%s group line: %s", self.spyre_group, group_line)
        if username not in group_line:
            self.fail(f"Failed to add {username} to {self.spyre_group} group in /etc/group")

        # 4. Verify groups in a fresh login session
        self.log.info("4 - Verify groups in fresh %s session", username)
        fresh_groups = self.run_cmd_out(f"su - {username} -c 'groups'")
        self.log.info("%s groups in fresh session: %s", username, fresh_groups)

        if self.spyre_group not in fresh_groups:
            self.log.warning("%s not showing %s group in fresh session", username, self.spyre_group)
            fresh_id = self.run_cmd_out(f"su - {username} -c 'id'")
            self.log.info("%s id in fresh session: %s", username, fresh_id)

        # 5. Check VFIO device permissions
        self.log.info("5 - Check VFIO device permissions")
        if self.spyre_exists():
            vfio_perms = self.run_cmd_out("ls -l /dev/vfio")
            self.log.info("VFIO device permissions:\n%s", vfio_perms)

        # 6. Start container as the user in a fresh login session
        self.log.info("6 - Start container as user %s in fresh session", username)

        # Build the podman command
        podman_cmd = self._build_podman_run_command(container_name=f"spyre-fvt-{username}")
        self.log.info("Podman command to execute: %s", podman_cmd)

        # Execute podman in a fresh user session
        container_output = self.run_cmd_out(f"su - {username} -c '{podman_cmd}'")
        self.log.info("Container creation output: %s", container_output)

        # Extract container ID from output
        container_id = container_output.strip().split('\n')[-1] if container_output else None
        if container_id:
            self.container_id = container_id
            self.container_user = username  # Track which user created this container
            self.log.info("Container ID: %s", container_id)
        else:
            self.log.warning("Could not extract container ID from output")
            self.fail("Failed to create container")

        # 7. Wait for VLLM startup
        self.log.info("7 - Wait for VLLM startup")
        startup_success = self.wait_for_vllm_startup(container_id, timeout=300, user=username)
        print("#######")
        print(startup_success)
        # 8. Verify VFIO devices detected and no access errors
        try:
            # Get logs using su since container was created by test user
            log_cmd = f"su - {username} -c 'podman logs {container_id}'"
            log_content = self.run_cmd_out(log_cmd)
            self.log.info("Container logs:\n%s", log_content)

            # Check for successful VFIO device detection
            if "VFIO" in log_content and ("fail" in log_content.lower() or "error" in log_content.lower()):
                self.fail(f"FAIL: VFIO device access failure detected but user is in {self.spyre_group} group")

            elif startup_success:
                self.log.info("PASS: VLLM started successfully with VFIO device access (user in %s group)", self.spyre_group)
            else:
                self.fail(f"FAIL: VLLM failed to start despite user being in {self.spyre_group} group")

        except PodmanException as ex:
            self.log.warning("Failed to get final logs: %s", ex)

    def test_user_not_in_spyre_group(self):
        """
        Test VFIO Spyre device access when non-root user is NOT in spyre group.
        Expected: Container should fail to access VFIO devices.
        Note: Uses fresh login session to ensure updated group membership is active.
        """
        self.log.info("=== Test: Non-root user NOT in spyre_group group ===")

        username = self.params.get("TEST_USERNAME", default="")
        password = self.params.get("TEST_PASSWORD", default=None)

        if not password:
            self.cancel("TEST_PASSWORD parameter is required for this test")

        # 1. Ensure user exists (create if needed)
        self.log.info("1 - Ensure user %s exists", username)
        user_exists = self.run_cmd_out(f"id -u {username} 2>/dev/null")
        if not user_exists:
            self.run_cmd(f"useradd -m {username}")
            self.run_cmd(f"echo '{username}:{password}' | chpasswd")

        # 2. Remove user from spyre group
        self.log.info("2 - Remove %s from %s group", username, self.spyre_group)
        self.run_cmd(f"gpasswd -d {username} {self.spyre_group}")

        # 3. Verify user is NOT in spyre group (check /etc/group file)
        self.log.info("3 - Verify %s is NOT in %s group (checking /etc/group)", username, self.spyre_group)
        group_line = self.run_cmd_out(f"grep '^{self.spyre_group}:' /etc/group")
        self.log.info("%s group line: %s", self.spyre_group, group_line)
        if username in group_line:
            self.fail(f"Failed to remove {username} from {self.spyre_group} group in /etc/group")

        # 4. Verify groups in a fresh login session
        self.log.info("4 - Verify groups in fresh %s session", username)
        fresh_groups = self.run_cmd_out(f"su - {username} -c 'groups'")
        self.log.info("%s groups in fresh session: %s", username, fresh_groups)

        if self.spyre_group in fresh_groups:
            self.log.warning("%s still showing %s group in fresh session", username, self.spyre_group)
            fresh_id = self.run_cmd_out(f"su - {username} -c 'id'")
            self.log.info("%s id in fresh session: %s", username, fresh_id)

        # 5. Check VFIO device permissions
        self.log.info("5 - Check VFIO device permissions")
        if self.spyre_exists():
            vfio_perms = self.run_cmd_out("ls -l /dev/vfio")
            self.log.info("VFIO device permissions:\n%s", vfio_perms)

        # 6. Start container as the user in a fresh login session (not in spyre group)
        self.log.info("6 - Start container as user %s in fresh session (not in %s)", username, self.spyre_group)

        # Build the podman command
        podman_cmd = self._build_podman_run_command(container_name=f"spyre-fvt-{username}-nospyre_group")
        self.log.info("Podman command to execute: %s", podman_cmd)

        # Execute podman in a fresh user session
        container_output = self.run_cmd_out(f"su - {username} -c '{podman_cmd}'")
        self.log.info("Container creation output: %s", container_output)

        # Extract container ID from output
        container_id = container_output.strip().split('\n')[-1] if container_output else None
        if container_id:
            self.container_id = container_id
            self.container_user = username  # Track which user created this container
            self.log.info("Container ID: %s", container_id)
        else:
            self.log.warning("Could not extract container ID from output")
            # Container creation might have failed, which is acceptable
            self.log.info("PASS: Container creation failed as expected (no %s group access)", self.spyre_group)
            return

        # 7. Monitor for VFIO access failure
        self.log.info("7 - Monitor container for VFIO access failure")
        startup_success = self.wait_for_vllm_startup(container_id, timeout=300, user=username)

        # 8. Verify VFIO device access failure
        try:
            # Get logs using su since container was created by test user
            log_cmd = f"su - {username} -c 'podman logs --tail 200 {container_id}'"
            log_content = self.run_cmd_out(log_cmd)
            self.log.info("Container logs:\n%s", log_content)

            # Expect VFIO device access failure
            if "VFIO" in log_content and ("fail" in log_content.lower() or "error" in log_content.lower() or "permission denied" in log_content.lower()):
                self.log.info("PASS: VFIO device access failure detected as expected")
            elif startup_success:
                self.fail("FAIL: Container started successfully but should have failed VFIO access")
            else:
                self.log.info("PASS: Container failed to start as expected (no %s group access)", self.spyre_group)

        except PodmanException as ex:
            self.log.warning("Failed to get final logs: %s", ex)

    def tearDown(self):
        """Clean up: stop and remove container if it exists."""
        if self.container_id:
            try:
                # Print container logs before cleanup
                self.log.info("=== Final Container Logs ===")
                try:
                    if self.container_user and self.container_user != "root":
                        # Get logs for non-root user container
                        logs_cmd = f"su - {self.container_user} -c 'podman logs {self.container_id}'"
                        logs_output = self.run_cmd_out(logs_cmd)
                        self.log.info("Container logs:\n%s", logs_output)
                    elif self.podman:
                        # Get logs via Podman API
                        _, logs, _ = self.podman.logs(self.container_id)
                        self.log.info("Container logs:\n%s", logs.decode())
                    else:
                        # Fallback to direct command
                        logs_output = self.run_cmd_out(f"podman logs {self.container_id}")
                        self.log.info("Container logs:\n%s", logs_output)
                except Exception as log_ex:
                    self.log.warning("Failed to retrieve final container logs: %s", log_ex)
                # If container was created by different user, use that user's context
                if self.container_user and self.container_user != "root":
                    self.log.info("Stopping container %s created by user %s",
                                  self.container_id, self.container_user)
                    # Stop container as the user who created it
                    self.run_cmd(f"su - {self.container_user} -c 'podman stop {self.container_id}'")
                    self.log.info("Removing container %s", self.container_id)
                    # Remove container as the user who created it
                    self.run_cmd(f"su - {self.container_user} -c 'podman rm -f {self.container_id}'")
                    self.log.info("Container cleanup completed for user %s", self.container_user)
                elif self.podman:
                    # Container created by root (current session)
                    self.log.info("Stopping container: %s", self.container_id)
                    self.podman.stop(self.container_id)
                    self.log.info("Removing container: %s", self.container_id)
                    self.podman.remove(self.container_id, force=True)
                    self.log.info("Container cleanup completed")
                else:
                    # Fallback: try to remove using podman command directly
                    self.log.info("Attempting cleanup with podman command")
                    self.run_cmd(f"podman stop {self.container_id}")
                    self.run_cmd(f"podman rm -f {self.container_id}")

            except PodmanException as ex:
                self.log.warning("Failed to cleanup container via Podman API: %s", ex)
                # Try command-line fallback
                try:
                    if self.container_user and self.container_user != "root":
                        self.run_cmd(f"su - {self.container_user} -c 'podman rm -f {self.container_id}'")
                    else:
                        self.run_cmd(f"podman rm -f {self.container_id}")
                    self.log.info("Container cleanup completed via command line")
                except Exception as cmd_ex:
                    self.log.warning("Failed to cleanup container via command line: %s", cmd_ex)
            except Exception as ex:
                self.log.warning("Failed to cleanup container: %s", ex)
