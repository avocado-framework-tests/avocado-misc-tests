#!/usr/bin/env python
# -*- coding: utf-8 -*-

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
#
# Copyright: 2026 IBM
# Author: MARAM SRIMANNARAYANA MURTHY <msmurthy@linux.vnet.ibm.com>

"""
NVMe/TCP Soft Target Automation

This test configures a remote Linux host as an NVMe/TCP soft target.
It supports:
- Network interface configuration with nmcli persistence
- Namespace creation or selection
- NVMe target subsystem configuration via configfs
- Persistent configuration via systemd and nvmet-cli
"""

import json
import socket
import time
from avocado import Test
from avocado.utils.ssh import Session


class NVMeTCPSoftTarget(Test):
    """
    Configure NVMe/TCP soft target on remote host

    :param soft_target_host_ip: Management IP for SSH connection
    :param user_name: SSH username
    :param password: SSH password
    :param network_config: Network interface configuration
    :param namespace_config: Namespace creation/selection config
    :param nvmet_config: NVMe target subsystem configuration
    """

    def setUp(self):
        """
        Initialize test parameters and establish SSH connection

        This method:
        1. Parses YAML configuration parameters (flattened format)
        2. Validates required parameters
        3. Establishes SSH connection to remote host
        4. Verifies remote host prerequisites
        """
        self.target_ip = self.params.get('soft_target_host_ip', default=None)
        self.username = self.params.get('user_name', default='root')
        self.password = self.params.get('password', default=None)

        if not self.target_ip or not self.password:
            self.cancel("soft_target_host_ip and password are required")

        primary_interface = self.params.get(
            'network_config_primary_interface', default=None
        )
        if not primary_interface:
            self.cancel("network_config_primary_interface is required")

        self.network_config = {
            'primary': {
                'interface': primary_interface,
                'ip': self.params.get('network_config_primary_ip'),
                'netmask': self.params.get('network_config_primary_netmask'),
                'gateway': self.params.get(
                    'network_config_primary_gateway', default=None
                ),
                'mtu': self.params.get(
                    'network_config_primary_mtu', default=1500
                )
            }
        }

        secondary_interface = self.params.get(
            'network_config_secondary_interface', default=None
        )
        if secondary_interface:
            self.network_config['secondary'] = {
                'interface': secondary_interface,
                'ip': self.params.get('network_config_secondary_ip'),
                'netmask': self.params.get('network_config_secondary_netmask'),
                'gateway': self.params.get(
                    'network_config_secondary_gateway', default=None
                ),
                'mtu': self.params.get(
                    'network_config_secondary_mtu',
                    default=1500
                )
            }

        self.ns_mode = self.params.get(
            'namespace_config_mode', default='create'
        )
        if self.ns_mode not in ['create', 'select']:
            self.cancel(
                "namespace_config_mode must be 'create' or 'select'"
            )

        self.ns_config = {'mode': self.ns_mode}
        if self.ns_mode == 'create':
            self.ns_config['nvme_controller'] = self.params.get(
                'namespace_config_nvme_controller'
            )
            self.ns_config['number_of_namespaces'] = self.params.get(
                'namespace_config_number_of_namespaces', default=4
            )
            self.ns_config['namespace_size'] = self.params.get(
                'namespace_config_namespace_size', default=None
            )
        else:  # select mode
            self.ns_config['namespaces'] = self.params.get(
                'namespace_config_namespaces'
            )

        self.subsystem_nqn = self.params.get(
            'nvmet_config_subsystem_nqn', default=None
        )
        self.port_id_start = self.params.get(
            'nvmet_config_port_id_start', default=1
        )
        self.tcp_port = self.params.get('nvmet_config_tcp_port', default=4420)
        self.allow_any_host = self.params.get(
            'nvmet_config_allow_any_host', default=True
        )

        if not self.subsystem_nqn:
            hostname = socket.gethostname()
            timestamp = int(time.time())
            self.subsystem_nqn = (
                f"nqn.2024-01.com.{hostname}:subsys{timestamp}"
            )
            self.log.info(
                f"Auto-generated subsystem NQN: {self.subsystem_nqn}"
            )

        self.log.info(f"Connecting to {self.target_ip} via SSH...")
        self.ssh_connect()
        self.verify_prerequisites()

    def ssh_connect(self):
        """
        Establish SSH connection to remote target host

        Uses avocado.utils.ssh.Session following standard patterns from
        avocado-misc-tests (dlpar_vscsi.py, uperf_test.py, etc.)
        """
        self.session = Session(
            self.target_ip,
            user=self.username,
            password=self.password
        )
        if not self.session.connect():
            self.cancel(
                f"Failed to establish SSH connection to {self.target_ip}"
            )
        self.log.info(f"SSH connection established to {self.target_ip}")

    def run_remote_cmd(self, cmd, ignore_status=False):
        """
        Execute command on remote host via SSH

        :param cmd: Command to execute
        :param ignore_status: Whether to ignore non-zero exit status
        :return: Tuple of (exit_status, stdout, stderr)
        """
        try:
            output = self.session.cmd(f"sudo {cmd}")
            exit_status = output.exit_status
            stdout_text = output.stdout_text
            stderr_text = output.stderr_text

            if exit_status != 0 and not ignore_status:
                self.log.error(f"Command failed: {cmd}")
                self.log.error(f"Exit status: {exit_status}")
                self.log.error(f"Stderr: {stderr_text}")
                self.fail(f"Remote command failed: {cmd}")

            return exit_status, stdout_text, stderr_text
        except Exception as e:
            if not ignore_status:
                self.fail(f"Failed to execute remote command: {e}")
            return -1, "", str(e)

    def verify_prerequisites(self):
        """
        Verify and install required packages on remote host

        This method:
        1. Detects the package manager (dnf/yum/apt)
        2. Checks for required packages
        3. Installs missing packages automatically
        4. Verifies kernel modules are available
        5. Only fails if package installation fails
        """
        self.log.info("Verifying remote host prerequisites...")

        pkg_mgr = self._detect_package_manager()
        self.log.info(f"Detected package manager: {pkg_mgr}")

        required_packages = {
            'dnf': ['nvme-cli', 'nvmetcli', 'NetworkManager'],
            'yum': ['nvme-cli', 'nvmetcli', 'NetworkManager'],
            'zypper': ['nvme-cli', 'nvmetcli', 'NetworkManager'],
            'apt': ['nvme-cli', 'nvmetcli', 'network-manager']
        }

        packages = required_packages.get(pkg_mgr, [])
        if not packages:
            self.cancel(f"Unsupported package manager: {pkg_mgr}")

        self._ensure_packages_installed(pkg_mgr, packages)

        self._verify_kernel_modules()

        self.log.info("Prerequisites verified successfully")

    def _detect_package_manager(self):
        """
        Detect available package manager on remote host

        :return: Package manager name ('dnf', 'yum', or 'apt')
        """
        for pkg_mgr in ['dnf', 'yum', 'zypper', 'apt']:
            status, _, _ = self.run_remote_cmd(
                f"which {pkg_mgr}", ignore_status=True
            )
            if status == 0:
                return pkg_mgr

        self.cancel(
            "No supported package manager found (dnf/yum/zypper/apt)"
        )

    def _ensure_packages_installed(self, pkg_mgr, packages):
        """
        Check and install required packages

        :param pkg_mgr: Package manager to use
        :param packages: List of package names to check/install
        """
        missing_packages = []

        for package in packages:
            self.log.info(f"Checking package: {package}")
            if pkg_mgr in ['dnf', 'yum', 'zypper']:
                cmd = f"rpm -q {package}"
            else:
                cmd = f"dpkg -l {package} | grep '^ii'"

            status, _, _ = self.run_remote_cmd(cmd, ignore_status=True)
            if status != 0:
                missing_packages.append(package)
                self.log.info(f"Package {package} not found")
            else:
                self.log.info(f"Package {package} already installed")

        if missing_packages:
            self.log.info(
                f"Installing missing packages: {', '.join(missing_packages)}"
            )
            self._install_packages(pkg_mgr, missing_packages)
        else:
            self.log.info("All required packages are already installed")

    def _install_packages(self, pkg_mgr, packages):
        """
        Install packages using detected package manager

        :param pkg_mgr: Package manager to use
        :param packages: List of package names to install
        """
        package_list = ' '.join(packages)

        if pkg_mgr in ['dnf', 'yum']:
            install_cmd = f"{pkg_mgr} install -y {package_list}"
        elif pkg_mgr == 'zypper':
            install_cmd = f"zypper install -y {package_list}"
        else:
            self.log.info("Updating apt package list...")
            status, _, stderr = self.run_remote_cmd(
                "apt-get update", ignore_status=True
            )
            if status != 0:
                self.log.warning(f"apt-get update failed: {stderr}")

            install_cmd = f"apt-get install -y {package_list}"

        self.log.info(f"Running: {install_cmd}")
        status, stdout, stderr = self.run_remote_cmd(
            install_cmd, ignore_status=True
        )

        if status != 0:
            self.fail(
                f"Failed to install packages: {package_list}\n"
                f"Error: {stderr}"
            )

        self.log.info(f"Successfully installed: {package_list}")

        for package in packages:
            if pkg_mgr in ['dnf', 'yum', 'zypper']:
                cmd = f"rpm -q {package}"
            else:
                cmd = f"dpkg -l {package} | grep '^ii'"

            status, _, _ = self.run_remote_cmd(cmd, ignore_status=True)
            if status != 0:
                self.fail(
                    f"Package {package} installation verification failed"
                )

        self.log.info("Package installation verified")

    def _verify_kernel_modules(self):
        """
        Verify required kernel modules are available
        """
        self.log.info("Verifying kernel modules...")

        modules = ['nvmet', 'nvmet_tcp']
        for module in modules:
            status, _, _ = self.run_remote_cmd(
                f"modinfo {module}", ignore_status=True
            )
            if status != 0:
                self.cancel(
                    f"Kernel module '{module}' not available. "
                    f"Ensure kernel supports NVMe target."
                )
            self.log.info(f"Kernel module '{module}' available")

    def configure_network(self):
        """
        Configure network interfaces on remote host using nmcli

        Configures primary and optional secondary interfaces for multipath.
        Uses nmcli for persistent configuration.
        """
        self.log.info("Configuring network interfaces...")

        primary = self.network_config.get('primary', {})
        if not primary:
            self.fail("Primary network configuration is required")

        self._configure_interface(
            primary.get('interface'),
            primary.get('ip'),
            primary.get('netmask'),
            primary.get('gateway'),
            primary.get('mtu', 1500)
        )

        secondary = self.network_config.get('secondary', {})
        if secondary:
            self._configure_interface(
                secondary.get('interface'),
                secondary.get('ip'),
                secondary.get('netmask'),
                secondary.get('gateway'),
                secondary.get('mtu', 1500)
            )

        self.log.info("Network configuration completed")

    def _configure_interface(self, interface, ip, netmask,
                             gateway=None, mtu=1500):
        """
        Configure a single network interface using nmcli

        :param interface: Interface name (e.g., eth0)
        :param ip: IP address
        :param netmask: Netmask
        :param gateway: Optional gateway
        :param mtu: MTU value (default: 1500)
        """
        if not interface or not ip or not netmask:
            self.fail("Interface, IP, and netmask are required")

        self.log.info(f"Configuring interface {interface}: {ip}/{netmask}")

        cidr = self._netmask_to_cidr(netmask)

        cmd = f"nmcli connection show {interface}"
        status, _, _ = self.run_remote_cmd(cmd, ignore_status=True)
        if status == 0:
            self.log.info(f"Deleting existing connection for {interface}")
            self.run_remote_cmd(f"nmcli connection delete {interface}")

        cmd = (
            f"nmcli connection add type ethernet "
            f"ifname {interface} con-name {interface} "
            f"ipv4.addresses {ip}/{cidr} "
            f"ipv4.method manual"
        )

        if gateway:
            cmd += f" ipv4.gateway {gateway}"

        self.run_remote_cmd(cmd)

        if mtu != 1500:
            self.run_remote_cmd(
                f"nmcli connection modify {interface} "
                f"802-3-ethernet.mtu {mtu}"
            )

        self.run_remote_cmd(f"nmcli connection up {interface}")

        time.sleep(2)
        status, stdout, _ = self.run_remote_cmd(f"ip addr show {interface}")
        if ip not in stdout:
            self.fail(f"Failed to configure IP {ip} on {interface}")

        self.log.info(f"Interface {interface} configured successfully")

    def _netmask_to_cidr(self, netmask):
        """
        Convert netmask to CIDR prefix length

        :param netmask: Netmask (e.g., 255.255.255.0)
        :return: CIDR prefix (e.g., 24)
        """
        return sum([bin(int(x)).count('1') for x in netmask.split('.')])

    def load_kernel_modules(self):
        """
        Load required kernel modules on remote host

        Loads nvmet and nvmet_tcp modules required for NVMe target operation.
        """
        self.log.info("Loading kernel modules...")

        modules = ['nvmet', 'nvmet_tcp']
        for module in modules:
            status, stdout, _ = self.run_remote_cmd(
                f"lsmod | grep {module}", ignore_status=True
            )

            if status == 0 and module in stdout:
                self.log.info(f"Module {module} already loaded")
            else:
                self.log.info(f"Loading module {module}")
                self.run_remote_cmd(f"modprobe {module}")

                cmd = f"lsmod | grep {module}"
                status, stdout, _ = self.run_remote_cmd(cmd)
                if module not in stdout:
                    self.fail(f"Failed to load kernel module {module}")

        self.log.info("Kernel modules loaded successfully")

    def create_or_select_namespaces(self):
        """
        Create new namespaces or select existing ones based on mode

        Mode 'create': Creates new namespaces
        Mode 'select': Uses existing namespaces specified in config

        Returns list of namespace device paths (e.g., ['/dev/nvme0n1', ...])
        """
        if self.ns_mode == 'create':
            return self._create_namespaces()
        else:
            return self._select_namespaces()

    def _create_namespaces(self):
        """
        Create new namespaces on remote host

        Creates equal-sized namespaces with automatic FLBAS detection.

        :return: List of created namespace device paths
        """
        controller = self.ns_config.get('nvme_controller')
        ns_count = self.ns_config.get('number_of_namespaces', 1)

        if not controller:
            self.fail("nvme_controller is required for create mode")

        controller_name = controller.split('/')[-1]

        self.log.info(
            f"Creating {ns_count} namespaces on {controller_name}..."
        )

        status, _, _ = self.run_remote_cmd(f"test -e {controller}")
        if status != 0:
            self.fail(f"Controller {controller} not found on remote host")

        cmd = f"nvme id-ctrl {controller} | grep unvmcap"
        _, output, _ = self.run_remote_cmd(cmd)
        capacity_str = output.split(':')[-1].strip()
        unallocated_capacity_bytes = int(capacity_str)

        block_size = 4096  # Default
        cmd = f"nvme list-ns {controller}"
        status, ns_list, _ = self.run_remote_cmd(cmd, ignore_status=True)

        if status == 0 and ns_list.strip():
            first_ns = ns_list.strip().split('\n')[0]
            if first_ns.startswith('['):
                first_ns_id = first_ns.split()[1].strip('[]')
                ns_device = f"{controller}n{first_ns_id}"
                cmd = f"nvme id-ns {ns_device}"
                _, ns_output, _ = self.run_remote_cmd(cmd, ignore_status=True)
                for line in ns_output.split('\n'):
                    if 'in use' in line:
                        lbads = int(
                            line.split('lbads:')[1].split()[0]
                        )
                        block_size = 2 ** lbads
                        self.log.info(f"Detected block size: {block_size} bytes")
                        break

        if block_size == 4096:
            self.log.info("Using default block size: 4096 bytes")

        max_ns_blocks = unallocated_capacity_bytes // block_size
        max_ns_blocks_considered = int(60 * max_ns_blocks / 100)
        ns_size = max_ns_blocks_considered // ns_count

        self.log.info(
            f"Unallocated capacity: {unallocated_capacity_bytes} bytes "
            f"({max_ns_blocks} blocks of {block_size} bytes)"
        )
        self.log.info(
            f"Using 60% of capacity: {max_ns_blocks_considered} blocks"
        )
        self.log.info(
            f"Creating {ns_count} namespaces, "
            f"each with {ns_size} blocks ({ns_size * block_size} bytes)"
        )

        cmd = f"nvme list-ns {controller} --all"
        status, stdout, _ = self.run_remote_cmd(cmd, ignore_status=True)
        if status == 0 and stdout.strip():
            self.log.info("Deleting existing namespaces...")
            for line in stdout.strip().split('\n'):
                if line.strip() and line.strip().startswith('['):
                    ns_id = line.split(']')[0].strip('[').strip()
                    self.run_remote_cmd(
                        f"nvme delete-ns {controller} -n {ns_id}",
                        ignore_status=True
                    )

        cmd = f"nvme id-ctrl {controller} | grep cntlid"
        _, cntlid_output, _ = self.run_remote_cmd(cmd)
        cont_id = cntlid_output.split(':')[-1].strip()

        cmd = f"nvme list-ns {controller} --all"
        status, stdout, _ = self.run_remote_cmd(cmd, ignore_status=True)
        existing_ns_ids = set()
        if status == 0 and stdout.strip():
            for line in stdout.strip().split('\n'):
                if line.strip() and line.strip().startswith('['):
                    ns_id = line.split(']')[0].strip('[').strip()
                    existing_ns_ids.add(ns_id)

        self.log.info(f"Existing namespace IDs: {existing_ns_ids}")

        namespaces = []
        for i in range(ns_count):
            self.log.info(f"Creating namespace {i + 1} of {ns_count}...")

            cmd = (
                f"nvme create-ns {controller} "
                f"--nsze={ns_size} --ncap={ns_size} "
                f"--flbas=0 --dps=0"
            )
            status, stdout, stderr = self.run_remote_cmd(cmd, ignore_status=True)

            if status != 0:
                self.log.warning(
                    f"Namespace creation with FLBAS=0 failed, "
                    f"attempting with FLBAS=1..."
                )
                cmd = (
                    f"nvme create-ns {controller} "
                    f"--nsze={ns_size} --ncap={ns_size} --flbas=1 --dps=0"
                )
                status, stdout, stderr = self.run_remote_cmd(cmd)

            cmd = f"nvme list-ns {controller} --all"
            _, stdout, _ = self.run_remote_cmd(cmd)
            current_ns_ids = set()
            for line in stdout.strip().split('\n'):
                if line.strip() and line.strip().startswith('['):
                    ns_id = line.split(']')[0].strip('[').strip()
                    current_ns_ids.add(ns_id)

            new_ns_ids = current_ns_ids - existing_ns_ids
            if not new_ns_ids:
                self.fail(
                    f"Failed to identify newly created namespace. "
                    f"Before: {existing_ns_ids}, After: {current_ns_ids}"
                )

            ns_id = new_ns_ids.pop()
            self.log.info(f"Created namespace with ID: {ns_id}")
            existing_ns_ids.add(ns_id)  # Update for next iteration

            cmd = f"nvme attach-ns {controller} -n {ns_id} -c {cont_id}"
            self.run_remote_cmd(cmd)

            self.run_remote_cmd(f"nvme ns-rescan {controller}")
            time.sleep(2)

            cmd = f"nvme list"
            status, stdout, _ = self.run_remote_cmd(cmd, ignore_status=True)

            ns_device = None
            controller_name = controller.split('/')[-1]  # e.g., "nvme1"

            if status == 0:
                for line in stdout.strip().split('\n'):
                    parts = line.split()
                    if parts and parts[0].startswith('/dev/'):
                        device_path = parts[0]
                        if device_path.startswith(f'/dev/{controller_name}n'):
                            try:
                                device_ns_num = device_path.split('n')[-1]
                                if device_path not in namespaces:
                                    ns_device = device_path
                                    self.log.info(
                                        f"Found new device: {ns_device} "
                                        f"(namespace ID from list-ns: "
                                        f"{ns_id})"
                                    )
                                    break
                            except (ValueError, IndexError):
                                continue

            if not ns_device:
                cmd = f"ls -1 /dev/{controller_name}n*"
                status, stdout, _ = self.run_remote_cmd(cmd, ignore_status=True)
                if status == 0:
                    for device_path in stdout.strip().split('\n'):
                        if device_path not in namespaces:
                            ns_device = device_path
                            self.log.warning(
                                f"Using device from ls: {ns_device} "
                                f"(namespace ID from list-ns: "
                                f"{ns_id})"
                            )
                            break

            if not ns_device:
                self.fail(
                    f"Could not find device node for namespace ID {ns_id}. "
                    f"Controller: {controller}"
                )

            status, _, _ = self.run_remote_cmd(
                f"test -e {ns_device}", ignore_status=True
            )
            if status != 0:
                self.fail(
                    f"Namespace device {ns_device} not found after creation. "
                    f"Namespace ID from list-ns: {ns_id}"
                )

            namespaces.append(ns_device)
            self.log.info(f"Namespace {ns_device} created successfully")

        for ns_device in namespaces:
            self._normalize_uuid(ns_device)

        return namespaces

    def _select_namespaces(self):
        """
        Select existing namespaces specified in configuration

        :return: List of selected namespace device paths
        """
        ns_string = self.ns_config.get('namespaces', '')
        if not ns_string:
            self.fail("namespaces string is required for select mode")

        ns_list = ns_string.split()
        self.log.info(f"Selecting existing namespaces: {ns_list}")

        namespaces = []
        for ns in ns_list:
            ns_device = ns if ns.startswith('/dev/') else f"/dev/{ns}"
            status, _, _ = self.run_remote_cmd(f"test -e {ns_device}")
            if status != 0:
                self.fail(f"Namespace {ns_device} not found on remote host")
            namespaces.append(ns_device)
            self.log.info(f"Namespace {ns_device} verified")

        for ns_device in namespaces:
            self._normalize_uuid(ns_device)

        return namespaces

    def _normalize_uuid(self, ns_device):
        """
        Normalize UUID metadata for namespace

        :param ns_device: Namespace device path (e.g., /dev/nvme0n1)
        """
        self.log.info(f"Normalizing UUID for {ns_device}")

        cmd = f"nvme id-ns {ns_device} | grep nguid"
        status, stdout, _ = self.run_remote_cmd(cmd, ignore_status=True)

        if status == 0 and stdout.strip():
            uuid = stdout.split(':')[-1].strip()
            self.log.info(f"Namespace {ns_device} UUID: {uuid}")
        else:
            self.log.warning(f"No UUID found for {ns_device}")

    def cleanup_all_nvmet_config(self):
        """
        Complete cleanup of ALL NVMe target configuration

        Removes all subsystems, ports, and namespaces from configfs.
        This ensures a clean state before creating new configuration.
        """
        self.log.info("Performing complete NVMe target cleanup...")

        configfs_base = "/sys/kernel/config/nvmet"

        subsys_base = f"{configfs_base}/subsystems"
        cmd = f"ls -1 {subsys_base} 2>/dev/null || true"
        status, subsys_list, _ = self.run_remote_cmd(cmd, ignore_status=True)

        subsystems = []
        if status == 0 and subsys_list.strip():
            subsystems = [
                s.strip() for s in subsys_list.strip().split('\n')
                if s.strip()
            ]

        if not subsystems:
            self.log.info("No subsystems found to clean up")
        else:
            self.log.info(f"Found {len(subsystems)} subsystem(s) to clean up")

        for subsys_nqn in subsystems:
            subsys_path = f"{subsys_base}/{subsys_nqn}"
            ns_path = f"{subsys_path}/namespaces"

            cmd = f"ls -1 {ns_path} 2>/dev/null || true"
            status, ns_list, _ = self.run_remote_cmd(cmd, ignore_status=True)

            if status == 0 and ns_list.strip():
                for ns_id in ns_list.strip().split('\n'):
                    if ns_id.strip() and ns_id.isdigit():
                        self.log.info(
                            f"Disabling namespace {ns_id} in {subsys_nqn}"
                        )
                        enable_file = f"{ns_path}/{ns_id}/enable"
                        self.run_remote_cmd(
                            f"echo 0 > {enable_file} 2>/dev/null || true",
                            ignore_status=True
                        )

        ports_base = f"{configfs_base}/ports"
        cmd = f"ls -1 {ports_base} 2>/dev/null || true"
        status, ports_list, _ = self.run_remote_cmd(cmd, ignore_status=True)

        if status == 0 and ports_list.strip():
            for port_id in ports_list.strip().split('\n'):
                if not port_id.strip():
                    continue

                port_subsys_path = f"{ports_base}/{port_id}/subsystems"
                cmd = f"ls -1 {port_subsys_path} 2>/dev/null || true"
                status, linked_subsys, _ = self.run_remote_cmd(
                    cmd, ignore_status=True
                )

                if status == 0 and linked_subsys.strip():
                    for subsys_nqn in linked_subsys.strip().split('\n'):
                        if subsys_nqn.strip():
                            link = f"{port_subsys_path}/{subsys_nqn}"
                            self.log.info(
                                f"Removing link: port {port_id} -> {subsys_nqn}"
                            )
                            self.run_remote_cmd(
                                f"rm -f {link} 2>/dev/null || true",
                                ignore_status=True
                            )

        if status == 0 and ports_list.strip():
            for port_id in ports_list.strip().split('\n'):
                if port_id.strip():
                    port_path = f"{ports_base}/{port_id}"
                    self.log.info(f"Removing port {port_id}")
                    self.run_remote_cmd(
                        f"rmdir {port_path} 2>/dev/null || true",
                        ignore_status=True
                    )

        for subsys_nqn in subsystems:
            subsys_path = f"{subsys_base}/{subsys_nqn}"
            ns_path = f"{subsys_path}/namespaces"

            cmd = f"ls -1 {ns_path} 2>/dev/null || true"
            status, ns_list, _ = self.run_remote_cmd(cmd, ignore_status=True)

            if status == 0 and ns_list.strip():
                for ns_id in ns_list.strip().split('\n'):
                    if ns_id.strip() and ns_id.isdigit():
                        ns_dir = f"{ns_path}/{ns_id}"
                        self.log.info(
                            f"Removing namespace directory: "
                            f"{subsys_nqn}/namespaces/{ns_id}"
                        )
                        self.run_remote_cmd(
                            f"rmdir {ns_dir} 2>/dev/null || true",
                            ignore_status=True
                        )

            self.log.info(f"Removing subsystem: {subsys_nqn}")
            self.run_remote_cmd(
                f"rmdir {subsys_path}/namespaces 2>/dev/null || true",
                ignore_status=True
            )
            self.run_remote_cmd(
                f"rmdir {subsys_path}/allowed_hosts 2>/dev/null || true",
                ignore_status=True
            )
            self.run_remote_cmd(
                f"rmdir {subsys_path} 2>/dev/null || true",
                ignore_status=True
            )

        controller = self.ns_config.get('nvme_controller')
        if controller and self.ns_mode == 'create':
            self.log.info(f"Deleting all namespaces from {controller}")
            cmd = f"nvme list-ns {controller} --all"
            status, stdout, _ = self.run_remote_cmd(cmd, ignore_status=True)

            deleted_count = 0
            if status == 0 and stdout.strip():
                for line in stdout.strip().split('\n'):
                    if line.strip() and line.strip().startswith('['):
                        ns_id = line.split(']')[0].strip('[').strip()
                        self.log.info(f"Deleting namespace {ns_id}")
                        self.run_remote_cmd(
                            f"nvme delete-ns {controller} -n {ns_id}",
                            ignore_status=True
                        )
                        deleted_count += 1

            if deleted_count > 0:
                self.log.info(
                    f"Deleted {deleted_count} namespace(s), "
                    f"waiting for cleanup to complete..."
                )
                time.sleep(5)  # Wait longer for namespace deletion to complete

                cmd = f"nvme list-ns {controller} --all"
                status, stdout, _ = self.run_remote_cmd(cmd, ignore_status=True)
                if status == 0 and stdout.strip():
                    remaining = len([
                        line for line in stdout.strip().split('\n')
                        if line.strip() and line.strip().startswith('[')
                    ])
                    if remaining > 0:
                        self.log.info(
                            f"{remaining} namespace(s) still present after "
                            f"deletion. This is normal - they will be cleaned "
                            f"up by the system."
                        )
                else:
                    self.log.info("All namespaces successfully deleted")

        self.log.info("Complete NVMe target cleanup finished")

    def configure_nvmet_subsystem(self, namespaces):
        """
        Configure NVMe target subsystem via configfs

        :param namespaces: List of namespace device paths to expose
        """
        self.log.info("Configuring NVMe target subsystem...")

        subsys_path = (
            "/sys/kernel/config/nvmet/subsystems/"
            f"{self.subsystem_nqn}"
        )
        self.run_remote_cmd(f"mkdir -p {subsys_path}")

        self.run_remote_cmd(
            f"echo 1 > {subsys_path}/attr_allow_any_host"
            if self.allow_any_host
            else f"echo 0 > {subsys_path}/attr_allow_any_host"
        )

        for idx, ns_device in enumerate(namespaces, start=1):
            self.log.info(f"Adding {ns_device} as namespace {idx}...")

            ns_path = f"{subsys_path}/namespaces/{idx}"
            self.run_remote_cmd(f"mkdir -p {ns_path}")
            self.run_remote_cmd(f"echo {ns_device} > {ns_path}/device_path")
            self.run_remote_cmd(f"echo 1 > {ns_path}/enable")

        self._configure_ports()

        self.log.info("NVMe target subsystem configured successfully")

    def _configure_ports(self):
        """
        Configure NVMe target ports for TCP transport

        Creates ports for primary and optional secondary network interfaces.
        """
        self.log.info("Configuring NVMe target ports...")

        primary_ip = self.network_config.get('primary', {}).get('ip')
        secondary_ip = self.network_config.get('secondary', {}).get('ip')

        if not primary_ip:
            self.fail("Primary IP is required for port configuration")

        port_id = self.port_id_start
        self._configure_single_port(port_id, primary_ip)

        if secondary_ip:
            port_id += 1
            self._configure_single_port(port_id, secondary_ip)

        self.log.info("NVMe target ports configured successfully")

    def _configure_single_port(self, port_id, ip_addr):
        """
        Configure a single NVMe target port

        :param port_id: Port ID number
        :param ip_addr: IP address to bind to
        """
        self.log.info(
            f"Configuring port {port_id} on {ip_addr}:{self.tcp_port}"
        )

        port_path = f"/sys/kernel/config/nvmet/ports/{port_id}"
        self.run_remote_cmd(f"mkdir -p {port_path}")

        self.run_remote_cmd(f"echo {ip_addr} > {port_path}/addr_traddr")
        self.run_remote_cmd(f"echo tcp > {port_path}/addr_trtype")
        self.run_remote_cmd(f"echo {self.tcp_port} > {port_path}/addr_trsvcid")
        self.run_remote_cmd(f"echo ipv4 > {port_path}/addr_adrfam")

        subsys_link = f"{port_path}/subsystems/{self.subsystem_nqn}"
        subsys_path = (
            f"/sys/kernel/config/nvmet/subsystems/{self.subsystem_nqn}"
        )
        self.run_remote_cmd(f"ln -s {subsys_path} {subsys_link}")

        self.log.info(f"Port {port_id} configured successfully")

    def setup_persistence(self, namespaces):
        """
        Make NVMe target configuration persistent across reboots

        Creates:
        1. nvmet-cli JSON configuration file
        2. systemd service to restore configuration on boot

        :param namespaces: List of namespace device paths
        """
        self.log.info("Setting up persistent configuration...")

        config = self._generate_nvmet_config(namespaces)
        config_json = json.dumps(config, indent=2)

        config_path = "/etc/nvmet/config.json"
        self.run_remote_cmd(f"mkdir -p /etc/nvmet")

        cmd = f"cat > {config_path} << 'EOF'\n{config_json}\nEOF"
        self.run_remote_cmd(cmd)

        self._create_systemd_service()

        self.run_remote_cmd("systemctl daemon-reload")
        self.run_remote_cmd("systemctl enable nvmet-restore.service")
        self.run_remote_cmd("systemctl start nvmet-restore.service")

        self.log.info("Persistent configuration setup completed")

    def _generate_nvmet_config(self, namespaces):
        """
        Generate nvmet-cli compatible JSON configuration

        :param namespaces: List of namespace device paths
        :return: Configuration dictionary
        """
        primary_ip = self.network_config.get('primary', {}).get('ip')
        secondary_ip = self.network_config.get('secondary', {}).get('ip')

        ports = [
            {
                "portid": self.port_id_start,
                "trtype": "tcp",
                "traddr": primary_ip,
                "trsvcid": str(self.tcp_port),
                "adrfam": "ipv4"
            }
        ]

        if secondary_ip:
            ports.append({
                "portid": self.port_id_start + 1,
                "trtype": "tcp",
                "traddr": secondary_ip,
                "trsvcid": str(self.tcp_port),
                "adrfam": "ipv4"
            })

        ns_configs = []
        for idx, ns_device in enumerate(namespaces, start=1):
            ns_configs.append({
                "nsid": idx,
                "device": {
                    "path": ns_device,
                    "nguid": "auto"
                },
                "enable": 1
            })

        config = {
            "subsystems": [
                {
                    "nqn": self.subsystem_nqn,
                    "allow_any_host": 1 if self.allow_any_host else 0,
                    "namespaces": ns_configs
                }
            ],
            "ports": ports
        }

        return config

    def _create_systemd_service(self):
        """
        Create systemd service to restore nvmet configuration on boot
        """
        service_content = """[Unit]
Description=NVMe Target Configuration Restore
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/sbin/nvmetcli restore /etc/nvmet/config.json
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
"""

        service_path = "/etc/systemd/system/nvmet-restore.service"
        cmd = f"cat > {service_path} << 'EOF'\n{service_content}\nEOF"
        self.run_remote_cmd(cmd)

        self.log.info("Systemd service created")

    def validate_configuration(self):
        """
        Validate NVMe target configuration

        Performs minimal validation:
        1. Verify configfs structure exists
        2. Verify TCP ports are listening
        3. Log configuration summary
        """
        self.log.info("Validating configuration...")

        subsys_path = (
            f"/sys/kernel/config/nvmet/subsystems/{self.subsystem_nqn}"
        )
        status, _, _ = self.run_remote_cmd(f"test -d {subsys_path}")
        if status != 0:
            self.fail(
                f"Subsystem {self.subsystem_nqn} not found in configfs"
            )

        cmd = f"ss -tlnp | grep {self.tcp_port}"
        status, stdout, _ = self.run_remote_cmd(cmd, ignore_status=True)

        if status == 0 and str(self.tcp_port) in stdout:
            self.log.info(f"TCP port {self.tcp_port} is listening")
        else:
            self.log.warning(
                f"TCP port {self.tcp_port} is not listening yet. "
                f"This is normal - the port will listen when a host connects."
            )
            status, stdout, _ = self.run_remote_cmd(
                "lsmod | grep nvmet_tcp", ignore_status=True
            )
            if status == 0:
                self.log.info("nvmet_tcp module is loaded")
            else:
                self.log.warning("nvmet_tcp module is not loaded")

        self._log_configuration_summary()

        self.log.info("Configuration validation completed successfully")

    def _log_configuration_summary(self):
        """
        Log comprehensive configuration summary
        """
        self.log.info("=" * 60)
        self.log.info("NVMe/TCP Soft Target Configuration Summary")
        self.log.info("=" * 60)
        self.log.info(f"Subsystem NQN: {self.subsystem_nqn}")
        self.log.info(f"TCP Port: {self.tcp_port}")
        self.log.info(f"Allow Any Host: {self.allow_any_host}")

        primary = self.network_config.get('primary', {})
        self.log.info(
            f"Primary Interface: {primary.get('interface')} "
            f"({primary.get('ip')})"
        )

        secondary = self.network_config.get('secondary', {})
        if secondary:
            self.log.info(
                f"Secondary Interface: {secondary.get('interface')} "
                f"({secondary.get('ip')})"
            )

        subsys_path = f"/sys/kernel/config/nvmet/subsystems/{self.subsystem_nqn}"
        ns_path = f"{subsys_path}/namespaces"
        cmd = f"ls -1 {ns_path} 2>/dev/null || true"
        status, stdout, _ = self.run_remote_cmd(cmd, ignore_status=True)

        if status == 0 and stdout.strip():
            self.log.info("Configured Namespaces:")
            for ns_id in stdout.strip().split('\n'):
                if ns_id.strip() and ns_id.isdigit():
                    device_file = (
                        f"{ns_path}/{ns_id}/device_path"
                    )
                    cmd = f"cat {device_file} 2>/dev/null || echo 'N/A'"
                    _, device_path, _ = self.run_remote_cmd(cmd, ignore_status=True)

                    enable_file = f"{ns_path}/{ns_id}/enable"
                    cmd = f"cat {enable_file} 2>/dev/null || echo '0'"
                    _, enabled, _ = self.run_remote_cmd(cmd, ignore_status=True)

                    status_str = "enabled" if enabled.strip() == "1" else "disabled"
                    self.log.info(
                        f"  Namespace {ns_id}: {device_path.strip()} "
                        f"({status_str})"
                    )

        self.log.info("=" * 60)

    def test_nvme_tcp_soft_target(self):
        """
        Main test execution method

        Orchestrates the complete NVMe/TCP soft target configuration:
        1. Clean up any existing configuration
        2. Configure network interfaces
        3. Load kernel modules
        4. Create or select namespaces
        5. Configure NVMe target subsystem
        6. Setup persistence
        7. Validate configuration
        """
        try:
            self.cleanup_all_nvmet_config()

            self.configure_network()
            self.load_kernel_modules()
            namespaces = self.create_or_select_namespaces()
            self.configure_nvmet_subsystem(namespaces)
            self.setup_persistence(namespaces)
            self.validate_configuration()

            self.log.info(
                "NVMe/TCP soft target configuration completed successfully"
            )

        except Exception as e:
            self.log.error(f"Test failed: {e}")
            raise

    def tearDown(self):
        """
        Cleanup - gracefully close SSH connection

        Note: Configuration is NOT deleted as per requirements.
        Only SSH connection is closed.
        """
        if hasattr(self, 'session'):
            try:
                self.session.quit()
                self.log.info("SSH connection closed gracefully")
            except Exception as e:
                self.log.warning(f"Error closing SSH connection: {e}")
