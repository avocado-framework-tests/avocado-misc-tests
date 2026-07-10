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
#          Abdul Haleem (abdhalee@linux.ibm.com)

import os
import pwd
import time
from avocado import Test
from avocado.utils import cpu, process
from avocado.utils.podman import wait_for_vllm_startup


class SpyreQuadletTests(Test):
    """
    Test suite for Spyre Quadlet container deployments.
    Tests various use cases: Entity Extraction, RAG, Embedding, and Reranker.
    """

    container_name = None
    service_name = None
    test_user = None

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
        process.run(
            f"su - {self.test_user} -c 'mkdir -p {systemd_dir}'",
            sudo=True, shell=True)

        # Create quadlet file
        quadlet_file = os.path.join(systemd_dir, f"spyre-{use_case}.container")
        self.log.info("Creating quadlet file: %s", quadlet_file)

        # Build quadlet content
        quadlet_content = f"""[Unit]
Description=Spyre {use_case.replace('-', ' ').title()}
After=network-online.target

[Container]
ContainerName=spyre-{use_case}
PublishPort={self.port_mapping}
Image={self.container_image}

Environment=AIU_PCIE_IDS="{aiu_ids}"
"""

        # Add RHAIIS 3.4 specific environment variable
        if hasattr(self, 'rhaiis_version') and self.rhaiis_version == "3.4":
            quadlet_content += 'Environment=VLLM_SPYRE_USE_CB=1\n'

        quadlet_content += f"""
PodmanArgs=--device={self.device}
PodmanArgs=--userns={self.userns}
PodmanArgs=--group-add={self.group_add}
PodmanArgs=--pids-limit={self.pids_limit}
PodmanArgs=--memory={memory}
"""

        # Add shm-size if specified
        if shm_size:
            quadlet_content += f"PodmanArgs=--shm-size={shm_size}\n"

        quadlet_content += f"""
Volume={self.host_models_dir}:/models

Exec=--model {model_path} -tp {tp_size} --max-model-len {max_model_len} --max-num-seqs {max_batch_size}"""

        # Add version-specific VLLM argument for 3.4
        if hasattr(self, 'rhaiis_version') and self.rhaiis_version == "3.4":
            quadlet_content += " --enable-prefix-caching"

        quadlet_content += f"""

[Service]
Slice=spyre-{use_case}.slice
Restart=no

[Install]
WantedBy=default.target
"""

        # Write content to temp file with proper cleanup
        temp_file = f"/tmp/spyre-{use_case}.container"
        try:
            with open(temp_file, 'w') as f:
                f.write(quadlet_content)

            # Copy to user directory and set ownership
            process.run(f"cp {temp_file} {quadlet_file}",
                        sudo=True, shell=True)
            process.run(
                f"chown {self.test_user}:{self.test_user} {quadlet_file}",
                sudo=True, shell=True)
        finally:
            # Ensure temp file is always cleaned up
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except OSError as e:
                    self.log.warning(f"Failed to remove temp file: {e}")

        return quadlet_file

    def reload_systemd_daemon(self):
        """Reload systemd user daemon."""
        self.log.info("Reloading systemd user daemon")
        process.run(
            f"su - {self.test_user} -c 'XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user daemon-reload'",
            sudo=True, shell=True)

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
        process.run(
            f"su - {self.test_user} -c 'XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user stop {service_name}'",
            sudo=True, shell=True)

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

    def _load_use_case_params(self):
        """
        Load parameters for a specific use case from YAML.

        :return: Dictionary of parameters
        """
        params = {
            'aiu_ids': self.params.get("AIU_PCIE_IDS", default=""),
            'model_path': self.params.get("VLLM_MODEL_PATH", default=""),
            'tp_size': self.params.get("AIU_WORLD_SIZE", default=""),
            'max_model_len': self.params.get("MAX_MODEL_LEN", default=""),
            'max_batch_size': self.params.get("MAX_BATCH_SIZE", default=""),
            'memory': self.params.get("MEMORY", default=""),
            'shm_size': self.params.get("SHM_SIZE", default=""),
        }

        return params

    def run_quadlet_test(self, use_case, **params):
        """
        Run a complete quadlet test for a specific use case.

        :param use_case: Name of the use case
        :param params: Dictionary of parameters (aiu_ids, model_path, etc.)
        """
        self.log.info("=== Testing %s use case ===", use_case.upper())

        container_name = f"spyre-{use_case}"
        service_name = f"spyre-{use_case}.service"

        # Store for cleanup
        self.container_name = container_name
        self.service_name = service_name

        if not self.spyre_exists():
            self.fail(
                "VFIO Spyre devices not found or not properly configured")

        self.log.info("Creating quadlet file for user %s", self.test_user)
        quadlet_file = self.create_quadlet_file(
            use_case,
            params['aiu_ids'],
            params['model_path'],
            params['tp_size'],
            params['max_model_len'],
            params['max_batch_size'],
            params['memory'],
            params.get('shm_size')
        )
        self.log.info("Quadlet file created: %s", quadlet_file)

        self.log.info("Reloading systemd daemon")
        self.reload_systemd_daemon()

        self.log.info("Starting service %s", service_name)
        if not self.start_service(service_name):
            service_logs = self.get_service_logs(service_name)
            self.fail(
                f"Failed to start service {service_name}\nService logs:\n{service_logs}")

        self.log.info("Checking if container is created")
        time.sleep(5)  # Give container time to start

        if not self.check_container_running(container_name):
            service_logs = self.get_service_logs(service_name)
            self.fail(
                f"Container {container_name} was not created\nService logs:\n{service_logs}")

        self.log.info("Container %s is running", container_name)

        self.log.info("Monitoring container for VLLM startup")
        startup_success = wait_for_vllm_startup(
            container_id=container_name,
            success_pattern="Application startup complete.",
            failure_pattern=None,
            additional_failure_checks=[("VFIO", False), ("fail", False)],
            timeout=300,
            check_interval=20,
            user=self.test_user,
            log=self.log,
            show_live_logs=True,
            live_log_lines=20
        )

        self.log.info("Collecting logs")
        service_logs = self.get_service_logs(service_name)
        self.log.info("Service logs:\n%s", service_logs)

        if not startup_success:
            self.fail(
                f"FAIL: {use_case.upper()} use case test failed - VLLM did not start")

        self.log.info(
            "PASS: %s use case test completed successfully", use_case.upper())

    def setUp(self):
        """Set up test environment."""
        if 'powerpc' not in cpu.get_arch():
            self.cancel("Supported only on IBM Power platform")
        with open('/proc/cpuinfo', 'r') as cpuinfo:
            if 'PowerNV' in cpuinfo.read():
                self.cancel("Not supported on the PowerNV platform")

        # Load parameters from YAML
        self.rhaiis_version = self.params.get("RHAIIS_VERSION", default="")
        self.spyre_group = self.params.get("SPYRE_GROUP", default="")
        self.test_user = self.params.get("USER", default="")
        self.host_models_dir = self.params.get(
            "HOST_MODELS_DIR", default="/opt/ibm/spyre/models/src")

        # Container configuration
        container_url = self.params.get("CONTAINER_URL", default="")
        container_tag = self.params.get("CONTAINER_TAG", default="")
        if not container_url or not container_tag:
            self.cancel(
                "CONTAINER_URL and CONTAINER_TAG must be set in YAML"
            )
        self.container_image = f"{container_url}:{container_tag}"
        self.api_key = self.params.get("API_KEY", default="")
        self.device = self.params.get("DEVICE", default="/dev/vfio")
        self.pids_limit = self.params.get("PIDS_LIMIT", default="0")
        self.userns = self.params.get("USERNS", default="keep-id")
        self.group_add = self.params.get("GROUP_ADD", default="keep-groups")
        self.port_mapping = self.params.get(
            "PORT_MAPPING", default="127.0.0.1:8000:8000")

        # Run servicereport commands (installation handled by spyre_Host_config.py)
        self.log.info("Running servicereport -r -p spyre")
        process.run("servicereport -r -p spyre", sudo=True, shell=True)
        self.log.info("Running servicereport -v -p spyre")
        res = self.run_cmd_out("servicereport -v -p spyre")
        if "FAIL" in res:
            self.cancel("Servicereport configuration failed")

        # Verify test user exists
        user_check = process.run(
            f"id -u {self.test_user} 2>/dev/null",
            shell=True, sudo=True, ignore_status=True
        )
        if user_check.exit_status != 0:
            self.cancel(f"Test user {self.test_user} does not exist")

        # Verify user is in spyre group
        groups_output = self.run_cmd_out(f"groups {self.test_user}")
        if self.spyre_group not in groups_output:
            self.cancel(
                f"User {self.test_user} is not in {self.spyre_group} group")

        # Authenticate with container registry if API_KEY is provided
        if self.api_key:
            self.log.info("Authenticating with container registry")
            registry = self.container_image.split(
                '/')[0] if '/' in self.container_image else 'icr.io'
            login_result = process.run(
                f"su - {self.test_user} -c 'XDG_RUNTIME_DIR=/run/user/$(id -u) "
                f"echo {self.api_key} | podman login {registry} --username iamapikey --password-stdin'",
                shell=True, sudo=True, ignore_status=True
            )
            if login_result.exit_status != 0:
                self.log.warning(
                    f"Failed to login to registry {registry}. "
                    "Container pull may fail if authentication is required."
                )
        else:
            self.log.info(
                "No API_KEY provided. Assuming image is already available locally "
                "or registry doesn't require authentication."
            )

        # Verify models directory exists
        if not os.path.exists(self.host_models_dir):
            self.cancel(
                f"Models directory {self.host_models_dir} does not exist")

    def test_quadlet(self):
        """Generic test method that loads use case from YAML."""
        use_case = self.params.get("USE_CASE", default="")
        if not use_case:
            self.cancel("USE_CASE parameter not specified in YAML")

        valid_use_cases = {"entity-extract", "rag", "embedding", "reranker"}
        if use_case not in valid_use_cases:
            self.cancel(f"Unknown use case: {use_case}")

        params = self._load_use_case_params()
        self.run_quadlet_test(use_case, **params)

    def tearDown(self):
        """Clean up: stop service, remove container, and clean up quadlet file."""
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
                self.log.info("Stopping service: %s", self.service_name)
                self.stop_service(self.service_name)

                # Force remove container if it exists
                if self.container_name:
                    self.log.info("Force removing container: %s",
                                  self.container_name)
                    process.run(
                        f"su - {self.test_user} -c 'XDG_RUNTIME_DIR=/run/user/$(id -u) podman rm -f {self.container_name} 2>/dev/null || true'",
                        shell=True, sudo=True, ignore_status=True
                    )

                    # Verify container is removed
                    check_result = process.run(
                        f"su - {self.test_user} -c 'XDG_RUNTIME_DIR=/run/user/$(id -u) podman ps -a --filter name={self.container_name} --format \"{{{{.Names}}}}\"'",
                        shell=True, sudo=True, ignore_status=True
                    )
                    if self.container_name in check_result.stdout_text:
                        self.log.warning(
                            "Container %s still exists after removal attempt", self.container_name)
                    else:
                        self.log.info(
                            "Container %s successfully removed", self.container_name)

                # Remove quadlet file
                user_home = pwd.getpwnam(self.test_user).pw_dir
                quadlet_file = os.path.join(
                    user_home, ".config", "containers", "systemd",
                    f"spyre-{self.container_name.replace('spyre-', '')}.container"
                )
                if os.path.exists(quadlet_file):
                    self.log.info("Removing quadlet file: %s", quadlet_file)
                    process.run(f"rm -f {quadlet_file}",
                                shell=True, sudo=True, ignore_status=True)

                # Reload systemd daemon to unload the service
                self.log.info("Reloading systemd daemon")
                process.run(
                    f"su - {self.test_user} -c 'XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user daemon-reload'",
                    shell=True, sudo=True, ignore_status=True
                )

                self.log.info("Cleanup completed successfully")

            except Exception as ex:
                self.log.warning("Failed to cleanup: %s", ex)
