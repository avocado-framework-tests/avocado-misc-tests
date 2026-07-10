#!/usr/bin/env python
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# See LICENSE for more details.
# Copyright: 2026 IBM
# Authors: Abdul Haleem (abdhalee@linux.ibm.com)

"""Spyre Host Configuration Test for AI accelerator setup."""

import os
import re
import pwd
import grp
from avocado import Test
from avocado.utils import process, distro
from avocado.utils.software_manager.manager import SoftwareManager

class SpyreHostConfig(Test):
    """Spyre host configuration test for AI accelerator setup."""

    def setUp(self):
        """Setup test parameters from YAML."""
        if 'ppc' not in distro.detect().arch:
            self.cancel("Test is only supported on Power platform")
        self.username = self.params.get('username', default='')
        self.password = self.params.get('password', default=None)
        self.spyre_group = self.params.get('spyre_group', default='')
        self.models_dir = self.params.get('models_dir', default='/opt/ibm/spyre/models')
        self.registry = self.params.get('registry', default='')
        self.api_key = self.params.get('api_key', default=None)
        self.ibm_repo_url = self.params.get('ibm_repo_url', default=None)

    def get_selinux_status(self):
        """Get current SELinux status."""
        try:
            result = process.run("getenforce", shell=True, ignore_status=True)
            return result.stdout_text.strip()
        except Exception:
            return "Unknown"

    def get_os_version(self):
        """Detect OS version."""
        try:
            result = process.run("cat /etc/os-release", shell=True, ignore_status=True)
            os_release = result.stdout_text
            if "Red Hat Enterprise Linux" in os_release or "RHEL" in os_release:
                version_match = re.search(r'VERSION_ID="?(\d+)', os_release)
                if version_match:
                    return f"rhel{version_match.group(1)}"
            return None
        except Exception:
            return None

    def install_packages(self, packages):
        """Install packages using SoftwareManager."""
        if isinstance(packages, str):
            packages = [packages]
        sm = SoftwareManager()
        failed = []
        for pkg in packages:
            if not sm.check_installed(pkg):
                if not sm.install(pkg):
                    failed.append(pkg)
                else:
                    self.log.info("✓ Installed: %s", pkg)
            else:
                self.log.info("✓ Already installed: %s", pkg)
        if failed:
            self.fail(f"Failed to install: {', '.join(failed)}")

    def test_01_install_base_packages(self):
        """Install base packages."""
        self.log.info("Installing base packages")
        packages = ['podman', 'python3-pip', 'container-tools', 'git', 'git-lfs', 'wget']
        self.install_packages(packages)

    def test_02_install_spyre_packages(self):
        """Install Spyre required packages."""
        self.log.info("Installing Spyre packages")
        packages = ['pciutils', 'podman', 'git', 'ndctl', 'sshpass']
        self.install_packages(packages)

    def test_03_install_huggingface_hub(self):
        """Install huggingface_hub."""
        self.log.info("Installing huggingface_hub[cli]")
        result = process.run("pip3 install huggingface_hub[cli]", shell=True, sudo=True, ignore_status=True)
        if result.exit_status != 0:
            self.fail("Failed to install huggingface_hub")
        self.log.info("✓ huggingface_hub installed")

    def test_04_configure_ibm_repo(self):
        """Configure IBM Tools repository."""
        self.log.info("Configuring IBM Tools Repository")
        process.run(f"rpm -ivh {self.ibm_repo_url}", shell=True, sudo=True, ignore_status=True)
        os_version = self.get_os_version() or "rhel9"
        packages = ['ServiceReport']
        if os_version == "rhel9":
            packages.append('ibm-power-managed-rhel9')
        elif os_version == "rhel8":
            packages.append('ibm-power-managed-rhel8')
        process.run(f"dnf -y install {' '.join(packages)}", shell=True, sudo=True, ignore_status=True)
        self.log.info("✓ IBM Tools configured")

    def test_05_podman_login(self):
        """Login to podman registry."""
        if not self.api_key:
            self.log.warning("API key not provided, skipping podman login")
            return
        self.log.info("Logging into registry: %s", self.registry)
        cmd = f"podman login -u iamapikey -p '{self.api_key}' {self.registry}"
        result = process.run(cmd, shell=True, sudo=True, ignore_status=True)
        if result.exit_status != 0:
            self.fail("Podman login failed")
        self.log.info("✓ Logged into registry")

    def test_06_disable_selinux(self):
        """Disable SELinux."""
        self.log.info("Disabling SELinux")
        status = self.get_selinux_status()
        if status.lower() in ["disabled", "permissive"]:
            self.log.info("✓ SELinux already %s", status.lower())
            return
        result = process.run("setenforce 0", shell=True, sudo=True, ignore_status=True)
        if result.exit_status != 0:
            self.fail("Failed to set SELinux to permissive")
        self.log.info("✓ SELinux set to permissive")

    def test_07_create_user(self):
        """Create user and set password."""
        self.log.info("Creating user: %s", self.username)
        user_exists = False
        try:
            pwd.getpwnam(self.username)
            self.log.info("User already exists")
            user_exists = True
        except KeyError:
            pass
        if not user_exists:
            result = process.run(f"adduser {self.username}", shell=True, sudo=True, ignore_status=True)
            if result.exit_status != 0:
                self.fail("Failed to create user")
            self.log.info("✓ User created")
        if self.password:
            self.log.info("Setting password for user: %s", self.username)
            cmd = f"echo '{self.username}:{self.password}' | chpasswd"
            result = process.run(cmd, shell=True, sudo=True, ignore_status=True)
            if result.exit_status != 0:
                self.fail("Failed to set password")
            self.log.info("✓ Password set")
        else:
            self.log.warning("No password provided, user created without password")

    def test_08_configure_spyre(self):
        """Configure Spyre with ServiceReport."""
        self.log.info("Configuring Spyre")
        commands = ["servicereport -v -p spyre", "servicereport -r -p spyre"]
        for cmd in commands:
            process.run(cmd, shell=True, sudo=True, ignore_status=True)
        self.log.info("✓ Spyre configured")

    def test_09_add_user_to_group(self):
        """Add user to Spyre group."""
        self.log.info("Adding user to group: %s", self.spyre_group)
        try:
            grp.getgrnam(self.spyre_group)
        except KeyError:
            process.run(f"groupadd {self.spyre_group}", shell=True, sudo=True, ignore_status=True)
        result = process.run(f"usermod -aG {self.spyre_group} {self.username}", shell=True, sudo=True, ignore_status=True)
        if result.exit_status != 0:
            self.fail("Failed to add user to group")
        self.log.info("✓ User added to group")

    def test_10_create_model_directories(self):
        """Create model directories."""
        self.log.info("Creating model directories")
        dirs = [
            {"path": self.models_dir, "mode": "0755", "owner": "root", "group": "root"},
            {"path": f"{self.models_dir}/src", "mode": "0775", "owner": "root", "group": self.spyre_group}
        ]
        for d in dirs:
            cmd = f"install -d -m {d['mode']} -o {d['owner']} -g {d['group']} {d['path']}"
            result = process.run(cmd, shell=True, sudo=True, ignore_status=True)
            if result.exit_status != 0:
                self.fail(f"Failed to create: {d['path']}")
        self.log.info("✓ Directories created")

    def test_11_enable_systemd_linger(self):
        """Enable systemd linger."""
        self.log.info("Enabling systemd linger")
        result = process.run(f"loginctl enable-linger {self.username}", shell=True, sudo=True, ignore_status=True)
        if result.exit_status != 0:
            self.fail("Failed to enable linger")
        self.log.info("✓ Linger enabled")

    def test_12_enable_persistent_logging(self):
        """Enable persistent logging."""
        self.log.info("Enabling persistent logging")
        process.run("install -d -m 2755 -o root -g systemd-journal /var/log/journal", shell=True, sudo=True, ignore_status=True)
        process.run("sed -ri 's/^#?Storage=.*/Storage=persistent/' /etc/systemd/journald.conf", shell=True, sudo=True, ignore_status=True)
        process.run("systemctl restart systemd-journald", shell=True, sudo=True, ignore_status=True)
        self.log.info("✓ Persistent logging enabled")

    def test_13_enable_resource_delegation(self):
        """Enable resource delegation."""
        self.log.info("Enabling resource delegation")
        systemd_dir = "/etc/systemd/system/user@.service.d"
        result = process.run(f"install -d -m 0755 -o root -g root {systemd_dir}", shell=True, sudo=True, ignore_status=True)
        if result.exit_status != 0:
            self.fail("Failed to create systemd directory")
        with open(f"{systemd_dir}/delegate.conf", 'w') as f:
            f.write("[Service]\nDelegate=cpu cpuset memory pids\n")
        process.run("systemctl daemon-reload", shell=True, sudo=True, ignore_status=True)
        self.log.info("✓ Resource delegation enabled")

    def test_14_setup_container_directory(self):
        """Setup container directory."""
        self.log.info("Setting up container directory")
        try:
            user_info = pwd.getpwnam(self.username)
            home_dir = user_info.pw_dir
        except KeyError:
            self.fail(f"User {self.username} not found")
        container_dir = f"{home_dir}/.config/containers/systemd"
        result = process.run(f"su - {self.username} -c 'mkdir -p {container_dir}'", shell=True, sudo=True, ignore_status=True)
        if result.exit_status != 0:
            self.fail("Failed to create container directory")
        self.log.info("✓ Container directory created")

    def test_15_configure_selinux_devices(self):
        """Configure SELinux for devices."""
        self.log.info("Configuring SELinux for devices")
        status = self.get_selinux_status()
        if status.lower() in ["disabled", "permissive"]:
            self.log.info("SELinux is %s, skipping", status)
            return
        process.run("setsebool -P container_use_devices 1", shell=True, sudo=True, ignore_status=True)
        self.log.info("✓ SELinux configured")
