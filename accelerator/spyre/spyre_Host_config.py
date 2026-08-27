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
as the configured user for user-specific setup.
"""

import os
import re
import pwd
import stat
import tempfile
import urllib.parse
from avocado import Test
from avocado.utils.podman import Podman
from avocado.utils import distro, linux, process
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils.software_manager.backends.rpm import RpmBackend

MUST_FIX = "[MUST FIX before running Spyre tests]"


class SpyreHostConfig(Test):
    """Spyre host configuration test for AI accelerator setup."""

    # ------------------------------------------------------------------ #
    # Credential helpers                                                   #
    # ------------------------------------------------------------------ #

    def _write_secret_tmpfile(self, secret, suffix='.secret'):
        """Write *secret* to a root-readable-only temp file.

        Returns the path.  The caller is responsible for unlinking it inside
        a ``finally`` block.
        """
        with tempfile.NamedTemporaryFile(
                mode='w', delete=False, suffix=suffix) as tmp:
            tmp.write(secret.strip() + '\n')
            tmp_path = tmp.name
        os.chmod(tmp_path, stat.S_IRUSR)   # 0o400 — owner read-only
        return tmp_path

    def _load_secrets(self, secrets_path):
        """Load credentials from a ``.secrets`` file (if present).

        *secrets_path* is read from the YAML parameter ``SECRETS_FILE``
        (default ``/root/input/spyre_Host_config.secrets``).

        Format — one assignment per line::

            KEY=value

        Blank lines and lines starting with ``#`` are ignored.
        Values are stripped of leading/trailing whitespace.
        Non-empty values in the secrets file override whatever was loaded from
        the YAML so credentials never need to live in the YAML itself.
        """
        if not os.path.exists(secrets_path):
            self.log.warning(
                "Secrets file not found, credentials must be set in YAML: %s",
                secrets_path)
            return

        self.log.info(
            "Loading credentials from secrets file: %s", secrets_path)
        # Map secrets-file keys → instance attribute names.
        # Credentials (sensitive) and the two config overrides (SPYRE_GROUP,
        # REGISTRY) are all accepted so the secrets file can carry everything.
        key_map = {
            'USER':             'username',
            'PASSWORD':         'password',
            'SPYRE_GROUP':      'spyre_group',
            'REGISTRY':         'registry',
            'API_KEY':          'api_key',
            'GSA_USER':         'gsa_user',
            'GSA_PASSWORD':     'gsa_password',
            'REDHAT_USER':      'redhat_user',
            'REDHAT_PASSWORD':  'redhat_pass',
            'HF_TOKEN':         'hf_token',
            'JFROG_USERID':     'jfrog_userid',
            'JFROG_TOKEN':      'jfrog_token',
            'JFROG_URL':        'jfrog_url',
        }
        with open(secrets_path, 'r') as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, _, value = line.partition('=')
                key = key.strip()
                value = value.strip()
                if key in key_map and value:
                    setattr(self, key_map[key], value)

    def _write_netrc_tmpfile(self, host, login, password):
        """Write a minimal ~/.netrc entry for *host* temporarily.

        Appends to ~/.netrc before the download and removes the entry after.
        Returns (netrc_path, entry) so the caller can clean up.
        """
        netrc_path = os.path.expanduser("~/.netrc")
        entry = f"\nmachine {host} login {login} password {password}\n"
        with open(netrc_path, 'a') as f:
            f.write(entry)
        os.chmod(netrc_path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
        return netrc_path, entry

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
        self.jfrog_userid = self.params.get('JFROG_USERID', default=None)
        self.jfrog_token = self.params.get('JFROG_TOKEN', default=None)
        self.jfrog_url = self.params.get('JFROG_URL', default=None)
        self.senlib_rpm_path = self.params.get("SENLIB_RPM_PATH", default=None)
        self.secrets_file = self.params.get(
            'SECRETS_FILE', default='/root/input/spyre_Host_config.secrets')

        # Override blank YAML values with credentials from the secrets file
        self._load_secrets(self.secrets_file)

        # username and spyre_group are required for most setup steps
        if not self.username:
            self.cancel(
                f"{MUST_FIX} 'USER' is not set. "
                "Add it to spyre_Host_config.secrets (preferred) or "
                "spyre_Host_config.yaml and re-run."
            )
        if not self.spyre_group:
            self.cancel(
                f"{MUST_FIX} 'SPYRE_GROUP' is not set. "
                "Add it to spyre_Host_config.secrets (preferred) or "
                "spyre_Host_config.yaml and re-run."
            )
        # Install base and Spyre required packages
        self.log.info("Installing base and Spyre packages")
        packages = ['podman', 'python3-pip', 'python3-pyudev', 'git',
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
        self.podman = Podman()

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

    def test_configure_ibm_repo(self):
        """Install ServiceReport (runs as root)."""
        self.log.info("Installing ServiceReport")

        # Install ServiceReport - check if specific RPM URL is provided
        if self.servicereport_rpm_url:
            self.log.info(
                f"Installing ServiceReport from specific RPM: {self.servicereport_rpm_url}")

            rpm_filename = self.servicereport_rpm_url.split('/')[-1]
            rpm_path = f"/tmp/{rpm_filename}"

            # Use GSA credentials for internal URLs, plain wget for public URLs
            parsed = urllib.parse.urlparse(self.servicereport_rpm_url)
            is_gsa = parsed.hostname and parsed.hostname.endswith('.ibm.com')
            if is_gsa:
                if not self.gsa_user or not self.gsa_password:
                    self.fail(
                        f"{MUST_FIX} GSA URL detected but GSA_USER/GSA_PASSWORD not provided. "
                        "Set them in spyre_Host_config.secrets and retry."
                    )
                self.log.info("Downloading RPM from GSA repo (authenticated)")
                # Extract the hostname to scope the netrc entry precisely
                gsa_host = urllib.parse.urlparse(
                    self.servicereport_rpm_url).hostname
                netrc_path, netrc_entry = self._write_netrc_tmpfile(
                    gsa_host, self.gsa_user, self.gsa_password)
                try:
                    download_cmd = (
                        f"wget -q -O {rpm_path} "
                        f"--netrc --no-check-certificate "
                        f"{self.servicereport_rpm_url}"
                    )
                    download_ok = self.run_cmd(download_cmd)
                finally:
                    # Remove only the entry we appended, leave the rest intact
                    with open(netrc_path, 'r') as f:
                        content = f.read()
                    with open(netrc_path, 'w') as f:
                        f.write(content.replace(netrc_entry, ""))
                if not download_ok:
                    self.fail(
                        f"{MUST_FIX} Failed to download ServiceReport RPM from: "
                        f"{self.servicereport_rpm_url}. "
                        "Check network connectivity and the URL/credentials in "
                        "spyre_Host_config.yaml."
                    )
            else:
                self.log.info("Downloading RPM from public URL")
                download_cmd = f"wget -q -O {rpm_path} {self.servicereport_rpm_url}"
                if not self.run_cmd(download_cmd):
                    self.fail(
                        f"{MUST_FIX} Failed to download ServiceReport RPM from: "
                        f"{self.servicereport_rpm_url}. "
                        "Check network connectivity and the URL in spyre_Host_config.yaml."
                    )

            # Remove any existing ServiceReport installation before installing the new one
            self.run_cmd("rpm -e --nodeps ServiceReport 2>/dev/null || true")

            # Install the downloaded RPM
            self.log.info(f"Installing ServiceReport RPM: {rpm_path}")
            if not RpmBackend.rpm_install(rpm_path, no_dependencies=True, replace=False):
                self.fail(
                    f"{MUST_FIX} ServiceReport installation failed - package not found after install. "
                )
            # Clean up downloaded RPM
            self.run_cmd(f"rm -f {rpm_path}")
            self.log.info("ServiceReport configured successfully")

    def test_register_redhat_system(self):
        """Register Red Hat system using subscription-manager (runs as root)."""
        if not self.redhat_user or not self.redhat_pass:
            self.cancel(
                f"{MUST_FIX} Red Hat registration credentials (REDHAT_USER / REDHAT_PASSWORD) not provided. "
                "Set them in spyre_Host_config.secrets. "
                "The system must be registered to access RHEL repos required for Spyre."
            )

        # Register the system with subscription-manager (--force handles already-registered systems).
        self.log.info(
            "Registering system with subscription-manager as user: %s", self.redhat_user)
        result = process.run(
            f"subscription-manager register "
            f"--username {self.redhat_user} "
            f"--password {self.redhat_pass} "
            f"--force",
            shell=True, sudo=True, ignore_status=True
        )
        output = result.stdout_text.strip()
        # Mask credentials from output before logging
        masked_output = re.sub(
            re.escape(self.redhat_user) + r'|' + re.escape(self.redhat_pass),
            '***', output
        )
        self.log.info("Registration output: %s", masked_output)

        # Verify registration succeeded
        if "The system has been registered with ID:" not in output and \
                "registered" not in output.lower():
            self.fail(
                f"{MUST_FIX} subscription-manager registration failed. "
                "Verify REDHAT_USER/REDHAT_PASSWORD in spyre_Host_config.secrets are correct "
                "and the system can reach subscription.rhsm.redhat.com, then retry."
            )
        self.log.info("Red Hat system registered successfully")

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
            # Write the chpasswd input (user:pass) to a temp file so neither
            # the password nor the literal string appears in any process log.
            chpasswd_input = f"{self.username}:{self.password}"
            tmp_path = self._write_secret_tmpfile(
                chpasswd_input, suffix='.chpasswd')
            try:
                result = process.run(
                    f"cat {tmp_path} | chpasswd",
                    shell=True, sudo=True, ignore_status=True
                )
            finally:
                os.unlink(tmp_path)
            if result.exit_status != 0:
                self.fail(
                    f"{MUST_FIX} Failed to set password for user '{self.username}'. "
                    "Ensure the password meets system complexity requirements and retry."
                )
            self.log.info("Password set")
        else:
            self.log.warning(
                "No password provided for user '%s'. "
                "Set PASSWORD in spyre_Host_config.secrets if login access is required.",
                self.username
            )

    def test_configure_spyre(self):
        """Configure Spyre with ServiceReport (runs as root)."""
        self.log.info("Configuring Spyre")
        self.log.info("Running servicereport validation")
        output = self.run_cmd_out("servicereport -v -p spyre")
        self.log.info(f"Validation output: {output}")

        if "invalid or not applicable" in output or "Warning" in output:
            self.cancel(
                "servicereport reports Spyre plugin is invalid or not applicable "
                "to this system — no Spyre hardware/firmware detected, skipping test."
            )

        if "FAIL" in output:
            self.log.info("Running servicereport reset")
            output = self.run_cmd_out("servicereport -r -p spyre")
            self.log.info(f"Reset output: {output}")
            output = self.run_cmd_out("servicereport -v -p spyre")
            self.log.info(f"Validation output after reset: {output}")
            if "FAIL" in output:
                self.fail(
                    f"{MUST_FIX} Servicereport validation failed - Spyre configuration is not correct. "
                    "Review the servicereport output above, ensure ServiceReport is properly installed "
                    "and the Spyre hardware/firmware is recognised, then retry."
                )

    def test_add_user_to_group(self):
        """Add senuser to the Spyre group and verify membership via a fresh login."""
        self.log.info("Adding user '%s' to group: %s",
                      self.username, self.spyre_group)
        # ── 1. Ensure the group exists ──────────────────────────────────────────
        if 'sentient' not in self.run_cmd_out(f"getent group {self.spyre_group}"):
            self.log.info("Group '%s' not found — creating it",
                          self.spyre_group)

            if self.run_cmd(f"groupadd -f {self.spyre_group}"):
                self.fail(
                    f"{MUST_FIX} Failed to create group '{self.spyre_group}'. "
                    "This group is required for Spyre device access. "
                    "Check for naming conflicts and retry."
                )
        else:
            self.log.info("Group '%s' already exists", self.spyre_group)

        # ── 2. Add the user to the group ────────────────────────────────────────
        self.log.info("Running: usermod -aG %s %s",
                      self.spyre_group, self.username)
        self.run_cmd(f"usermod -aG {self.spyre_group} {self.username}")
        self.log.info("Running: usermod -aG %s root", self.spyre_group)
        self.run_cmd(f"usermod -aG {self.spyre_group} root")

        # ── 3. Verify membership via a new login session ────────────────────────
        self.log.info(
            "Verifying group membership with a fresh login session for '%s'",
            self.username,
        )
        output = self.run_cmd_out(f"su -l root -c 'groups'")
        self.log.info("groups output for 'root': %s", output)
        if self.spyre_group not in output.split():
            self.fail("{MUST_FIX} User 'root' is NOT a member of group ")

        output = self.run_cmd_out(f"su -l {self.username} -c 'groups'")
        self.log.info("groups output for '%s': %s", self.username, output)

        if self.spyre_group not in output.split():
            self.fail(
                f"{MUST_FIX} User '{self.username}' is NOT a member of group "
                f"'{self.spyre_group}' after a fresh login session. "
                f"'groups' reported: {output!r}. "
                "Confirm usermod executed without error and that the user's "
                "passwd/shadow entry is correct."
            )

        self.log.info(
            "Confirmed: user '%s' is a member of group '%s'",
            self.username, self.spyre_group,
        )

    def test_create_model_directories(self):
        """Create model directories (runs as root)."""
        self.log.info("Creating model directories")
        cmd = f"install -d -m 0775 -o root -g {self.spyre_group} {self.models_dir}"
        if not self.run_cmd(cmd):
            self.fail(
                f"{MUST_FIX} Failed to create model directory: {self.models_dir}. "
                "Spyre requires this directory to load AI models. "
                "Check disk space and permissions, then retry."
            )
        self.log.info(f"Model directory created: {self.models_dir}")

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
                f"Check journald config at {journald_conf} and retry."
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
                f"Check permissions on {systemd_dir} and retry."
            )
        if not self.run_cmd("systemctl daemon-reload"):
            self.fail(
                f"{MUST_FIX} Failed to reload systemd daemon after resource delegation config. "
                "Run 'systemctl daemon-reload' manually, resolve any errors, and retry."
            )
        self.log.info("Resource delegation enabled")

    def test_setup_container_directory(self):
        """Setup container directory (configure in test user)."""
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
                f"Check home directory permissions for user '{self.username}' and retry."
            )

        # Verify directory was created
        output = self.run_cmd_out(
            f"ls -ld {container_dir}", user=self.username)
        self.log.info(f"Container directory: {output}")
        if not output or container_dir not in output:
            self.fail(
                f"{MUST_FIX} Container directory verification failed: {container_dir}. "
                "Directory was not created correctly. "
                f"Check home directory permissions for user '{self.username}' and retry."
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

    def test_podman_login(self):
        """Login to podman registry (runs as root and as test user).

        The API key is written into a root-readable-only temp shell script
        and passed via ``--password-stdin`` so it never appears on the
        command line or in any process log.
        """
        if not self.api_key:
            self.cancel(
                f"{MUST_FIX} API_KEY not provided, skipping podman login. "
                "Set API_KEY in spyre_Host_config.secrets. "
                "Podman login is required to pull Spyre container images."
            )
        registry = self.registry or ''
        self.log.info("Logging into registry: %s", registry)

        # Root login
        root_result = process.run(
            f"echo {self.api_key} | "
            f"podman login {registry} --username iamapikey --password-stdin",
            shell=True, sudo=True, ignore_status=True
        )
        if root_result.exit_status != 0:
            self.fail(
                f"{MUST_FIX} Podman login (root) to {registry} failed. "
                "Verify API_KEY in spyre_Host_config.secrets is valid and has pull "
                f"permissions, and that the system can reach {registry}, then retry."
            )

        # User login — run as the configured test user under its own XDG session
        user_result = process.run(
            f"su - {self.username} -c "
            f"'XDG_RUNTIME_DIR=/run/user/$(id -u) "
            f"echo {self.api_key} | "
            f"podman login {registry} --username iamapikey --password-stdin'",
            shell=True, sudo=True, ignore_status=True
        )
        if user_result.exit_status != 0:
            self.fail(
                f"{MUST_FIX} Podman login (user: {self.username}) to {registry} failed. "
                "Verify API_KEY in spyre_Host_config.secrets is valid and has pull "
                f"permissions, and that the system can reach {registry}, then retry."
            )
        self.log.info("Logged into registry: %s", registry)

    def test_huggingface_login(self):
        """Login to HuggingFace (runs as root and as test user)."""
        if not self.hf_token:
            self.cancel(
                "HuggingFace token not provided, skipping login. "
                "Set HF_TOKEN in spyre_Host_config.secrets if HuggingFace access is required."
            )

        self.log.info("Logging into HuggingFace")
        login_cmd = f"hf auth login --token {self.hf_token}"

        # Root login
        if not self.run_cmd(login_cmd):
            self.fail(
                f"{MUST_FIX} HuggingFace login (root) failed. "
                "Verify hf_token is valid and has the required permissions, then retry."
            )

        # User login
        if not self.run_cmd(login_cmd, user=self.username):
            self.fail(
                f"{MUST_FIX} HuggingFace login (user: {self.username}) failed. "
                "Verify hf_token is valid and has the required permissions, then retry."
            )

        self.log.info("Logged into HuggingFace for root and %s", self.username)

    def test_install_configure_jfrog(self):
        """Install JFrog CLI, configure server, and download Spyre RPM."""
        self.log.info("Installing JFrog CLI")
        if not self.run_cmd("curl -fL https://install-cli.jfrog.io | sh"):
            self.fail(
                f"{MUST_FIX} Failed to install JFrog CLI. "
                "Ensure curl is available and the JFrog install endpoint is reachable."
            )

        self.log.info("Removing existing JFrog server config 'myserver'")
        # Ignore failure — the config may not exist yet on a fresh system
        self.run_cmd('jf config remove myserver --quiet')

        self.log.info("Adding JFrog server config 'myserver'")
        jf_add_cmd = (
            f"jf config add myserver "
            f"--url {self.jfrog_url} "
            f"--artifactory-url {self.jfrog_url}/artifactory "
            f"--user {self.jfrog_userid} "
            f"--access-token {self.jfrog_token} "
            f"--interactive=false "
            f"--overwrite"
        )
        masked_cmd = re.sub(
            re.escape(self.jfrog_userid) + r'|' + re.escape(self.jfrog_token),
            '***', jf_add_cmd
        )
        self.log.info("Running: %s", masked_cmd)
        if not self.run_cmd(jf_add_cmd):
            self.fail(
                f"{MUST_FIX} Failed to configure JFrog server 'myserver'. "
                "Verify that jf_user and jf_token are correct and have sufficient permissions."
            )

        if not self.senlib_rpm_path:
            self.fail(
                f'{MUST_FIX} "{self.senlib_rpm_path}" parameter is required but was not provided. '
                'Set it in the YAML configuration file.'
            )

        self.log.info("Downloading Spyre RPM from Artifactory: %s",
                      self.senlib_rpm_path)
        dl_cmd = f'jf rt dl "{self.senlib_rpm_path}" /root/ --server-id myserver --flat'
        if not self.run_cmd(dl_cmd):
            self.fail(
                f"{MUST_FIX} Failed to download Spyre RPM from Artifactory. "
                "Check that the artifact path is correct and 'myserver' credentials "
                "have read access to the repository."
            )

        self.log.info("Spyre senlib RPM downloaded to /root")
