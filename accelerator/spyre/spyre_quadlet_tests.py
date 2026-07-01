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
#          Abdul Haleem (abdhalee@linux.vnet.ibm.com)

import os
import pwd
import time
from avocado import Test
from avocado.utils import archive, process
from avocado.utils.podman import wait_for_vllm_startup
from avocado.utils.software_manager.manager import SoftwareManager


class SpyreQuadletTests(Test):
    """
    Test suite for Spyre Quadlet container deployments.
    Tests various use cases: Entity Extraction, RAG, Embedding, and Reranker.
    """

    container_name = None
    service_name = None
    test_user = None

    def run_cmd(self, cmd, sudo=True):
        """
        Execute a command and raise exception on failure.

        :param cmd: Command to execute
        :param sudo: Whether to run with sudo
        :raises: Exception if command fails
        """
        result = process.run(cmd, ignore_status=True, sudo=sudo, shell=True)
        if result.exit_status != 0:
            raise Exception(f"Command failed: {cmd}")
        return result

    @staticmethod
    def run_cmd_out(cmd, sudo=True):
        """Execute a command and return output."""
        return process.system_output(
            cmd, shell=True, ignore_status=True,
            sudo=sudo).decode("utf-8").strip()

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

    def create_quadlet_file(self, use_case, aiu_ids, model_path, tp_size,
                            max_model_len, max_batch_size, memory, shm_size=None):
        """
        Create a quadlet .container file for the specified use case.

        :param use_case: Name of the use case (entity-extract, rag, embedding, reranker)
        :param aiu_ids: AIU PCIe device IDs
        :param model_path: Path to model inside container
        :param tp_size: Tensor parallel size
        :param max_model_len: Maximum model length
        :param max_batch_size: Maximum batch size
        :param memory: Memory limit
        :param shm_size: Shared memory size (optional)
        :return: Path to created quadlet file
        """
        # Create systemd user directory
        user_home = pwd.getpwnam(self.test_user).pw_dir
        systemd_dir = os.path.join(
            user_home, ".config", "containers", "systemd")

        self.log.info("Creating systemd directory: %s", systemd_dir)
        self.run_cmd(f"su - {self.test_user} -c 'mkdir -p {systemd_dir}'")

        # Create quadlet file
        quadlet_file = os.path.join(systemd_dir, f"spyre-{use_case}.container")
        self.log.info("Creating quadlet file: %s", quadlet_file)

        # Build quadlet content
        quadlet_content = f"""[Unit]
Description=Spyre {use_case.replace('-', ' ').title()}
After=network-online.target

[Container]
ContainerName=spyre-{use_case}
PublishPort=127.0.0.1::8000
Image={self.container_image}

Environment=AIU_PCIE_IDS="{aiu_ids}"

PodmanArgs=--device={self.device}
PodmanArgs=--userns={self.userns}
PodmanArgs=--group-add={self.group_add}
PodmanArgs=--pids-limit={self.pids_limit}
PodmanArgs=--memory={memory}
PodmanArgs=--privileged={self.privileged}
"""

        # Add shm-size if specified
        if shm_size:
            quadlet_content += f"PodmanArgs=--shm-size={shm_size}\n"

        quadlet_content += f"""
Volume={self.host_models_dir}:/models

Exec=--model {model_path} -tp {tp_size} --max-model-len {max_model_len} --max-num-seqs {max_batch_size}

[Service]
Slice=spyre-{use_case}.slice
Restart=no

[Install]
WantedBy=default.target
"""

        # Write content to temp file
        temp_file = f"/tmp/spyre-{use_case}.container"
        with open(temp_file, 'w') as f:
            f.write(quadlet_content)

        # Copy to user directory and set ownership
        self.run_cmd(f"cp {temp_file} {quadlet_file}")
        self.run_cmd(f"chown {self.test_user}:{self.test_user} {quadlet_file}")
        self.run_cmd(f"rm {temp_file}")

        return quadlet_file

    def reload_systemd_daemon(self):
        """Reload systemd user daemon."""
        self.log.info("Reloading systemd user daemon")
        self.run_cmd(
            f"su - {self.test_user} -c 'XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user daemon-reload'")

    def start_service(self, service_name):
        """
        Start a systemd user service.

        :param service_name: Name of the service to start
        :return: True if service started successfully, False otherwise
        """
        self.log.info("Starting service: %s", service_name)
        result = process.run(
            f"su - {self.test_user} -c 'XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user start {service_name}'",
            shell=True, sudo=True, ignore_status=True
        )
        return result.exit_status == 0

    def stop_service(self, service_name):
        """
        Stop a systemd user service.

        :param service_name: Name of the service to stop
        """
        self.log.info("Stopping service: %s", service_name)
        self.run_cmd(
            f"su - {self.test_user} -c 'XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user stop {service_name}'")

    def check_container_running(self, container_name):
        """
        Check if a container is running.

        :param container_name: Name of the container
        :return: True if container is running, False otherwise
        """
        output = self.run_cmd_out(
            f"su - {self.test_user} -c 'XDG_RUNTIME_DIR=/run/user/$(id -u) podman ps --filter name={container_name} --format {{{{.Names}}}}'",
            sudo=True
        )
        return container_name in output

    def get_service_logs(self, service_name):
        """
        Get systemd service logs.

        :param service_name: Name of the service
        :return: Service logs as string
        """
        return self.run_cmd_out(
            f"su - {self.test_user} -c 'XDG_RUNTIME_DIR=/run/user/$(id -u) journalctl --user -xeu {service_name}'",
            sudo=True
        )

    def _wait_for_vllm_startup(self, container_name, timeout=300, check_interval=20):
        """
        Wait for VLLM to start by checking container logs for startup message.
        Uses the utility function from podman.py.

        :param container_name: Container name to monitor
        :param timeout: Maximum time to wait in seconds
        :param check_interval: Time between log checks in seconds
        :return: True if startup successful, False otherwise
        """
        return wait_for_vllm_startup(
            container_id=container_name,
            success_pattern="Application startup complete.",
            failure_pattern=None,
            additional_failure_checks=[("VFIO", False), ("fail", False)],
            timeout=timeout,
            check_interval=check_interval,
            user=self.test_user,
            log=self.log,
            show_live_logs=True,
            live_log_lines=20
        )

    def run_quadlet_test(self, use_case, aiu_ids, model_path, tp_size,
                         max_model_len, max_batch_size, memory, shm_size=None):
        """
        Run a complete quadlet test for a specific use case.

        :param use_case: Name of the use case
        :param aiu_ids: AIU PCIe device IDs
        :param model_path: Path to model inside container
        :param tp_size: Tensor parallel size
        :param max_model_len: Maximum model length
        :param max_batch_size: Maximum batch size
        :param memory: Memory limit
        :param shm_size: Shared memory size (optional)
        :return: True if test passed, False otherwise
        """
        self.log.info("=== Testing %s use case ===", use_case.upper())

        container_name = f"spyre-{use_case}"
        service_name = f"spyre-{use_case}.service"

        # Store for cleanup
        self.container_name = container_name
        self.service_name = service_name

        try:
            self.log.info("Checking ServiceReport and VFIO devices")
            try:
                self.run_cmd("servicereport -r -p spyre")
                self.run_cmd("servicereport -v -p spyre")
            except Exception as ex:
                self.fail(f"ServiceReport command failed: {ex}")

            if not self.spyre_exists():
                self.fail(
                    "VFIO Spyre devices not found or not properly configured")

            self.log.info("Creating quadlet file for user %s", self.test_user)
            quadlet_file = self.create_quadlet_file(
                use_case, aiu_ids, model_path, tp_size,
                max_model_len, max_batch_size, memory, shm_size
            )
            self.log.info("Quadlet file created: %s", quadlet_file)

            self.log.info("Reloading systemd daemon")
            self.reload_systemd_daemon()

            self.log.info("Starting service %s", service_name)
            if not self.start_service(service_name):
                self.log.error("Failed to start service")
                service_logs = self.get_service_logs(service_name)
                self.log.error("Service logs:\n%s", service_logs)
                return False

            self.log.info("Checking if container is created")
            time.sleep(5)  # Give container time to start

            if not self.check_container_running(container_name):
                self.log.error("Container %s was not created", container_name)
                service_logs = self.get_service_logs(service_name)
                self.log.error("Service logs:\n%s", service_logs)
                return False

            self.log.info("Container %s is running", container_name)

            self.log.info("Monitoring container for VLLM startup")
            startup_success = self._wait_for_vllm_startup(
                container_name,
                timeout=self.vllm_startup_timeout,
                check_interval=20
            )

            self.log.info("Collecting logs")
            service_logs = self.get_service_logs(service_name)
            self.log.info("Service logs:\n%s", service_logs)

            if startup_success:
                self.log.info(
                    "PASS: %s use case test completed successfully", use_case.upper())
                return True
            else:
                self.fail(f"FAIL: {use_case.upper()} use case test failed - VLLM did not start")

        except Exception as ex:
            self.log.error("Exception during test: %s", ex)
            try:
                service_logs = self.get_service_logs(service_name)
                self.log.error("Service logs:\n%s", service_logs)
            except Exception:
                pass
            return False

    def setUp(self):
        """Set up test environment."""
        if "ppc" not in os.uname()[4]:
            self.cancel("supported only on IBM Power platform")
        if 'PowerNV' in open('/proc/cpuinfo', 'r').read():
            self.cancel("Not supported on the PowerNV platform")

        # Configure SELinux
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
                    self.log.info("✓ SELinux set to Permissive mode")
                else:
                    self.cancel("Failed to set SELinux to Permissive mode - this is required for container operations")
        except Exception as ex:
            self.log.warning("Could not check SELinux status: %s", ex)

        # Check and install required packages
        self.log.info("Checking and installing required packages")
        smm = SoftwareManager()
        for package in ['podman', 'systemd']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel(
                    f"Failed to install {package} required for this test.")

        # Configure persistent journald logging
        self.log.info("Configuring persistent journald logging")
        try:
            # Create journal directory
            journal_dir_cmd = "install -d -m 2755 -o root -g systemd-journal /var/log/journal"
            process.run(journal_dir_cmd, shell=True, sudo=True, ignore_status=True)

            # Update journald configuration for persistent storage
            journald_config_cmd = "sed -ri 's/^#?Storage=.*/Storage=persistent/' /etc/systemd/journald.conf"
            process.run(journald_config_cmd, shell=True, sudo=True, ignore_status=True)

            # Restart journald to apply changes
            self.log.info("Restarting systemd-journald")
            restart_journald_cmd = "systemctl restart systemd-journald"
            result = process.run(restart_journald_cmd, shell=True, sudo=True, ignore_status=True)
            if result.exit_status == 0:
                self.log.info("✓ Persistent journald logging configured")
            else:
                self.log.warning("Failed to restart journald")
        except Exception as ex:
            self.log.warning("Could not configure persistent journald: %s", ex)

        # Create systemd user service directory
        self.log.info("Setting up systemd user service directory")
        try:
            systemd_user_dir_cmd = "install -d -m 0755 -o root -g root /etc/systemd/system/user@.service.d"
            process.run(systemd_user_dir_cmd, shell=True, sudo=True, ignore_status=True)
            self.log.info("✓ Systemd user service directory ready")
        except Exception as ex:
            self.log.warning("Could not create systemd user service directory: %s", ex)

        # Check if ServiceReport is available, install if not
        self.log.info("Checking ServiceReport availability")
        servicereport_check = process.run(
            "which servicereport",
            shell=True, sudo=True, ignore_status=True
        )

        if servicereport_check.exit_status != 0:
            self.log.info("ServiceReport not found, downloading and installing")
            try:
                tarball = self.fetch_asset('ServiceReport.zip', locations=[
                                           'https://github.com/linux-ras/ServiceReport'
                                           '/archive/master.zip'], expire='7d')
                archive.extract(tarball, self.workdir)

                # Install ServiceReport
                servicereport_dir = os.path.join(self.workdir, 'ServiceReport-master')
                install_cmd = f"cd {servicereport_dir} && ./install.sh"
                result = process.run(install_cmd, shell=True, sudo=True, ignore_status=True)
                if result.exit_status != 0:
                    self.cancel("Failed to install ServiceReport - required for this test")
                self.log.info("✓ ServiceReport installed successfully")
            except Exception as ex:
                self.cancel(f"Failed to download/install ServiceReport: {ex}")
        else:
            self.log.info("ServiceReport already installed")

        # Load parameters from YAML
        self.spyre_group = self.params.get("SPYRE_GROUP", default="")
        self.test_user = self.params.get("TEST_USERNAME", default="")
        self.test_password = self.params.get("TEST_PASSWORD", default="")
        self.root_password = self.params.get("ROOT_PASSWORD", default="")
        self.host_models_dir = self.params.get("HOST_MODELS_DIR", default="")
        self.vllm_startup_timeout = int(self.params.get(
            "VLLM_STARTUP_TIMEOUT", default="300"))
        self.log_check_interval = self.params.get(
            "LOG_CHECK_INTERVAL", default="")

        # Container configuration
        self.container_image = self.params.get("CONTAINER_IMAGE", default="")
        self.container_url = self.params.get("CONTAINER_URL", default="")
        self.container_tag = self.params.get("CONTAINER_TAG", default="")
        self.api_key = self.params.get("API_KEY", default="")
        self.device = self.params.get("DEVICE", default="")
        self.privileged = self.params.get("PRIVILEGED", default="")
        self.pids_limit = self.params.get("PIDS_LIMIT", default="")
        self.userns = self.params.get("USERNS", default="")
        self.group_add = self.params.get("GROUP_ADD", default="")
        self.port_mapping = self.params.get("PORT_MAPPING", default="")

        # VLLM-specific options
        self.vllm_spyre_use_cb = self.params.get(
            "VLLM_SPYRE_USE_CB", default="")
        self.vllm_dt_chunk_len = self.params.get(
            "VLLM_DT_CHUNK_LEN", default="")
        self.vllm_spyre_use_chunked_prefill = self.params.get(
            "VLLM_SPYRE_USE_CHUNKED_PREFILL", default="")
        self.enable_prefix_caching = self.params.get(
            "ENABLE_PREFIX_CACHING", default="")
        self.additional_vllm_args = self.params.get(
            "ADDITIONAL_VLLM_ARGS", default="")

        # Create test user if doesn't exist
        user_check = process.run(
            f"id -u {self.test_user} 2>/dev/null",
            shell=True, sudo=True, ignore_status=True
        )

        if user_check.exit_status != 0:
            self.log.info("Creating test user: %s", self.test_user)
            try:
                self.run_cmd(f"useradd -m {self.test_user}")
                self.run_cmd(
                    f"echo '{self.test_user}:{self.test_password}' | chpasswd")
                self.log.info("Test user created successfully")
            except Exception as ex:
                self.cancel(f"Failed to create test user {self.test_user}: {ex}")

        # Add user to spyre group
        self.log.info("Adding user %s to %s group",
                      self.test_user, self.spyre_group)
        try:
            self.run_cmd(f"usermod -aG {self.spyre_group} {self.test_user}")
            self.log.info("User added to spyre group")
        except Exception as ex:
            self.cancel(f"Failed to add user to spyre group: {ex}")

        # Enable lingering for user
        self.log.info("Enabling lingering for user %s", self.test_user)
        try:
            self.run_cmd(f"loginctl enable-linger {self.test_user}")
            self.log.info("Lingering enabled")
        except Exception as ex:
            self.cancel(f"Failed to enable lingering: {ex}")

        # Setup runtime directory
        uid_result = process.run(
            f"id -u {self.test_user}",
            shell=True, sudo=True, ignore_status=True
        )
        if uid_result.exit_status == 0:
            user_uid = uid_result.stdout_text.strip()
            runtime_dir = f"/run/user/{user_uid}"
            self.log.info("Setting up runtime directory: %s", runtime_dir)
            try:
                self.run_cmd(f"mkdir -p {runtime_dir}")
                self.run_cmd(
                    f"chown {self.test_user}:{self.test_user} {runtime_dir}")
                self.run_cmd(f"chmod 700 {runtime_dir}")
                self.log.info("✓ Runtime directory configured")
            except Exception as ex:
                self.cancel(f"Failed to setup runtime directory: {ex}")
        else:
            self.cancel(f"Failed to get UID for user {self.test_user}")

        # Ensure models directory exists
        if not os.path.exists(self.host_models_dir):
            self.log.info("Creating models directory: %s",
                          self.host_models_dir)
            try:
                os.makedirs(self.host_models_dir, exist_ok=True)
                self.log.info("✓ Models directory created")
            except Exception as ex:
                self.cancel(f"Failed to create models directory: {ex}")

    def test_entity_extraction(self):
        """Test Entity Extraction use case with quadlet."""
        # Load parameters from YAML
        aiu_ids = self.params.get("ENTITY_EXTRACT_AIU_IDS", default="")
        model_path = self.params.get("ENTITY_EXTRACT_MODEL", default="")
        tp_size = self.params.get("ENTITY_EXTRACT_WORLD_SIZE", default="")
        max_model_len = self.params.get(
            "ENTITY_EXTRACT_MAX_MODEL_LEN", default="")
        max_batch_size = self.params.get(
            "ENTITY_EXTRACT_MAX_BATCH_SIZE", default="")
        memory = self.params.get("ENTITY_EXTRACT_MEMORY", default="")

        success = self.run_quadlet_test(
            "entity-extract", aiu_ids, model_path, tp_size,
            max_model_len, max_batch_size, memory
        )
        if not success:
            self.fail("spyre-entity-extract container failed")

    def test_rag(self):
        """Test RAG use case with quadlet."""
        # Load parameters from YAML
        aiu_ids = self.params.get("RAG_AIU_IDS", default="")
        model_path = self.params.get("RAG_MODEL", default="")
        tp_size = self.params.get("RAG_WORLD_SIZE", default="")
        max_model_len = self.params.get("RAG_MAX_MODEL_LEN", default="")
        max_batch_size = self.params.get("RAG_MAX_BATCH_SIZE", default="")
        memory = self.params.get("RAG_MEMORY", default="")
        shm_size = self.params.get("RAG_SHM_SIZE", default="")

        success = self.run_quadlet_test(
            "rag", aiu_ids, model_path, tp_size,
            max_model_len, max_batch_size, memory, shm_size
        )
        if not success:
            self.fail("spyre-rag container failed")

    def test_embedding(self):
        """Test Embedding use case with quadlet."""
        # Load parameters from YAML
        aiu_ids = self.params.get("EMBEDDING_AIU_IDS", default="")
        model_path = self.params.get("EMBEDDING_MODEL", default="")
        tp_size = self.params.get("EMBEDDING_WORLD_SIZE", default="")
        max_model_len = self.params.get("EMBEDDING_MAX_MODEL_LEN", default="")
        max_batch_size = self.params.get(
            "EMBEDDING_MAX_BATCH_SIZE", default="")
        memory = self.params.get("EMBEDDING_MEMORY", default="")

        success = self.run_quadlet_test(
            "embedding", aiu_ids, model_path, tp_size,
            max_model_len, max_batch_size, memory
        )
        if not success:
            self.fail("spyre-embedding container failed")

    def test_reranker(self):
        """Test Reranker use case with quadlet."""
        # Load parameters from YAML
        aiu_ids = self.params.get("RERANKER_AIU_IDS", default="")
        model_path = self.params.get("RERANKER_MODEL", default="")
        tp_size = self.params.get("RERANKER_WORLD_SIZE", default="")
        max_model_len = self.params.get("RERANKER_MAX_MODEL_LEN", default="")
        max_batch_size = self.params.get("RERANKER_MAX_BATCH_SIZE", default="")
        memory = self.params.get("RERANKER_MEMORY", default="")

        success = self.run_quadlet_test(
            "reranker", aiu_ids, model_path, tp_size,
            max_model_len, max_batch_size, memory
        )
        if not success:
            self.fail("spyre-reranker container failed")

    def tearDown(self):
        """Clean up: stop service and remove container."""
        if self.service_name:
            try:
                self.log.info("=== Cleanup ===")

                # Get final service logs
                try:
                    service_logs = self.get_service_logs(self.service_name)
                    self.log.info("Final service logs:\n%s", service_logs)
                except Exception as ex:
                    self.log.warning(
                        "Failed to get final service logs: %s", ex)

                # Stop the service
                self.stop_service(self.service_name)

                # Remove container if it exists
                if self.container_name:
                    self.log.info("Removing container: %s",
                                  self.container_name)
                    self.run_cmd(
                        f"su - {self.test_user} -c 'XDG_RUNTIME_DIR=/run/user/$(id -u) podman rm -f {self.container_name} 2>/dev/null || true'"
                    )

                self.log.info("Cleanup completed")

            except Exception as ex:
                self.log.warning("Failed to cleanup: %s", ex)
