#!/usr/bin/env python
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# See LICENSE for more details.
# Copyright: 2026 IBM
# Authors: Abdul Haleem (abdhalee@linux.ibm.com)

"""
Spyre Host Configuration Test for AI accelerator setup.

This test suite configures a host system for Spyre AI accelerator usage.
Tests run as root for system configuration, with some operations performed
as the configured user (default: senuser) for user-specific setup.
"""

import os
import re
import pwd
import grp
from avocado import Test
from avocado.utils import distro, linux, process
from avocado.utils.software_manager.manager import SoftwareManager

MUST_FIX = "[MUST FIX before running Spyre tests]"


class SpyreHostConfig(Test):
    """Spyre host configuration test for AI accelerator setup."""

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

    def setUp(self):
        """Setup test parameters from YAML and install base packages."""
        if 'ppc' not in distro.detect().arch:
            self.cancel(
                f"{MUST_FIX} Test is only supported on Power (ppc64le) platform. "
                "Ensure you are running on the correct hardware."
            )

        curr_user = self.run_cmd_out('whoami')
        if 'root' not in curr_user:
            self.cancel(
                f"{MUST_FIX} Tests must be run as root. "
                "Please login as root and re-run."
            )

        self.username = self.params.get('USER', default=None)
        self.password = self.params.get('PASSWORD', default=None)
        self.spyre_group = self.params.get('SPYRE_GROUP', default=None)
        self.models_dir = self.params.get(
            'HOST_MODELS_DIR', default='/opt/ibm/spyre/models/src')
        self.api_key = self.params.get('API_KEY', default=None)
        self.registry = self.params.get('REGISTRY', default=None)
        self.servicereport_rpm_url = self.params.get(
            'SERVICEREPORT_URL', default=None)
        self.hf_token = self.params.get('HF_TOKEN', default=None)
        self.gsa_user = self.params.get('GSA_USER', default=None)
        self.gsa_password = self.params.get('GSA_PASSWORD', default=None)
        self.redhat_user = self.params.get('REDHAT_USER', default=None)
        self.redhat_pass = self.params.get('REDHAT_PASSWORD', default=None)

        # username and spyre_group are required for most setup steps
        if not self.username:
            self.cancel(
                f"{MUST_FIX} 'username' parameter is missing from yaml. "
                "Set username in spyre_Host_config.yaml and re-run."
            )
        if not self.spyre_group:
            self.cancel(
                f"{MUST_FIX} 'spyre_group' parameter is missing from yaml. "
                "Set spyre_group in spyre_Host_config.yaml and re-run."
            )

        # Install base and Spyre required packages
        self.log.info("Installing base and Spyre packages")
        packages = ['podman', 'python3-pip', 'git',
                    'pciutils', 'subscription-manager']
        if not self.servicereport_rpm_url:
            packages.extend(['ServiceReport'])
        sm = SoftwareManager()
        failed = []
        for pkg in packages:
            if not sm.check_installed(pkg):
                if not sm.install(pkg):
                    failed.append(pkg)
                else:
                    self.log.info("Installed: %s", pkg)
            else:
                self.log.info("Already installed: %s", pkg)
        if failed:
            self.cancel(
                f"{MUST_FIX} Failed to install base packages: {', '.join(failed)}. "
                "Ensure the system has a working package repository and retry."
            )

    def test_collect_system_info(self):
        """Collect comprehensive system information for debugging."""
        info_data = {}

        # OS Information
        detected_distro = distro.detect()
        info_data['os'] = f"{detected_distro.name} {detected_distro.version}"
        info_data['architecture'] = detected_distro.arch

        # SELinux Status
        info_data['selinux'] = "Enforcing" if linux.is_selinux_enforcing(
        ) else "Disabled/Permissive"

        # Collect all command outputs
        commands = {
            'kernel_version': "uname -r",
            'kernel_full': "uname -a",
            'podman': "podman --version",
            'python': "python3 --version",
            'pip_packages': "pip3 list",
            'pci_devices': "lspci -nn",
            'microcode': "lsmcode",
            'memory': "free -h | grep Mem",
            'disk': "df -h / | tail -1"
        }

        for key, cmd in commands.items():
            try:
                info_data[key] = self.run_cmd_out(cmd).strip()
            except Exception as e:
                info_data[key] = f"Error: {str(e)}"

        output = [
            "=" * 80,
            "SYSTEM INFORMATION",
            "=" * 80,
            f"OS: {info_data['os']}",
            f"Architecture: {info_data['architecture']}",
            f"Kernel Version: {info_data['kernel_version']}",
            f"Kernel Full: {info_data['kernel_full']}",
            f"SELinux: {info_data['selinux']}",
            f"Podman: {info_data['podman']}",
            f"Python: {info_data['python']}",
            "",
            "PIP Packages:",
            f"{info_data['pip_packages']}",
            "",
            "PCI Devices:",
            f"{info_data['pci_devices']}",
            "",
            "Microcode:",
            f"{info_data['microcode']}",
            "",
            f"Memory: {info_data['memory']}",
            f"Disk: {info_data['disk']}",
            "=" * 80
        ]

        self.log.info("\n".join(output))

    def test_install_huggingface_hub(self):
        """Install huggingface_hub (runs as root)."""
        self.log.info("Installing huggingface_hub[cli]")
        if not self.run_cmd("pip3 install huggingface_hub[cli]"):
            self.fail(
                f"{MUST_FIX} Failed to install huggingface_hub[cli]. "
                "Ensure pip3 is working and the system has internet access, then retry."
            )
        self.log.info("huggingface_hub installed")

    def test_huggingface_login(self):
        """Login to HuggingFace (runs as root)."""
        if not self.hf_token:
            self.cancel(
                "HuggingFace token (hf_token) not provided in yaml, skipping login. "
                "Set hf_token in spyre_Host_config.yaml if HuggingFace access is required."
            )

        self.log.info("Logging into HuggingFace")
        if not self.run_cmd(f"hf auth login --token {self.hf_token}"):
            self.fail(
                f"{MUST_FIX} HuggingFace login failed. "
                "Verify hf_token is valid and has the required permissions, then retry."
            )
        self.log.info("Logged into HuggingFace")

    def test_configure_ibm_repo(self):
        """Install ServiceReport (runs as root)."""
        self.log.info("Installing ServiceReport")

        # Use avocado distro utility to detect OS version
        detected_distro = distro.detect()
        os_version = f"rhel{detected_distro.version}" if detected_distro.name.lower() in [
            'rhel', 'redhat'] else "rhel9"
        self.log.info(f"Detected OS version: {os_version}")

        # Install ServiceReport - check if specific RPM URL is provided
        if self.servicereport_rpm_url:
            self.log.info(
                f"Installing ServiceReport from specific RPM: {self.servicereport_rpm_url}")

            rpm_filename = self.servicereport_rpm_url.split('/')[-1]
            rpm_path = f"/tmp/{rpm_filename}"

            # Use GSA credentials for internal pokgsa URLs, plain wget for public URLs
            is_gsa = 'gsa' in self.servicereport_rpm_url
            if is_gsa:
                if not self.gsa_user or not self.gsa_password:
                    self.fail(
                        f"{MUST_FIX} GSA URL detected but gsa_user/gsa_password not provided. "
                        "Set gsa_user and gsa_password in spyre_Host_config.yaml and retry."
                    )
                self.log.info("Downloading RPM from GSA repo (authenticated)")
                download_cmd = (
                    f"wget -q -O {rpm_path} "
                    f"--user={self.gsa_user} --password={self.gsa_password} "
                    f"--no-check-certificate {self.servicereport_rpm_url}"
                )
            else:
                self.log.info("Downloading RPM from public URL")
                download_cmd = f"wget -q -O {rpm_path} {self.servicereport_rpm_url}"

            if not self.run_cmd(download_cmd):
                self.fail(
                    f"{MUST_FIX} Failed to download ServiceReport RPM from: {self.servicereport_rpm_url}. "
                    "Check network connectivity and the URL/credentials in spyre_Host_config.yaml."
                )

            # Install the downloaded RPM using dnf to resolve dependencies automatically
            self.log.info(f"Installing ServiceReport RPM: {rpm_path}")
            install_output = self.run_cmd_out(f"dnf install -y {rpm_path}")
            self.log.info(
                f"ServiceReport installation output: {install_output}")

            # Verify installation
            verify_output = self.run_cmd_out("rpm -qa | grep -i servicereport")
            if not verify_output or "servicereport" not in verify_output.lower():
                self.fail(
                    f"{MUST_FIX} ServiceReport installation failed - package not found after install. "
                    "Check dnf output above for dependency or repo errors and retry."
                )
            self.log.info(f"ServiceReport installed: {verify_output.strip()}")

            # Clean up downloaded RPM
            self.run_cmd(f"rm -f {rpm_path}")
        self.log.info("ServiceReport configured successfully")

    def test_register_redhat_system(self):
        """Register Red Hat system using subscription-manager (runs as root)."""
        if not self.redhat_user or not self.redhat_pass:
            self.cancel(
                f"{MUST_FIX} Red Hat registration credentials (redhat_user / redhat_pass) not provided. "
                "Set them in spyre_Host_config.yaml. "
                "The system must be registered to access RHEL repos required for Spyre."
            )

        # Register the system with subscription-manager (--force handles already-registered systems)
        self.log.info(
            f"Registering system with subscription-manager as user: {self.redhat_user}")
        cmd = (
            f"subscription-manager register "
            f"--username={self.redhat_user} "
            f"--password={self.redhat_pass} "
            f"--force"
        )
        output = self.run_cmd_out(cmd)
        self.log.info(f"Registration output: {output}")

        # Verify registration succeeded
        if "The system has been registered with ID:" not in output and \
                "registered" not in output.lower():
            self.fail(
                f"{MUST_FIX} subscription-manager registration failed. "
                "Verify redhat_user/redhat_pass in spyre_Host_config.yaml are correct "
                "and the system can reach subscription.rhsm.redhat.com, then retry."
            )
        self.log.info("Red Hat system registered successfully")

    def test_podman_login(self):
        """Login to podman registry (runs as root)."""
        if not self.api_key:
            self.cancel(
                f"{MUST_FIX} API key (api_key) not provided in yaml, skipping podman login. "
                "Set api_key in spyre_Host_config.yaml. "
                "Podman login is required to pull Spyre container images."
            )

        self.log.info("Logging into registry: %s", self.registry)
        if not self.run_cmd(f"podman login -u iamapikey -p '{self.api_key}' {self.registry}"):
            self.fail(
                f"{MUST_FIX} Podman login to {self.registry} failed. "
                "Verify api_key in spyre_Host_config.yaml is valid and has pull permissions, "
                "and that the system can reach {self.registry}, then retry."
            )
        self.log.info("Logged into registry")

    def test_disable_selinux(self):
        """Disable SELinux (runs as root)."""
        self.log.info("Disabling SELinux")
        if not linux.is_selinux_enforcing():
            self.log.info("SELinux already disabled or permissive")
            return
        if not self.run_cmd("setenforce 0"):
            self.fail(
                f"{MUST_FIX} Failed to set SELinux to permissive mode. "
                "SELinux must be permissive for Spyre containers to access devices. "
                "Check SELinux policy and retry."
            )
        self.log.info("SELinux set to permissive")

    def test_create_user(self):
        """Create user and set password (runs as root)."""
        self.log.info("Creating user: %s", self.username)
        user_exists = False
        try:
            pwd.getpwnam(self.username)
            self.log.info("User already exists")
            user_exists = True
        except KeyError:
            pass
        if not user_exists:
            if not self.run_cmd(f"adduser {self.username}"):
                self.fail(
                    f"{MUST_FIX} Failed to create user '{self.username}'. "
                    "This user is required to run Spyre workloads. "
                    "Check system user limits or conflicts and retry."
                )
            self.log.info("User created")
        if self.password:
            self.log.info("Setting password for user: %s", self.username)
            if not self.run_cmd(f"echo '{self.username}:{self.password}' | chpasswd"):
                self.fail(
                    f"{MUST_FIX} Failed to set password for user '{self.username}'. "
                    "Ensure the password meets system complexity requirements and retry."
                )
            self.log.info("Password set")
        else:
            self.log.warning(
                "No password provided for user '%s'. "
                "Set 'password' in spyre_Host_config.yaml if login access is required.",
                self.username
            )

    def test_configure_spyre(self):
        """Configure Spyre with ServiceReport (runs as root)."""
        self.log.info("Configuring Spyre")

        # Run servicereport validation
        self.log.info("Running servicereport validation")
        output = self.run_cmd_out("servicereport -v -p spyre")
        self.log.info(f"Validation output: {output}")
        if "FAIL" in output:
            self.fail(
                f"{MUST_FIX} Servicereport validation failed - Spyre configuration is not correct. "
                "Review the servicereport output above, ensure ServiceReport is properly installed "
                "and the Spyre hardware/firmware is recognised, then retry."
            )

        # Run servicereport reset
        self.log.info("Running servicereport reset")
        output = self.run_cmd_out("servicereport -r -p spyre")
        self.log.info(f"Reset output: {output}")

        self.log.info("Spyre configured successfully")

    def test_add_user_to_group(self):
        """Add user to Spyre group (runs as root)."""
        self.log.info("Adding user to group: %s", self.spyre_group)
        try:
            grp.getgrnam(self.spyre_group)
        except KeyError:
            if not self.run_cmd(f"groupadd {self.spyre_group}"):
                self.fail(
                    f"{MUST_FIX} Failed to create group '{self.spyre_group}'. "
                    "This group is required for Spyre device access. "
                    "Check for naming conflicts and retry."
                )
        if not self.run_cmd(f"usermod -aG {self.spyre_group} {self.username}"):
            self.fail(
                f"{MUST_FIX} Failed to add user '{self.username}' to group '{self.spyre_group}'. "
                "Group membership is required for Spyre device access. "
                "Verify both user and group exist and retry."
            )
        self.log.info("User added to group")

    def test_create_model_directories(self):
        """Create model directories (runs as root)."""
        self.log.info("Creating model directories")
        dirs = [
            {"path": self.models_dir, "mode": "0755",
                "owner": "root", "group": "root"},
            {"path": f"{self.models_dir}/src", "mode": "0775",
                "owner": "root", "group": self.spyre_group}
        ]
        for d in dirs:
            cmd = f"install -d -m {d['mode']} -o {d['owner']} -g {d['group']} {d['path']}"
            if not self.run_cmd(cmd):
                self.fail(
                    f"{MUST_FIX} Failed to create model directory: {d['path']}. "
                    "Spyre requires this directory to load AI models. "
                    "Check disk space and permissions, then retry."
                )
        self.log.info(f"Model directory created: {self.models_dir}/src")

    def test_enable_systemd_linger(self):
        """Enable systemd linger (runs as root)."""
        self.log.info("Enabling systemd linger")
        if not self.run_cmd(f"loginctl enable-linger {self.username}"):
            self.fail(
                f"{MUST_FIX} Failed to enable systemd linger for user '{self.username}'. "
                "Linger is required so Spyre user services start at boot without login. "
                "Verify loginctl is available and the user exists, then retry."
            )
        self.log.info("Linger enabled")

    def test_enable_persistent_logging(self):
        """Enable persistent logging (runs as root)."""
        self.log.info("Enabling persistent logging")

        # Ensure systemd is installed
        sm = SoftwareManager()
        if not sm.check_installed('systemd'):
            self.log.info("Installing systemd")
            if not sm.install('systemd'):
                self.fail(
                    f"{MUST_FIX} Failed to install systemd. "
                    "systemd is required for Spyre service management. "
                    "Ensure the system repo is accessible and retry."
                )
        self.log.info("systemd is available")

        if not self.run_cmd("install -d -m 2755 -o root -g systemd-journal /var/log/journal"):
            self.fail(
                f"{MUST_FIX} Failed to create /var/log/journal directory. "
                "Persistent logging is required for Spyre diagnostics. "
                "Check disk space and permissions, then retry."
            )

        journald_conf = "/etc/systemd/journald.conf"
        if not os.path.exists(journald_conf):
            # File does not exist — create it with [Journal] section
            self.log.info(f"{journald_conf} not found, creating it")
            os.makedirs(os.path.dirname(journald_conf), exist_ok=True)
            with open(journald_conf, 'w') as f:
                f.write("[Journal]\nStorage=persistent\n")
        else:
            # File exists — update existing Storage= line or append it
            with open(journald_conf, 'r') as f:
                content = f.read()
            if re.search(r'^#?Storage=', content, re.MULTILINE):
                content = re.sub(
                    r'^#?Storage=.*', 'Storage=persistent', content, flags=re.MULTILINE)
            else:
                content += '\nStorage=persistent\n'
            with open(journald_conf, 'w') as f:
                f.write(content)

        if not self.run_cmd("systemctl restart systemd-journald"):
            self.fail(
                f"{MUST_FIX} Failed to restart systemd-journald. "
                "Persistent logging is required for Spyre diagnostics. "
                "Check journald config at {journald_conf} and retry."
            )
        self.log.info("Persistent logging enabled")

    def test_enable_resource_delegation(self):
        """Enable resource delegation (runs as root)."""
        self.log.info("Enabling resource delegation")
        systemd_dir = "/etc/systemd/system/user@.service.d"
        if not self.run_cmd(f"install -d -m 0755 -o root -g root {systemd_dir}"):
            self.fail(
                f"{MUST_FIX} Failed to create systemd delegation directory: {systemd_dir}. "
                "Resource delegation is required for Spyre cgroup management. "
                "Check disk space and systemd installation, then retry."
            )
        try:
            with open(f"{systemd_dir}/delegate.conf", 'w') as f:
                f.write("[Service]\nDelegate=cpu cpuset memory pids\n")
        except OSError as e:
            self.fail(
                f"{MUST_FIX} Failed to write delegate.conf: {e}. "
                "Resource delegation is required for Spyre cgroup management. "
                "Check permissions on {systemd_dir} and retry."
            )
        if not self.run_cmd("systemctl daemon-reload"):
            self.fail(
                f"{MUST_FIX} Failed to reload systemd daemon after resource delegation config. "
                "Run 'systemctl daemon-reload' manually, resolve any errors, and retry."
            )
        self.log.info("Resource delegation enabled")

    def test_setup_container_directory(self):
        """Setup container directory (runs as configured user: senuser)."""
        self.log.info(
            "Setting up container directory for user: %s", self.username)
        try:
            user_info = pwd.getpwnam(self.username)
            home_dir = user_info.pw_dir
        except KeyError:
            self.fail(
                f"{MUST_FIX} User '{self.username}' not found on the system. "
                "Run test_create_user first to create the user, then retry."
            )

        container_dir = f"{home_dir}/.config/containers/systemd"
        if not self.run_cmd(f"mkdir -p {container_dir}", user=self.username):
            self.fail(
                f"{MUST_FIX} Failed to create container directory: {container_dir}. "
                "This directory is required for Spyre quadlet container definitions. "
                "Check home directory permissions for user '{self.username}' and retry."
            )

        # Verify directory was created
        output = self.run_cmd_out(
            f"ls -ld {container_dir}", user=self.username)
        self.log.info(f"Container directory: {output}")
        if not output or container_dir not in output:
            self.fail(
                f"{MUST_FIX} Container directory verification failed: {container_dir}. "
                "Directory was not created correctly. "
                "Check home directory permissions for user '{self.username}' and retry."
            )

        self.log.info(
            "Container directory created for user: %s", self.username)

    def test_configure_selinux_devices(self):
        """Configure SELinux for devices (runs as root)."""
        self.log.info("Configuring SELinux for devices")
        if not linux.is_selinux_enforcing():
            self.log.info("SELinux is disabled or permissive, skipping")
            return

        self.log.info("Setting container_use_devices SELinux boolean")
        if not self.run_cmd("setsebool -P container_use_devices 1"):
            self.fail(
                f"{MUST_FIX} Failed to set container_use_devices SELinux boolean. "
                "This is required for Spyre containers to access accelerator devices. "
                "Check SELinux policy modules are installed and retry."
            )

        # Verify the boolean is set
        output = self.run_cmd_out("getsebool container_use_devices")
        self.log.info(f"SELinux boolean status: {output}")
        if "container_use_devices --> on" not in output:
            self.fail(
                f"{MUST_FIX} container_use_devices SELinux boolean is not set to 'on' after setsebool. "
                "This is required for Spyre containers to access accelerator devices. "
                "Verify SELinux policy supports this boolean and retry."
            )

        self.log.info("SELinux configured")
