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

    def run_cmd(self, cmd):
        """Execute a command and track failures."""
        if process.system(cmd, ignore_status=True, sudo=True, shell=True):
            self.is_fail += 1
            self.log.info("%s command failed", cmd)
        return

    @staticmethod
    def run_cmd_out(cmd):
        """Execute a command and return output."""
        return process.system_output(cmd, shell=True, ignore_status=True,
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

    def setUp(self):
        """Set up test environment and initialize Podman."""
        if "ppc" not in os.uname()[4]:
            self.cancel("supported only on Power platform")
        if 'PowerNV' in open('/proc/cpuinfo', 'r').read():
            self.cancel("servicelog: is not supported on the PowerNV platform")
        
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
        self.aiu_pcie_ids = self.params.get("AIU_PCIE_IDS", default="0233:70:00.0 0234:80:00.0")
        self.aiu_world_size = self.params.get("AIU_WORLD_SIZE", default=4)
        self.max_model_len = self.params.get("MAX_MODEL_LEN", default=32768)
        self.max_batch_size = self.params.get("MAX_BATCH_SIZE", default=32)
        self.host_models_dir = self.params.get("HOST_MODELS_DIR", default='/opt/ibm/spyre/models/')
        self.vllm_model_path = self.params.get("VLLM_MODEL_PATH", default='/models/granite-3.3-8b-instruct')
        self.vllm_spyre_use_cb = self.params.get("VLLM_SPYRE_USE_CB", default='1')
        self.memory = self.params.get("MEMORY", default='100G')
        self.shm_size = self.params.get("SHM_SIZE", default='2G')
        self.container_url = self.params.get("CONTAINER_URL", default=None)
        self.container_tag = self.params.get("CONTAINER_TAG", default=None)
        self.image_id = self.params.get("IMAGE_ID", default=None)
        self.clog_file = self.params.get("CLOG_FILE", default=None)
        self.precompiled_decoders = self.params.get("PRECOMPILED_DECODERS", default='1')
        self.cache_dir = self.params.get("CACHE_DIR", default='/opt/ibm/spyre/models/cache')
        self.senlib_config_file = self.params.get("SENLIB_CONFIG_FILE", default='senlib_config_aiusmi.json')
        self.api_key = self.params.get("API_KEY", default=None)
        # Container runtime parameters
        self.device = self.params.get("DEVICE", default="/dev/vfio")
        self.privileged = self.params.get("PRIVILEGED", default="true")
        self.pids_limit = self.params.get("PIDS_LIMIT", default="0")
        self.userns = self.params.get("USERNS", default="keep-id")
        self.group_add = self.params.get("GROUP_ADD", default="keep-groups")
        self.port_mapping = self.params.get("PORT_MAPPING", default="127.0.0.1::8000")
        # Optional VLLM parameters
        self.vllm_dt_chunk_len = self.params.get("VLLM_DT_CHUNK_LEN", default=None)
        self.vllm_spyre_use_chunked_prefill = self.params.get("VLLM_SPYRE_USE_CHUNKED_PREFILL", default=None)
        # VLLM-specific options
        enable_prefix_caching_str = self.params.get("ENABLE_PREFIX_CACHING", default="true")
        self.enable_prefix_caching = enable_prefix_caching_str.lower() in ("true", "1", "yes")
        additional_vllm_args_str = self.params.get("ADDITIONAL_VLLM_ARGS", default="")
        self.additional_vllm_args = [arg.strip() for arg in additional_vllm_args_str.split(",") if arg.strip()] if additional_vllm_args_str else None
        
        # Initialize Podman utility
        try:
            self.podman = Podman()
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
        
        # Pull container image
        if self.container_url and self.container_tag:
            try:
                image = f"{self.container_url}:{self.container_tag}"
                self.log.info("Pulling container image: %s", image)
                self.podman.pull(image)
                self.log.info("Successfully pulled image: %s", image)
            except PodmanException as ex:
                self.log.warning("Failed to pull image: %s", ex)

    def tearDown(self):
        """Clean up: stop and remove container if it exists."""
        if self.container_id and self.podman:
            try:
                self.log.info("Stopping container: %s", self.container_id)
                self.podman.stop(self.container_id)
                self.log.info("Removing container: %s", self.container_id)
                self.podman.remove(self.container_id, force=True)
                self.log.info("Container cleanup completed")
            except PodmanException as ex:
                self.log.warning("Failed to cleanup container: %s", ex)

    def test_root_in_sentient(self):
        """
        The test checks VFIO Spyre devices are accessible
        with root user is part of sentient group
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
            self.log.info("6 - Add root user to sentient groups")
            self.run_cmd("usermod -aG sentient root")
        else:
            self.cancel("Please login as root user and continue")

        self.log.info("7 - Check if root is added into sentient group")
        groups = self.run_cmd_out('sudo -u root groups')
        if 'sentient' not in groups:
            self.fail("Fail to add root user to sentient group")

        self.log.info("8 - List ids in groups")
        self.run_cmd("id -nG")

        self.log.info("9 - List pci devices")
        self.run_cmd("lspci -nn")

        self.log.info("10 - Check device group")
        if self.spyre_exists():
            groups = self.run_cmd_out("ls -l /dev/vfio")
            if 'sentient' not in groups:
                self.fail("Device files group not sentient")

        self.log.info("11 - Start the container")
        container_id = self.run_container()

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
            _, logs, _ = self.podman.logs(container_id, tail=50)
            self.log.info("Container logs:\n%s", logs.decode())
        except PodmanException as ex:
            self.log.warning("Failed to get container logs: %s", ex)

    def wait_for_vllm_startup(self, container_id, timeout=300, check_interval=10):
        """
        Wait for VLLM to start by checking container logs for startup message.
        
        :param container_id: Container ID to monitor
        :param timeout: Maximum time to wait in seconds
        :param check_interval: Time between log checks in seconds
        :return: True if startup successful, False otherwise
        """
        import time
        elapsed = 0
        
        while elapsed < timeout:
            try:
                _, logs, _ = self.podman.logs(container_id, tail=100)
                log_content = logs.decode()
                
                if "Application startup complete" in log_content:
                    self.log.info("VLLM started successfully")
                    return True
                
                if "VFIO" in log_content and "fail" in log_content.lower():
                    self.log.error("VFIO device access failure detected in logs")
                    return False
                    
                self.log.info("Waiting for VLLM startup... (%d/%d seconds)", elapsed, timeout)
                time.sleep(check_interval)
                elapsed += check_interval
                
            except PodmanException as ex:
                self.log.warning("Failed to get container logs: %s", ex)
                time.sleep(check_interval)
                elapsed += check_interval
        
        self.log.error("Timeout waiting for VLLM startup")
        return False

    def test_root_not_in_sentient(self):
        """
        Test VFIO Spyre device access when root user is NOT in sentient group.
        Expected: Container should fail to access VFIO devices.
        """
        self.log.info("=== Test: Root user NOT in sentient group ===")
        
        # 1. Remove root from sentient group
        self.log.info("1 - Remove root user from sentient group")
        self.run_cmd("gpasswd -d root sentient")
        
        # 2. Verify root is not in sentient group
        self.log.info("2 - Verify root is not in sentient group")
        groups = self.run_cmd_out("groups root")
        if "sentient" in groups:
            self.fail("Failed to remove root from sentient group")
        self.log.info("Root user groups: %s", groups)
        
        # 3. Start container
        self.log.info("3 - Start container as root (not in sentient)")
        container_id = self.run_container()
        
        # 4. Wait and check for VFIO access failure
        self.log.info("4 - Monitor container logs for VFIO access errors")
        startup_success = self.wait_for_vllm_startup(container_id, timeout=120)
        
        # 5. Get final logs
        try:
            _, logs, _ = self.podman.logs(container_id, tail=200)
            log_content = logs.decode()
            self.log.info("Container logs:\n%s", log_content)
            
            # Expect VFIO device access failure
            if "VFIO" in log_content and ("fail" in log_content.lower() or "error" in log_content.lower()):
                self.log.info("PASS: VFIO device access failure detected as expected")
            elif startup_success:
                self.fail("FAIL: Container started successfully but should have failed VFIO access")
            else:
                self.log.info("Container failed to start as expected (no sentient group access)")
                
        except PodmanException as ex:
            self.log.warning("Failed to get final logs: %s", ex)

    def test_user_in_sentient(self):
        """
        Test VFIO Spyre device access when non-root user IS in sentient group.
        Expected: Container should successfully access VFIO devices and VLLM should start.
        """
        self.log.info("=== Test: Non-root user IN sentient group ===")
        
        username = self.params.get("TEST_USERNAME", default="senuser")
        password = self.params.get("TEST_PASSWORD", default=None)
        
        if not password:
            self.cancel("TEST_PASSWORD parameter is required for this test")
        
        # 1. Create new user
        self.log.info("1 - Create user: %s", username)
        self.run_cmd(f"useradd -m {username}")
        self.run_cmd(f"echo '{username}:{password}' | chpasswd")
        
        # 2. Add user to sentient group
        self.log.info("2 - Add %s to sentient group", username)
        self.run_cmd(f"usermod -aG sentient {username}")
        
        # 3. Verify user is in sentient group
        self.log.info("3 - Verify %s is in sentient group", username)
        groups = self.run_cmd_out(f"groups {username}")
        if "sentient" not in groups:
            self.fail(f"Failed to add {username} to sentient group")
        self.log.info("%s groups: %s", username, groups)
        
        # 4. Check VFIO device permissions
        self.log.info("4 - Check VFIO device permissions")
        if self.spyre_exists():
            vfio_perms = self.run_cmd_out("ls -l /dev/vfio")
            self.log.info("VFIO device permissions:\n%s", vfio_perms)
        
        # 5. Start container as the new user
        self.log.info("5 - Start container as user: %s", username)
        container_id = self.run_container(container_name=f"spyre-fvt-{username}")
        
        # 6. Wait for VLLM startup
        self.log.info("6 - Wait for VLLM startup")
        startup_success = self.wait_for_vllm_startup(container_id, timeout=300)
        
        # 7. Verify VFIO devices detected and no access errors
        try:
            _, logs, _ = self.podman.logs(container_id, tail=200)
            log_content = logs.decode()
            self.log.info("Container logs:\n%s", log_content)
            
            # Check for successful VFIO device detection
            if "VFIO" in log_content and "fail" not in log_content.lower():
                self.log.info("VFIO devices detected successfully")
            
            if startup_success:
                self.log.info("PASS: VLLM started successfully with VFIO device access")
            else:
                self.fail("FAIL: VLLM failed to start despite user being in sentient group")
                
        except PodmanException as ex:
            self.log.warning("Failed to get final logs: %s", ex)

    def test_user_not_in_sentient(self):
        """
        Test VFIO Spyre device access when non-root user is NOT in sentient group.
        Expected: Container should fail to access VFIO devices.
        """
        self.log.info("=== Test: Non-root user NOT in sentient group ===")
        
        username = self.params.get("TEST_USERNAME", default="senuser")
        password = self.params.get("TEST_PASSWORD", default=None)
        
        if not password:
            self.cancel("TEST_PASSWORD parameter is required for this test")
        
        # 1. Ensure user exists (create if needed)
        self.log.info("1 - Ensure user %s exists", username)
        user_exists = self.run_cmd_out(f"id -u {username} 2>/dev/null")
        if not user_exists:
            self.run_cmd(f"useradd -m {username}")
            self.run_cmd(f"echo '{username}:{password}' | chpasswd")
        
        # 2. Remove user from sentient group
        self.log.info("2 - Remove %s from sentient group", username)
        self.run_cmd(f"gpasswd -d {username} sentient")
        
        # 3. Verify user is NOT in sentient group
        self.log.info("3 - Verify %s is NOT in sentient group", username)
        groups = self.run_cmd_out(f"groups {username}")
        if "sentient" in groups:
            self.fail(f"Failed to remove {username} from sentient group")
        self.log.info("%s groups: %s", username, groups)
        
        # 4. Check VFIO device permissions
        self.log.info("4 - Check VFIO device permissions")
        if self.spyre_exists():
            vfio_perms = self.run_cmd_out("ls -l /dev/vfio")
            self.log.info("VFIO device permissions:\n%s", vfio_perms)
        
        # 5. Start container as the user (not in sentient)
        self.log.info("5 - Start container as user: %s (not in sentient)", username)
        try:
            container_id = self.run_container(container_name=f"spyre-fvt-{username}-nosentient")
        except Exception as ex:
            self.log.info("Container creation failed as expected: %s", ex)
            return
        
        # 6. Monitor for VFIO access failure
        self.log.info("6 - Monitor container for VFIO access failure")
        startup_success = self.wait_for_vllm_startup(container_id, timeout=120)
        
        # 7. Verify VFIO device access failure
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
                self.log.info("Container failed as expected (no sentient group access)")
                
        except PodmanException as ex:
            self.log.warning("Failed to get final logs: %s", ex)
