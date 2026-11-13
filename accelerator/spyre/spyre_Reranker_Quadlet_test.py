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
from avocado.utils.podman import (
    install_huggingface_cli,
    download_model_from_hf,
    validate_model_with_sha,
    wait_for_vllm_startup
)

USE_CASE = "reranker"


class SpyreRerankerQuadletTest(Test):
    """
    Spyre Quadlet test for the Reranker use case.

    Uses the first AIU PCIe ID only.

    Test methods
    ------------
    test_create_container  -- deploy quadlet, wait for VLLM startup
    test_remove_container  -- stop service, remove container and quadlet file
    """

    container_name = None
    service_name = None
    test_user = None

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    @staticmethod
    def run_cmd_out(cmd, sudo=True):
        """Execute a shell command and return stripped stdout."""
        return process.system_output(
            cmd, shell=True, ignore_status=True,
            sudo=sudo).decode("utf-8").strip()

    def spyre_exists(self):
        """
        Check that VFIO Spyre devices exist under /dev/vfio and that
        the numeric device entries carry the expected spyre_group ownership.

        :return: True if devices are present and correctly owned.
        """
        if not os.path.exists('/dev/vfio'):
            return False
        files = os.listdir('/dev/vfio')
        if not any(f.isdigit() for f in files):
            return False
        if hasattr(self, 'spyre_group') and self.spyre_group:
            try:
                listing = process.system_output(
                    'ls -l /dev/vfio', shell=True, ignore_status=True,
                    sudo=True).decode("utf-8").strip()
                if self.spyre_group not in listing:
                    self.log.warning(
                        "VFIO devices exist but spyre_group '%s' not found",
                        self.spyre_group)
                    return False
                self.log.info("VFIO devices exist with correct spyre_group '%s'",
                              self.spyre_group)
            except Exception as ex:
                self.log.warning("Failed to verify device group ownership: %s", ex)
                return False
        return True

    def create_quadlet_file(self, use_case, aiu_ids, model_path, tp_size,
                            max_model_len, max_batch_size, memory, shm_size=None):
        """
        Write a systemd Quadlet .container unit file for the given use case.

        :return: Absolute path of the written quadlet file.
        """
        user_home = pwd.getpwnam(self.test_user).pw_dir
        systemd_dir = os.path.join(user_home, ".config", "containers", "systemd")

        self.log.info("Creating systemd directory: %s", systemd_dir)
        process.run(f"su - {self.test_user} -c 'mkdir -p {systemd_dir}'",
                    sudo=True, shell=True)

        quadlet_file = os.path.join(systemd_dir, f"spyre-{use_case}.container")
        self.log.info("Creating quadlet file: %s", quadlet_file)

        content = f"""[Unit]
Description=Spyre {use_case.replace('-', ' ').title()}
After=network-online.target

[Container]
ContainerName=spyre-{use_case}
PublishPort={self.port_mapping}
Image={self.container_image}
LogDriver=k8s-file

Environment=AIU_PCIE_IDS="{aiu_ids}"
"""
        if hasattr(self, 'rhaiis_version') and self.rhaiis_version in ("3.3", "3.4"):
            content += 'Environment=VLLM_SPYRE_USE_CB=1\n'

        content += f"""
PodmanArgs=--device={self.device}
PodmanArgs=--userns={self.userns}
PodmanArgs=--group-add={self.group_add}
PodmanArgs=--security-opt={self.security_opt}
PodmanArgs=--pids-limit={self.pids_limit}
PodmanArgs=--memory={memory}
"""
        if shm_size:
            content += f"PodmanArgs=--shm-size={shm_size}\n"

        content += f"""
Volume={self.host_models_dir}:/models

Exec=--model {model_path} -tp {tp_size} --max-model-len {max_model_len} --max-num-seqs {max_batch_size}"""

        if hasattr(self, 'rhaiis_version') and self.rhaiis_version in ("3.3", "3.4"):
            content += " --enable-prefix-caching"

        content += f"""

[Service]
Slice=spyre-{use_case}.slice
Restart=always
RestartSec=15

[Install]
WantedBy=default.target
"""
        temp_file = f"/tmp/spyre-{use_case}.container"
        try:
            with open(temp_file, 'w') as fh:
                fh.write(content)
            process.run(f"cp {temp_file} {quadlet_file}", sudo=True, shell=True)
            process.run(f"chown {self.test_user}:{self.test_user} {quadlet_file}",
                        sudo=True, shell=True)
            self.log.info("Quadlet file content (%s):\n%s", quadlet_file, content)
        finally:
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except OSError as ex:
                    self.log.warning("Failed to remove temp file: %s", ex)
        return quadlet_file

    def reload_systemd_daemon(self):
        """Reload the systemd user daemon."""
        self.log.info("Reloading systemd user daemon")
        process.run(
            f"su - {self.test_user} -c "
            f"'XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user daemon-reload'",
            sudo=True, shell=True)

    def start_service(self, service_name):
        """Start a systemd user service. Returns True on success."""
        self.log.info("Starting service: %s", service_name)
        result = process.run(
            f"su - {self.test_user} -c "
            f"'XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user start {service_name}'",
            shell=True, sudo=True, ignore_status=True)
        return result.exit_status == 0

    def stop_service(self, service_name):
        """Stop a systemd user service."""
        self.log.info("Stopping service: %s", service_name)
        process.run(
            f"su - {self.test_user} -c "
            f"'XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user stop {service_name}'",
            sudo=True, shell=True)

    def check_container_running(self, container_name):
        """Return True if the named Podman container is running."""
        output = self.run_cmd_out(
            f"su - {self.test_user} -c "
            f"'XDG_RUNTIME_DIR=/run/user/$(id -u) "
            f"podman ps --filter name={container_name} --format {{{{.Names}}}}'",
            sudo=True)
        return container_name in output

    def get_service_logs(self, service_name):
        """Return journalctl output for the given systemd user service."""
        return self.run_cmd_out(
            f"su - {self.test_user} -c "
            f"'XDG_RUNTIME_DIR=/run/user/$(id -u) "
            f"journalctl --user -xeu {service_name}'",
            sudo=True)

    def _load_use_case_params(self):
        """
        Build the parameter dict for the reranker use case.
        Uses the first AIU PCIe ID only.
        """
        all_ids = self.params.get("AIU_PCIE_IDS", default="")
        ids = all_ids.split()
        return {
            'aiu_ids': ids[0] if ids else "",
            'model_path': self.params.get("VLLM_MODEL_PATH", default=""),
            'tp_size': self.params.get("AIU_WORLD_SIZE", default=""),
            'max_model_len': self.params.get("MAX_MODEL_LEN", default=""),
            'max_batch_size': self.params.get("MAX_BATCH_SIZE", default=""),
            'memory': self.params.get("MEMORY", default=""),
            'shm_size': self.params.get("SHM_SIZE", default=""),
        }

    # ------------------------------------------------------------------
    # setUp
    # ------------------------------------------------------------------

    def setUp(self):
        """Set up the test environment and validate prerequisites."""
        self.test_user = self.params.get("USER", default="")

        if getattr(self, '_testMethodName', '') == 'test_remove_container':
            return

        if 'powerpc' not in cpu.get_arch():
            self.cancel("Supported only on IBM Power platform")
        with open('/proc/cpuinfo', 'r') as cpuinfo:
            if 'PowerNV' in cpuinfo.read():
                self.cancel("Not supported on the PowerNV platform")

        self.rhaiis_version = self.params.get("RHAIIS_VERSION", default="")
        self.spyre_group = self.params.get("SPYRE_GROUP", default="")
        self.host_models_dir = self.params.get(
            "HOST_MODELS_DIR", default="/opt/ibm/spyre/models/src")
        self.vllm_model_path = self.params.get("VLLM_MODEL_PATH", default="")
        self.hf_model_name = self.params.get("HF_MODEL_NAME", default="")

        container_url = self.params.get("CONTAINER_URL", default="")
        container_tag = self.params.get("CONTAINER_TAG", default="")
        if not container_url or not container_tag:
            self.cancel("CONTAINER_URL and CONTAINER_TAG must be set in YAML")
        self.container_image = f"{container_url}:{container_tag}"
        self.api_key = self.params.get("API_KEY", default="")
        self.device = self.params.get("DEVICE", default="/dev/vfio")
        self.pids_limit = self.params.get("PIDS_LIMIT", default="0")
        self.userns = self.params.get("USERNS", default="keep-id")
        self.group_add = self.params.get("GROUP_ADD", default="keep-groups")
        self.security_opt = self.params.get("SECURITY_OPT", default="label=disable")
        self.port_mapping = self.params.get("PORT_MAPPING", default="127.0.0.1:8000:8000")

        self.log.info("Running servicereport -r -p spyre")
        process.run("servicereport -r -p spyre", sudo=True, shell=True)
        res = self.run_cmd_out("servicereport -v -p spyre")
        if "FAIL" in res:
            self.cancel("Servicereport configuration failed")

        user_check = process.run(f"id -u {self.test_user} 2>/dev/null",
                                 shell=True, sudo=True, ignore_status=True)
        if user_check.exit_status != 0:
            self.cancel(f"Test user {self.test_user} does not exist")

        self.log.info("Adding %s to group %s", self.test_user, self.spyre_group)
        process.run(f"usermod -aG {self.spyre_group} {self.test_user}",
                    sudo=True, shell=True)
        process.run(f"loginctl terminate-user {self.test_user}",
                    sudo=True, shell=True, ignore_status=True)
        time.sleep(2)
        process.run(f"loginctl enable-linger {self.test_user}",
                    sudo=True, shell=True)

        if self.spyre_group not in self.run_cmd_out(f"groups {self.test_user}"):
            self.cancel(f"User {self.test_user} is not in {self.spyre_group} group")

        if self.api_key:
            registry = self.container_image.split('/')[0] \
                if '/' in self.container_image else 'icr.io'
            login_result = process.run(
                f"su - {self.test_user} -c 'XDG_RUNTIME_DIR=/run/user/$(id -u) "
                f"echo {self.api_key} | podman login {registry} "
                f"--username iamapikey --password-stdin'",
                shell=True, sudo=True, ignore_status=True)
            if login_result.exit_status != 0:
                self.log.warning("Failed to login to registry %s", registry)
        else:
            self.log.info("No API_KEY provided — assuming image is available locally")

        if self.host_models_dir and not os.path.exists(self.host_models_dir):
            try:
                os.makedirs(self.host_models_dir, exist_ok=True)
            except Exception as ex:
                self.cancel(f"Failed to create HOST_MODELS_DIR: {ex}")

        if not install_huggingface_cli():
            self.cancel("Failed to install Hugging Face CLI")

        if self.hf_model_name:
            model_name = os.path.basename(self.vllm_model_path)
            model_dir = os.path.join(self.host_models_dir, model_name)
            model_exists = (
                os.path.isdir(model_dir) and
                any(f.startswith('config') for f in os.listdir(model_dir))
            )
            if not model_exists:
                self.log.info("Downloading model: %s", self.hf_model_name)
                if not download_model_from_hf(hf_model_id=self.hf_model_name,
                                              local_dir=self.host_models_dir,
                                              model_name=model_name):
                    self.cancel(f"Failed to download model {self.hf_model_name}")
                is_valid, messages = validate_model_with_sha(model_dir)
                for msg in messages:
                    self.log.info("  %s", msg)
                if not os.path.exists(model_dir):
                    self.cancel(f"Model directory not found after download: {model_dir}")
            else:
                self.log.info("Model already exists: %s", model_dir)
        else:
            if not os.path.exists(self.host_models_dir):
                self.cancel(f"Models directory {self.host_models_dir} does not exist")

    # ------------------------------------------------------------------
    # Test methods
    # ------------------------------------------------------------------

    def test_create_container(self):
        """Deploy the reranker quadlet container and wait for VLLM startup."""
        self.container_name = f"spyre-{USE_CASE}"
        self.service_name = f"spyre-{USE_CASE}.service"
        self.log.info("=== test_create_container: %s ===", USE_CASE.upper())

        if not self.spyre_exists():
            self.fail("VFIO Spyre devices not found or not properly configured")

        params = self._load_use_case_params()
        quadlet_file = self.create_quadlet_file(
            USE_CASE, params['aiu_ids'], params['model_path'],
            params['tp_size'], params['max_model_len'],
            params['max_batch_size'], params['memory'], params.get('shm_size'))
        self.log.info("Quadlet file created: %s", quadlet_file)

        self.reload_systemd_daemon()

        if not self.start_service(self.service_name):
            self.fail(f"Failed to start service {self.service_name}\n"
                      + self.get_service_logs(self.service_name))

        time.sleep(5)
        if not self.check_container_running(self.container_name):
            self.fail(f"Container {self.container_name} was not created\n"
                      + self.get_service_logs(self.service_name))

        self.log.info("Monitoring container for VLLM startup")
        startup_success = wait_for_vllm_startup(
            container_id=self.container_name,
            success_pattern="Application startup complete.",
            failure_pattern="BACKTRACE",
            additional_failure_checks=[("VFIO", False), ("fail", False)],
            timeout=600, check_interval=10,
            user=self.test_user, log=self.log,
            show_live_logs=True, live_log_lines=20)

        self.log.info("Service logs:\n%s", self.get_service_logs(self.service_name))

        if not startup_success:
            self.fail(f"FAIL: {USE_CASE.upper()} — VLLM did not start")
        self.log.info("PASS: %s container created and VLLM startup completed",
                      USE_CASE.upper())

    def test_remove_container(self):
        """Stop the reranker service, remove container and quadlet files."""
        self.container_name = f"spyre-{USE_CASE}"
        self.service_name = f"spyre-{USE_CASE}.service"
        self.log.info("=== test_remove_container: %s ===", USE_CASE.upper())

        try:
            logs = self.get_service_logs(self.service_name)
            if logs:
                self.log.info("Service logs:\n%s", logs)
        except Exception as ex:
            self.log.warning("Could not get service logs: %s", ex)

        self.stop_service(self.service_name)

        process.run(
            f"su - {self.test_user} -c "
            f"'XDG_RUNTIME_DIR=/run/user/$(id -u) podman stop -t 10 {self.container_name}'",
            shell=True, sudo=True, ignore_status=True)
        process.run(
            f"su - {self.test_user} -c "
            f"'XDG_RUNTIME_DIR=/run/user/$(id -u) podman rm -f {self.container_name}'",
            shell=True, sudo=True, ignore_status=True)

        remaining = self.run_cmd_out(
            f"su - {self.test_user} -c "
            f"'XDG_RUNTIME_DIR=/run/user/$(id -u) podman ps -a "
            f"--filter name=^{self.container_name}$ --format \"{{{{.Names}}}}\"'")
        if self.container_name in remaining.splitlines():
            self.fail(f"Container {self.container_name} still exists after removal")
        self.log.info("Container %s removed", self.container_name)

        user_home = pwd.getpwnam(self.test_user).pw_dir
        quadlet_file = os.path.join(
            user_home, ".config", "containers", "systemd",
            f"spyre-{USE_CASE}.container")
        if os.path.exists(quadlet_file):
            process.run(f"rm -f {quadlet_file}", shell=True, sudo=True,
                        ignore_status=True)

        temp_file = f"/tmp/spyre-{USE_CASE}.container"
        if os.path.exists(temp_file):
            process.run(f"rm -f {temp_file}", shell=True, sudo=True,
                        ignore_status=True)

        process.run(
            f"su - {self.test_user} -c "
            f"'XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user daemon-reload'",
            shell=True, sudo=True, ignore_status=True)

        self.log.info("PASS: %s container and files removed", USE_CASE.upper())
