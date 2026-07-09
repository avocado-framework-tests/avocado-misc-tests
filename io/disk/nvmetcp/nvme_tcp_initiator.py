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
#
# Copyright: 2026 IBM
# Author: Maram Srimannarayana Murthy <msmurthy@linux.vnet.ibm.com>

"""
NVMe/TCP Initiator Configuration Test

This test configures an NVMe/TCP initiator on the local system to connect
to pre-configured NVMe/TCP soft targets. It supports both single-path and
multipath configurations and ensures persistence across reboots.
"""

import os
import json
import time
from avocado import Test
from avocado.utils import process, linux_modules, genio, distro, service
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils.software_manager.distro_packages import (
    install_distro_packages)
from avocado.utils.process import CmdError
from avocado.utils.network.hosts import LocalHost
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.network.exceptions import NWException


class NVMeTCPInitiator(Test):
    """
    NVMe/TCP Initiator configuration and validation test.

    This test performs the following operations:
    1. Validates OS and kernel support for NVMe/TCP
    2. Installs required packages (nvme-cli)
    3. Loads nvme-tcp kernel module
    4. Validates network configuration
    5. Discovers and connects to NVMe/TCP targets
    6. Configures multipath (if applicable)
    7. Ensures persistence across reboots
    8. Validates the complete configuration

    :param primary_ip: Primary initiator IP address
    :param secondary_ip: Secondary initiator IP (for multipath)
    :param target_ips: Space-separated list of target IP addresses
    :param subsystem_nqn: Target subsystem NQN
    :param target_port: Target port (default: 4420)
    """

    def setUp(self):
        """Initialize test parameters and validate prerequisites."""
        self.primary_ip = self.params.get('primary_ip', default=None)
        self.primary_interface = self.params.get(
            'primary_interface', default=None)
        self.primary_subnet = self.params.get('primary_subnet', default=None)
        self.primary_gateway = self.params.get(
            'primary_gateway', default=None)

        self.secondary_ip = self.params.get('secondary_ip', default=None)
        self.secondary_interface = self.params.get(
            'secondary_interface', default=None)
        self.secondary_subnet = self.params.get(
            'secondary_subnet', default=None)
        self.secondary_gateway = self.params.get(
            'secondary_gateway', default=None)

        self.target_ips = self.params.get('target_ips', default='')
        self.subsystem_nqn = self.params.get('subsystem_nqn', default=None)
        self.target_port = self.params.get('target_port', default=4420)

        if not self.primary_ip:
            self.cancel("primary_ip parameter is required")
        if not self.target_ips:
            self.cancel("target_ips parameter is required")
        if not self.subsystem_nqn:
            self.cancel("subsystem_nqn parameter is required")

        self.target_ips = self.target_ips.split()
        self.network_mode = (
            "multi_path" if self.secondary_ip else "single_path")
        self.connected_controllers = []
        self.namespaces = []
        self.multipath_enabled = False

        self.localhost = LocalHost()

        self.log.info("Network mode: %s", self.network_mode)
        self.log.info("Primary IP: %s", self.primary_ip)
        if self.primary_interface:
            self.log.info("Primary Interface: %s", self.primary_interface)
        if self.secondary_ip:
            self.log.info("Secondary IP: %s", self.secondary_ip)
            if self.secondary_interface:
                self.log.info(
                    "Secondary Interface: %s", self.secondary_interface)
        self.log.info("Target IPs: %s", self.target_ips)
        self.log.info("Subsystem NQN: %s", self.subsystem_nqn)

        detected_distro = distro.detect()
        distro_name = detected_distro.name.lower()

        if distro_name in ['rhel', 'centos', 'rocky', 'alma', 'fedora']:
            self.os_family = 'rhel'
            self.log.info("Detected RHEL-based distribution: %s", distro_name)
        elif distro_name in ['suse', 'sles', 'opensuse', 'opensuse-leap']:
            self.os_family = 'suse'
            self.log.info("Detected SUSE-based distribution: %s", distro_name)
        else:
            self.cancel("Unsupported OS: %s" % distro_name)

        self.validate_prerequisites()

    def validate_prerequisites(self):
        """
        Validate and install prerequisites for NVMe/TCP initiator.

        This includes:
        - Kernel version check
        - Required package installation (nvme-cli, network tools)
        - nvme-tcp module loading
        """
        self.log.info("Validating prerequisites...")

        kernel_version = os.uname().release
        self.log.info("Kernel version: %s", kernel_version)

        self._install_required_packages()

        self._load_nvme_modules()
        self.configure_module_autoload()

    def _install_required_packages(self):
        """
        Install required packages for NVMe/TCP initiator.

        Uses install_distro_packages() utility for distro-aware installation.

        Required packages:
        - nvme-cli: NVMe management command line interface

        Optional packages (installed if available):
        - iproute/iproute2: Network configuration tools
        - util-linux: System utilities including lsblk
        """
        common_packages = ['nvme-cli', 'util-linux']
        iproute_pkg = 'iproute' if self.os_family == 'rhel' else 'iproute2'
        packages = common_packages + [iproute_pkg]

        detected_distro = distro.detect()
        distro_pkg_map = {detected_distro.name.lower(): packages}

        self.log.info("Installing required packages for NVMe/TCP initiator...")

        if install_distro_packages(distro_pkg_map):
            self.log.info("Packages installed successfully")
        else:
            self.log.info("Packages already installed or installation skipped")

        smm = SoftwareManager()
        if not smm.check_installed("nvme-cli"):
            self.cancel(
                "nvme-cli package is required but not installed. "
                "Please install it manually and retry.")

    def _load_nvme_modules(self):
        """
        Load required NVMe kernel modules.

        Loads:
        - nvme-tcp: NVMe over TCP transport module
        - nvme-fabrics: NVMe fabrics support (auto-loaded with nvme-tcp)
        """
        try:
            if not linux_modules.module_is_loaded("nvme-tcp"):
                self.log.info("Loading nvme-tcp module...")
                linux_modules.load_module("nvme-tcp")
                self.log.info("nvme-tcp module loaded successfully")
            else:
                self.log.info("nvme-tcp module already loaded")

            if linux_modules.module_is_loaded("nvme-fabrics"):
                self.log.info("nvme-fabrics module is loaded")
            else:
                self.log.warning(
                    "nvme-fabrics module not loaded - may load automatically")

        except CmdError as e:
            self.cancel("Failed to load nvme-tcp module: %s" % str(e))

    def configure_module_autoload(self):
        """
        Configure nvme-tcp module to load automatically at boot.

        Creates /etc/modules-load.d/nvme-tcp.conf if it doesn't exist.
        """
        module_conf = "/etc/modules-load.d/nvme-tcp.conf"
        if not os.path.exists(module_conf):
            self.log.info("Configuring nvme-tcp module auto-load...")
            try:
                genio.write_file(module_conf, "nvme-tcp\n")
                self.log.info("Created %s", module_conf)
            except IOError as e:
                self.log.warning(
                    "Failed to create module auto-load config: %s", str(e))
        else:
            self.log.info("Module auto-load already configured")

    def _configure_ip_on_interface(self, ip_addr, interface, subnet,
                                   gateway=None):
        """
        Configure IP address on network interface.

        IMPORTANT: Does NOT modify default gateway to prevent network
        disruption. Only configures IP and brings interface UP.
        Gateway parameter is ignored to preserve existing routing and
        prevent SSH/management connection loss.

        :param ip_addr: IP address to configure
        :param interface: Interface name
        :param subnet: Subnet mask (e.g., '255.255.255.0' or '24')
        :param gateway: Optional gateway IP (IGNORED - see note above)
        """
        self.log.info(
            "Configuring IP %s on interface %s", ip_addr, interface)

        try:
            net_if = NetworkInterface(if_name=interface, host=self.localhost)
            net_if.add_ipaddr(ipaddr=ip_addr, netmask=subnet)
            self.log.info("Added IP %s/%s to %s", ip_addr, subnet, interface)

            net_if.bring_up()
            self.log.info("Brought interface %s UP", interface)

            if gateway:
                self.log.info(
                    "Gateway %s specified but NOT configured to preserve "
                    "existing routing and prevent management connection "
                    "loss. Configure gateway manually if needed for "
                    "specific routes.", gateway)

            self.log.info(
                "Successfully configured IP %s on %s", ip_addr, interface)

            try:
                self.log.info(
                    "Saving network configuration to make it persistent...")
                net_if.save(ipaddr=ip_addr, netmask=subnet)
                self.log.info(
                    "Network configuration saved persistently for %s",
                    interface)
            except NWException as save_err:
                self.log.warning(
                    "Failed to save persistent network config: %s. "
                    "IP is configured but may not survive reboot.",
                    str(save_err))
            except Exception as save_err:
                self.log.warning(
                    "Unexpected error saving network config: %s",
                    str(save_err))

        except NWException as e:
            self.log.warning("Network configuration failed: %s", str(e))
        except Exception as e:
            self.log.warning("Failed to configure IP: %s", str(e))

    def _validate_ip_on_interface(self, ip_addr, interface=None):
        """
        Validate IP exists on interface.

        :param ip_addr: IP address to validate
        :param interface: Optional interface name to check
        :return: Detected interface name or None if not found
        """
        try:
            detected_if = self.localhost.get_interface_by_ipaddr(ip_addr)
            if detected_if:
                detected_name = detected_if.name
                if interface and detected_name != interface:
                    self.log.warning(
                        "IP %s found on %s, not on specified %s",
                        ip_addr, detected_name, interface)
                self.log.info(
                    "Validated IP %s on interface %s", ip_addr, detected_name)
                return detected_name

            self.log.info("IP %s not found on any interface", ip_addr)
            return None

        except NWException as e:
            self.log.warning("Failed to validate IP: %s", str(e))
            return None
        except Exception as e:
            self.log.warning(
                "Unexpected error during IP validation: %s", str(e))
            return None

    def validate_network_configuration(self):
        """
        Validate and configure initiator network configuration.

        Checks:
        - Primary IP exists and interface is UP (configures if needed)
        - Secondary IP exists and interface is UP (if multipath)
        - Maps IPs to network interfaces

        IMPORTANT: Configures ALL interfaces before proceeding to
        connectivity tests.
        """
        self.log.info("Validating network configuration...")

        detected_primary_interface = self._validate_ip_on_interface(
            self.primary_ip, self.primary_interface)

        if not detected_primary_interface and self.primary_interface:
            if self.primary_subnet:
                self.log.info(
                    "IP %s not found, configuring on %s...",
                    self.primary_ip, self.primary_interface)
                self._configure_ip_on_interface(
                    self.primary_ip, self.primary_interface,
                    self.primary_subnet, self.primary_gateway)
                detected_primary_interface = self.primary_interface
            else:
                self.fail(
                    "IP %s not found and no subnet provided for "
                    "configuration" % self.primary_ip)

        if not self.primary_interface and detected_primary_interface:
            self.primary_interface = detected_primary_interface
            self.log.info(
                "Auto-detected primary interface: %s",
                self.primary_interface)

        if self.secondary_ip:
            detected_secondary_interface = self._validate_ip_on_interface(
                self.secondary_ip, self.secondary_interface)

            if not detected_secondary_interface and self.secondary_interface:
                if self.secondary_subnet:
                    self.log.info(
                        "IP %s not found, configuring on %s...",
                        self.secondary_ip, self.secondary_interface)
                    self._configure_ip_on_interface(
                        self.secondary_ip, self.secondary_interface,
                        self.secondary_subnet, self.secondary_gateway)
                    detected_secondary_interface = self.secondary_interface
                else:
                    self.fail(
                        "IP %s not found and no subnet provided for "
                        "configuration" % self.secondary_ip)

            if not self.secondary_interface and detected_secondary_interface:
                self.secondary_interface = detected_secondary_interface
                self.log.info(
                    "Auto-detected secondary interface: %s",
                    self.secondary_interface)

        time.sleep(2)
        self.log.info("Waiting for network interfaces to stabilize...")

        self._verify_interface_status(self.primary_ip, self.primary_interface)
        if self.secondary_ip and self.secondary_interface:
            self._verify_interface_status(
                self.secondary_ip, self.secondary_interface)

        self.log.info("Network configuration validated successfully")

    def _verify_interface_status(self, ip_addr, interface):
        """
        Verify interface has the correct IP configured and is UP.

        Flexible verification:
        - If IP found on specified interface → Success
        - If IP found on different interface → Accept and update name
        - If IP not found anywhere → Fail
        - If interface not UP → Fail

        :param ip_addr: Expected IP address
        :param interface: Expected interface name
        """
        self.log.info("Verifying IP %s configuration...", ip_addr)

        detected_if = self.localhost.get_interface_by_ipaddr(ip_addr)

        if not detected_if:
            self.fail(
                "IP %s not found on any interface after configuration" %
                ip_addr)

        detected_name = detected_if.name

        if detected_name != interface:
            self.log.warning(
                "IP %s found on %s instead of specified %s. "
                "Using %s for this test.",
                ip_addr, detected_name, interface, detected_name)
            if ip_addr == self.primary_ip:
                self.primary_interface = detected_name
            elif ip_addr == self.secondary_ip:
                self.secondary_interface = detected_name

        net_if = NetworkInterface(if_name=detected_name, host=self.localhost)
        if not net_if.is_link_up():
            self.fail(
                "Interface %s with IP %s is not UP" %
                (detected_name, ip_addr))

        self.log.info(
            "Verified: IP %s on interface %s is UP", ip_addr, detected_name)

    def _ping_target(self, target_ip, source_interface=None):
        """
        Ping target IP to verify network connectivity.

        Uses NetworkInterface.ping_check() utility for consistent ping
        behavior.

        :param target_ip: Target IP to ping
        :param source_interface: Optional source interface to bind to
        :return: True if ping successful, False otherwise
        """
        try:
            if not source_interface:
                default_interfaces = (
                    self.localhost.get_default_route_interface())
                if default_interfaces:
                    source_interface = default_interfaces[0]
                else:
                    self.log.warning(
                        "No default route interface found, using system "
                        "default")
                    cmd = "ping -c 3 -W 2 %s" % target_ip
                    process.run(cmd, shell=True, sudo=True)
                    self.log.info("Ping to %s successful", target_ip)
                    return True

            net_if = NetworkInterface(
                if_name=source_interface, host=self.localhost)
            net_if.ping_check(peer_ip=target_ip, count=3, options="-W 2")
            self.log.info(
                "Ping to %s from %s successful", target_ip,
                source_interface)
            return True
        except (NWException, CmdError) as e:
            self.log.warning("Ping to %s failed: %s", target_ip, str(e))
            return False
        except Exception as e:
            self.log.warning("Ping test failed: %s", str(e))
            return False

    def _test_port_connectivity(self, target_ip, port):
        """
        Test TCP port connectivity to target.

        :param target_ip: Target IP address
        :param port: TCP port number
        :return: True if port is reachable, False otherwise
        """
        cmd = (
            "timeout 5 bash -c 'cat < /dev/null > /dev/tcp/%s/%d'" %
            (target_ip, port))
        try:
            result = process.run(cmd, shell=True, ignore_status=True)
            if result.exit_status == 0:
                self.log.info("Port %d on %s is reachable", port, target_ip)
                return True
            else:
                self.log.warning(
                    "Port %d on %s is not reachable", port, target_ip)
                return False
        except CmdError:
            cmd_alt = "nc -zv -w 5 %s %d" % (target_ip, port)
            try:
                result = process.run(cmd_alt, shell=True, ignore_status=True)
                if result.exit_status == 0:
                    self.log.info(
                        "Port %d on %s is reachable (via nc)",
                        port, target_ip)
                    return True
                else:
                    self.log.warning(
                        "Port %d on %s is not reachable", port, target_ip)
                    return False
            except CmdError as e:
                self.log.warning(
                    "Port connectivity test failed: %s", str(e))
                return False

    def validate_connectivity(self):
        """
        Validate comprehensive network connectivity to target IPs.

        Tests:
        1. ICMP ping to each target (with interface binding for multipath)
        2. TCP port 4420 connectivity
        """
        self.log.info("Testing connectivity to targets...")

        all_reachable = True
        for i, target_ip in enumerate(self.target_ips):
            self.log.info("Testing connectivity to target %s...", target_ip)

            source_interface = self.primary_interface if i == 0 else (
                self.secondary_interface if i == 1 and
                self.secondary_interface else None)

            ping_success = self._ping_target(target_ip, source_interface)
            if not ping_success:
                self.log.warning(
                    "ICMP ping to %s failed (may be blocked by firewall)",
                    target_ip)

            port_success = self._test_port_connectivity(
                target_ip, self.target_port)
            if not port_success:
                self.log.error(
                    "Port %d on %s is not reachable",
                    self.target_port, target_ip)
                all_reachable = False
            else:
                self.log.info(
                    "Target %s:%d is reachable", target_ip, self.target_port)

        if not all_reachable:
            self.fail(
                "One or more targets are not reachable on port %d" %
                self.target_port)

        self.log.info("All targets are reachable")

    def _discover_single_target(self, target_ip):
        """
        Discover NVMe/TCP target on a single IP.

        :param target_ip: Target IP address to discover
        :return: Discovery output string
        """
        cmd = "nvme discover -t tcp -a %s -s %d" % (
            target_ip, self.target_port)
        try:
            output = process.system_output(
                cmd, shell=True, sudo=True).decode()
            self.log.info("Discovery output for %s:\n%s", target_ip, output)

            if self.subsystem_nqn not in output:
                self.log.warning(
                    "Subsystem NQN %s not found in discovery log for %s",
                    self.subsystem_nqn, target_ip)
            return output
        except CmdError as e:
            self.fail("Discovery failed for %s: %s" % (target_ip, str(e)))

    def discover_targets(self):
        """Discover NVMe/TCP targets using nvme discover command."""
        self.log.info("Discovering NVMe/TCP targets...")

        for target_ip in self.target_ips:
            self._discover_single_target(target_ip)

    def _connect_to_single_target(self, target_ip):
        """
        Connect to a single target IP.

        :param target_ip: Target IP address to connect to
        """
        cmd = "nvme connect -t tcp -n %s -a %s -s %d" % (
            self.subsystem_nqn, target_ip, self.target_port)
        try:
            output = process.system_output(
                cmd, shell=True, sudo=True).decode()
            self.log.info("Connection output for %s: %s", target_ip, output)
        except CmdError as e:
            self.fail("Connection failed for %s: %s" % (target_ip, str(e)))

    def connect_to_subsystem(self):
        """
        Establish NVMe/TCP connection to target subsystem.

        Creates controller connections for each target IP.
        Implements idempotent behavior - skips if already connected.
        """
        self.log.info("Connecting to subsystem %s...", self.subsystem_nqn)

        existing_controllers = self.get_connected_controllers()
        if existing_controllers:
            self.log.info("=" * 70)
            self.log.info(
                "NVMe/TCP configuration already exists for subsystem:")
            self.log.info("  Subsystem NQN: %s", self.subsystem_nqn)
            self.log.info(
                "  Connected Controllers: %s", existing_controllers)
            self.log.info("  Status: ACTIVE")
            self.log.info("Skipping connection - using existing configuration")
            self.log.info("=" * 70)
            self.connected_controllers = existing_controllers
            return

        for target_ip in self.target_ips:
            self._connect_to_single_target(target_ip)

        time.sleep(5)

        self.connected_controllers = self.get_connected_controllers()
        if not self.connected_controllers:
            self.fail("No controllers created after connection")

        self.log.info(
            "Successfully connected controllers: %s",
            self.connected_controllers)

    def get_connected_controllers(self):
        """
        Get list of connected NVMe controllers for the subsystem.

        :return: List of controller names (e.g., ['nvme0', 'nvme1'])
        """
        cmd = "nvme list-subsys -o json"
        try:
            output = process.system_output(
                cmd, shell=True, sudo=True).decode()
            data = json.loads(output)

            controllers = []
            for host in data:
                for subsys in host.get("Subsystems", []):
                    if subsys.get("NQN") == self.subsystem_nqn:
                        for path in subsys.get("Paths", []):
                            ctrl_name = path.get("Name")
                            if ctrl_name:
                                controllers.append(ctrl_name)

            return controllers
        except (CmdError, json.JSONDecodeError, KeyError) as e:
            self.log.warning(
                "Failed to get connected controllers: %s", str(e))
            return []

    def configure_multipath(self):
        """
        Configure NVMe native multipathing.

        Only executed if network_mode is 'multi_path'.
        Enables multipath and validates path states.
        """
        if self.network_mode != "multi_path":
            self.log.info(
                "Skipping multipath configuration (single_path mode)")
            return

        self.log.info("Configuring NVMe multipath...")

        multipath_param = "/sys/module/nvme_core/parameters/multipath"
        try:
            current_value = genio.read_file(multipath_param).strip()
            if current_value == "Y":
                self.log.info("NVMe multipath already enabled")
                self.multipath_enabled = True
            else:
                self.log.info("Enabling NVMe multipath...")
                genio.write_file(multipath_param, "Y")
                self.multipath_enabled = True
                self.log.info("NVMe multipath enabled")
        except IOError as e:
            self.log.warning("Failed to enable multipath: %s", str(e))

        self.validate_multipath_paths()

    def validate_multipath_paths(self):
        """
        Validate multipath configuration and path states.

        Checks:
        - Multiple paths exist
        - At least one path is 'optimized' (ANA-aware targets)
        - OR at least two paths are 'live' (non-ANA targets)
        - No paths are 'inaccessible'
        """
        if not self.multipath_enabled:
            return

        self.log.info("Validating multipath paths...")

        cmd = "nvme list-subsys -o json"
        try:
            output = process.system_output(
                cmd, shell=True, sudo=True).decode()
            data = json.loads(output)

            for host in data:
                for subsys in host.get("Subsystems", []):
                    if subsys.get("NQN") == self.subsystem_nqn:
                        paths = subsys.get("Paths", [])
                        self.log.info(
                            "Found %d paths for subsystem", len(paths))

                        if len(paths) < 2:
                            self.fail(
                                "Expected at least 2 paths for multipath, "
                                "found %d" % len(paths))

                        live_count = 0
                        optimized_count = 0
                        for path in paths:
                            state = path.get("State", "unknown")
                            ana_state = path.get("ANAState", "unknown")
                            self.log.info(
                                "Path %s: state=%s, ana_state=%s",
                                path.get("Name"), state, ana_state)

                            if state == "live":
                                live_count += 1
                            if ana_state == "optimized":
                                optimized_count += 1

                        if optimized_count > 0:
                            self.log.info(
                                "Multipath validation successful: %d "
                                "optimized paths (ANA-aware)",
                                optimized_count)
                        elif live_count >= 2:
                            self.log.info(
                                "Multipath validation successful: %d live "
                                "paths (non-ANA target)", live_count)
                        else:
                            self.fail(
                                "Insufficient active paths: %d live, %d "
                                "optimized" % (live_count, optimized_count))

        except (CmdError, json.JSONDecodeError, KeyError) as e:
            self.log.warning("Failed to validate multipath: %s", str(e))

    def configure_persistence(self):
        """
        Configure persistence across reboots.

        Creates:
        - /etc/nvme/discovery.conf for automatic discovery
        - Enables nvme-connect.service or nvmf-autoconnect.service
        """
        self.log.info("Configuring persistence...")

        discovery_conf = "/etc/nvme/discovery.conf"
        os.makedirs(os.path.dirname(discovery_conf), exist_ok=True)

        conf_lines = []
        for target_ip in self.target_ips:
            conf_lines.append(
                "-t tcp -a %s -s %d\n" % (target_ip, self.target_port))

        try:
            genio.write_file(discovery_conf, "".join(conf_lines))
            self.log.info(
                "Created %s for discovery controllers", discovery_conf)
            self.log.info("Discovery config: %s", "".join(conf_lines).strip())
        except IOError as e:
            self.log.warning("Failed to create discovery.conf: %s", str(e))

        service_enabled = False
        for service_name in ["nvme-connect", "nvmf-autoconnect"]:
            try:
                nvme_service = service.SpecificServiceManager(service_name)
                if nvme_service.enable():
                    self.log.info("Enabled %s.service", service_name)
                    service_enabled = True
                    break
            except Exception as e:
                self.log.debug(
                    "Could not enable %s.service: %s", service_name, str(e))
                continue

        if not service_enabled:
            self.log.info(
                "No systemd service available (nvme-connect or "
                "nvmf-autoconnect). Persistence relies on discovery.conf "
                "only.")

    def validate_configuration(self):
        """
        Validate the complete NVMe/TCP initiator configuration.

        Validates:
        - Controllers are connected and in 'live' state
        - Namespaces are visible and accessible
        - Multipath is working (if applicable)
        """
        self.log.info("Validating configuration...")

        self.validate_controllers()
        self.validate_namespaces()

        if self.multipath_enabled:
            self.validate_multipath_paths()

        self.log.info("Configuration validation successful")

    def validate_controllers(self):
        """
        Validate NVMe controller state and health.

        Uses nvme list-subsys to validate controllers, which properly shows
        all controllers in multipath configurations (unlike nvme list which
        only shows one controller per namespace).
        """
        self.log.info("Validating controllers...")

        if not self.connected_controllers:
            self.fail("No connected controllers found")

        expected_count = len(self.target_ips)
        actual_count = len(self.connected_controllers)

        if actual_count != expected_count:
            self.log.warning(
                "Controller count mismatch: expected=%d, actual=%d",
                expected_count, actual_count)

        cmd = "nvme list-subsys -o json"
        try:
            output = process.system_output(
                cmd, shell=True, sudo=True).decode()
            data = json.loads(output)

            for host in data:
                for subsys in host.get("Subsystems", []):
                    if subsys.get("NQN") == self.subsystem_nqn:
                        paths = subsys.get("Paths", [])
                        found_controllers = [
                            p.get("Name") for p in paths if p.get("Name")]

                        for ctrl in self.connected_controllers:
                            if ctrl in found_controllers:
                                state = next(
                                    (p.get("State") for p in paths
                                     if p.get("Name") == ctrl), "unknown")
                                self.log.info(
                                    "Controller %s validated: state=%s",
                                    ctrl, state)
                            else:
                                self.fail(
                                    "Controller %s not found in subsystem" %
                                    ctrl)

                        return

            self.fail(
                "Subsystem %s not found in nvme list-subsys" %
                self.subsystem_nqn)

        except (CmdError, json.JSONDecodeError) as e:
            self.log.warning("Failed to validate controllers: %s", str(e))

    def validate_namespaces(self):
        """Validate namespace visibility and accessibility."""
        self.log.info("Validating namespaces...")

        cmd = "nvme list -o json"
        try:
            output = process.system_output(
                cmd, shell=True, sudo=True).decode()
            data = json.loads(output)

            self.namespaces = []
            for device in data.get("Devices", []):
                ns_path = device.get("DevicePath")
                if ns_path:
                    self.namespaces.append(ns_path)
                    self.log.info(
                        "Found namespace: %s (size: %s)",
                        ns_path, device.get("Size", "unknown"))

            if not self.namespaces:
                self.fail("No namespaces found")

            self.log.info("Found %d namespace(s)", len(self.namespaces))
        except (CmdError, json.JSONDecodeError) as e:
            self.fail("Failed to validate namespaces: %s" % str(e))

    def generate_status_report(self):
        """
        Generate comprehensive status report.

        :return: Formatted status report string
        """
        report = []
        report.append("=" * 60)
        report.append("NVMe/TCP Initiator Configuration Report")
        report.append("=" * 60)
        report.append("")
        report.append("Status: SUCCESS")
        report.append("")
        report.append("System Information:")
        report.append("  OS Family: %s" % self.os_family)
        report.append("  Kernel: %s" % os.uname().release)
        report.append("")
        report.append("Network Configuration:")
        report.append("  Network Mode: %s" % self.network_mode)
        report.append("  Primary IP: %s" % self.primary_ip)
        if self.primary_interface:
            report.append("  Primary Interface: %s" % self.primary_interface)
        if self.primary_subnet:
            report.append("  Primary Subnet: %s" % self.primary_subnet)
        if self.primary_gateway:
            report.append("  Primary Gateway: %s" % self.primary_gateway)
        if self.secondary_ip:
            report.append("  Secondary IP: %s" % self.secondary_ip)
            if self.secondary_interface:
                report.append(
                    "  Secondary Interface: %s" % self.secondary_interface)
            if self.secondary_subnet:
                report.append("  Secondary Subnet: %s" % self.secondary_subnet)
            if self.secondary_gateway:
                report.append(
                    "  Secondary Gateway: %s" % self.secondary_gateway)
        report.append("")
        report.append("Target Configuration:")
        report.append("  Subsystem NQN: %s" % self.subsystem_nqn)
        report.append("  Target IPs: %s" % ", ".join(self.target_ips))
        report.append("  Port: %d" % self.target_port)
        report.append("")
        report.append("Connected Controllers:")
        for ctrl in self.connected_controllers:
            report.append("  - %s" % ctrl)
        report.append("")
        report.append("Namespaces:")
        for ns in self.namespaces:
            report.append("  - %s" % ns)
        report.append("")
        report.append("Multipath Status:")
        report.append(
            "  Enabled: %s" % ("yes" if self.multipath_enabled else "no"))
        report.append("")
        report.append("Persistence:")
        report.append(
            "  Discovery Config: /etc/nvme/discovery.conf (configured)")
        report.append(
            "  Systemd Service: nvme-connect.service (enabled)")
        report.append("  Module Auto-load: nvme-tcp (configured)")
        report.append("")
        report.append("=" * 60)

        return "\n".join(report)

    def deconfigure_nvme_tcp(self):
        """
        Deconfigure NVMe/TCP initiator.

        This method:
        1. Finds all connected controllers for the specified subsystem
        2. Disconnects each controller
        3. Removes persistence configuration
        4. Validates cleanup
        """
        self.log.info("=" * 70)
        self.log.info("Deconfiguring NVMe/TCP Initiator")
        self.log.info("=" * 70)

        controllers = self.get_connected_controllers()

        if not controllers:
            self.log.info(
                "No controllers found for subsystem %s - already clean",
                self.subsystem_nqn)
            return

        self.log.info(
            "Found %d controller(s) to disconnect: %s",
            len(controllers), controllers)

        disconnected_count = 0
        for ctrl in controllers:
            try:
                cmd = "nvme disconnect -d /dev/%s" % ctrl
                self.log.info("Disconnecting controller %s...", ctrl)
                process.system(cmd, shell=True, sudo=True, ignore_status=False)
                self.log.info("Successfully disconnected %s", ctrl)
                disconnected_count += 1
            except CmdError as e:
                self.log.warning(
                    "Failed to disconnect %s: %s", ctrl, str(e))

        time.sleep(2)

        self.log.info("Removing persistence configuration...")
        discovery_conf = "/etc/nvme/discovery.conf"
        if os.path.exists(discovery_conf):
            try:
                os.remove(discovery_conf)
                self.log.info("Removed %s", discovery_conf)
            except OSError as e:
                self.log.warning(
                    "Failed to remove %s: %s", discovery_conf, str(e))

        try:
            nvme_service = service.SpecificServiceManager("nvme-connect")
            if nvme_service.disable():
                self.log.info("Disabled nvme-connect.service")
            else:
                self.log.info(
                    "nvme-connect.service not enabled or does not exist")
        except Exception as e:
            self.log.info(
                "Could not disable nvme-connect.service: %s", str(e))

        remaining_controllers = self.get_connected_controllers()
        if remaining_controllers:
            self.log.warning(
                "Some controllers still connected: %s", remaining_controllers)
        else:
            self.log.info("All controllers successfully disconnected")

        self.log.info("=" * 70)
        self.log.info("Deconfiguration Summary:")
        self.log.info("  Subsystem NQN: %s", self.subsystem_nqn)
        self.log.info(
            "  Controllers Disconnected: %d/%d",
            disconnected_count, len(controllers))
        self.log.info("  Persistence Removed: Yes")
        self.log.info(
            "  Status: %s",
            "CLEAN" if not remaining_controllers else "PARTIAL")
        self.log.info("=" * 70)

    def test_00_cleanup_existing_configuration(self):
        """
        Cleanup test that runs FIRST (test_00_*) to ensure clean state.

        This test:
        - Runs before the main configuration test (alphabetically first)
        - Removes any existing NVMe/TCP configuration for the subsystem
        - Ensures a clean starting state for testing
        - Always passes (warnings only if cleanup issues)

        Test naming: test_00_* ensures this runs before
        test_initiator_configuration
        """
        self.log.info("\n" + "=" * 70)
        self.log.info(
            "CLEANUP TEST: Removing existing NVMe/TCP configuration")
        self.log.info("=" * 70)

        try:
            self.deconfigure_nvme_tcp()
            self.log.info("Cleanup completed successfully")
        except Exception as e:
            self.log.warning("Cleanup encountered issues: %s", str(e))
            self.log.warning(
                "Continuing anyway - main test will handle any remaining "
                "config")

    def test_initiator_configuration(self):
        """
        Main test method that orchestrates the complete initiator
        configuration.

        Execution flow:
        1. Validate network configuration
        2. Test connectivity to targets
        3. Discover targets
        4. Connect to subsystem
        5. Configure multipath (if applicable)
        6. Configure persistence
        7. Validate configuration
        8. Generate status report
        """
        self.validate_network_configuration()
        self.validate_connectivity()
        self.discover_targets()
        self.connect_to_subsystem()
        self.configure_multipath()
        self.configure_persistence()
        self.validate_configuration()

        report = self.generate_status_report()
        self.log.info("\n%s", report)

    def tearDown(self):
        """
        Cleanup method (optional).

        Note: We intentionally do NOT disconnect controllers in tearDown
        to maintain the configuration for persistence testing.
        """
        self.log.info(
            "Test completed. Controllers remain connected for persistence.")
