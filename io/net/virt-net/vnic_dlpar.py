#!/usr/bin/env python3

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
# Author: Shaik Abdulla <shaik.abdulla1@ibm.com>

"""
vNIC DLPAR operations — regular DLPAR and lockdown-protected DLPAR.

Assumptions:
  - The vNIC is already added to the LPAR manually by the user before
    running any test. This script does NOT add the vNIC itself.
  - Backend traffic (ping) is checked after every add/remove cycle to
    confirm connectivity is restored.

Lockdown helpers use avocado.utils.linux:
  linux.is_kernel_lockdown_enabled()          -> (mode, is_enabled)
  linux.enable_kernel_lockdown_integrity()    -> bool
  linux.enable_kernel_lockdown_confidentiality() -> bool
"""

import netifaces
from avocado import Test
from avocado import skipIf, skipUnless
from avocado.utils import process
from avocado.utils import distro
from avocado.utils import dmesg
from avocado.utils import wait
from avocado.utils import linux
from avocado.utils.process import CmdError
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.network.hosts import LocalHost
from avocado.utils.ssh import Session
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils.software_manager.distro_packages import (
    install_distro_packages)

IS_POWER_NV = 'PowerNV' in open('/proc/cpuinfo', 'r').read()
IS_KVM_GUEST = 'qemu' in open('/proc/cpuinfo', 'r').read()


class VnicDlpar(Test):
    """
    vNIC DLPAR test — performs drmgr-based (OS-level) hot remove / add
    cycles on a pre-provisioned vNIC interface.

    Optionally enables kernel lockdown (integrity or confidentiality) before
    running the DLPAR cycle and restores the original state in tearDown.

    Lockdown state is queried and set via avocado.utils.linux:
      linux.is_kernel_lockdown_enabled()
      linux.enable_kernel_lockdown_integrity()
      linux.enable_kernel_lockdown_confidentiality()

    Update vnic_dlpar.yaml with site-specific values before running.

    :avocado: tags=net,io,privileged,pSeries,ppc64le
    """

    @skipUnless("ppc" in distro.detect().arch,
                "supported only on Power platform")
    @skipIf(IS_POWER_NV or IS_KVM_GUEST,
            "This test is not supported on KVM guest or PowerNV platform")
    def setUp(self):
        """
        Gather necessary test inputs and validate the environment.
        The vNIC must already exist on the LPAR before running this test.
        """
        self.session_hmc = None
        self.original_lockdown_state = None
        self.install_packages()
        self.rsct_service_start()

        # --- HMC connectivity ---
        self.hmc_ip = wait.wait_for(
            lambda: self.get_mcp_component("HMCIPAddr"), timeout=30)
        if not self.hmc_ip:
            self.cancel("HMC IP not got")
        self.hmc_username = self.params.get("hmc_username", default=None)
        self.hmc_pwd = self.params.get("hmc_pwd", default=None)
        self.lpar = self.get_partition_name("Partition Name")
        if not self.lpar:
            self.cancel("LPAR Name not got from lparstat command")
        self.session_hmc = Session(self.hmc_ip, user=self.hmc_username,
                                   password=self.hmc_pwd)
        self.session_hmc.cleanup_master()
        if not self.session_hmc.connect():
            self.cancel("failed connecting to HMC")

        # --- Managed system and LPAR id ---
        self.server = self.params.get("manageSystem", default=None)
        if not self.server:
            self.cancel("Managed System not got")
        cmd = ('lssyscfg -m %s -r lpar --filter lpar_names=%s -F lpar_id'
               % (self.server, self.lpar))
        self.lpar_id = self.session_hmc.cmd(cmd).stdout_text.split()[0]

        # --- vNIC slot / interface details ---
        self.slot_num = str(self.params.get(
            "slot_num", default=None)).split(' ')
        for slot in self.slot_num:
            if int(slot) < 3 or int(slot) > 2999:
                self.cancel("Slot invalid. Valid range: 3 - 2999")
        self.mac_id = self.params.get(
            "mac_id", default="02:03:03:03:03:01").split(' ')
        self.mac_id = [mac.replace(':', '') for mac in self.mac_id]
        self.device_ip = self.params.get('device_ip', default=None).split(' ')
        self.netmask = self.params.get('netmasks', default=None).split(' ')
        self.peer_ip = self.params.get('peer_ip', default=None).split(' ')
        self.num_of_dlpar = int(self.params.get("num_of_dlpar", default='1'))

        # --- Backing device info ---
        self.sriov_port = self.params.get(
            "sriov_ports", default=None).split(' ')
        self.backing_adapter = self.params.get(
            "sriov_adapters", default=None).split(' ')
        cmd = ('lshwres -m %s -r sriov --rsubtype adapter -F '
               'phys_loc:adapter_id' % self.server)
        adapter_id_output = self.session_hmc.cmd(cmd).stdout_text
        self.backing_adapter_id = []
        for backing_adapter in self.backing_adapter:
            for line in adapter_id_output.splitlines():
                if str(backing_adapter) in line:
                    self.backing_adapter_id.append(line.split(':')[1])
        if not self.backing_adapter_id:
            self.cancel("SRIOV adapter provided was not found.")

        self.local = LocalHost()
        dmesg.clear_dmesg()

        # --- Lockdown configuration ---
        # Uses linux.is_kernel_lockdown_enabled() / enable_kernel_lockdown_*()
        # from avocado.utils.linux instead of custom sysfs writes.
        self.lockdown_mode = self.params.get(
            "lockdown_mode", default="integrity")
        self.lockdown_enable = self.params.get(
            "lockdown_enable", default=False)
        # Save original state so tearDown can restore it.
        self.original_lockdown_state, _ = linux.is_kernel_lockdown_enabled()

        if self.lockdown_enable is True:
            if self.original_lockdown_state is None:
                self.cancel("Kernel lockdown not supported on this system")
            if self.original_lockdown_state == "none":
                if not self._enable_lockdown(self.lockdown_mode):
                    self.fail(
                        "Failed to enable kernel lockdown "
                        "(%s)" % self.lockdown_mode)
        else:
            self.log.info(
                "Running vNIC DLPAR test without lockdown enabled")

    # ------------------------------------------------------------------ #
    #  Static helpers                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def get_mcp_component(component):
        """
        Probes IBM.MCP class for mentioned component and returns it.
        """
        for line in process.system_output(
                'lsrsrc IBM.MCP %s' % component,
                ignore_status=True, shell=True,
                sudo=True).decode("utf-8").splitlines():
            if component in line:
                return line.split()[-1].strip('{}\"')
        return ''

    @staticmethod
    def get_partition_name(component):
        """
        Get partition name from lparstat -i.
        """
        for line in process.system_output(
                'lparstat -i', ignore_status=True, shell=True,
                sudo=True).decode("utf-8").splitlines():
            if component in line:
                return line.split(':')[-1].strip()
        return ''

    @staticmethod
    def find_device(mac_addrs):
        """
        Find the network interface name matching the given 12-char MAC
        (no colons).
        """
        mac = ':'.join(mac_addrs[i:i+2] for i in range(0, 12, 2))
        for device in netifaces.interfaces():
            addrs = netifaces.ifaddresses(device)
            if 17 in addrs and mac in addrs[17][0]['addr']:
                return device
        return ''

    # ------------------------------------------------------------------ #
    #  Package / service helpers                                          #
    # ------------------------------------------------------------------ #

    def install_packages(self):
        """
        Install packages required by the test using
        install_distro_packages() from
        avocado.utils.software_manager.distro_packages.
        """
        detected_distro = distro.detect()
        self.log.info("Test is running on: %s", detected_distro.name)
        base_pkgs = ['ksh', 'src', 'rsct.basic', 'rsct.core.utils',
                     'rsct.core', 'DynamicRM', 'powerpc-utils']
        ubuntu_pkgs = base_pkgs + ['python-paramiko']
        distro_pkg_map = {
            'rhel': base_pkgs,
            'SuSE': base_pkgs,
            'Ubuntu': ubuntu_pkgs,
        }
        install_distro_packages(distro_pkg_map)
        smm = SoftwareManager()
        for pkg in base_pkgs:
            if not smm.check_installed(pkg):
                self.cancel(
                    '%s is needed for the test to be run' % pkg)

    def rsct_service_start(self):
        """
        Start rsct services required for DLPAR operations.
        """
        try:
            process.run("startsrc -g rsct", shell=True, sudo=True)
        except CmdError as details:
            self.log.debug(str(details))
            self.cancel("Command startsrc -g rsct failed")
        try:
            process.run("startsrc -g rsct_rm", shell=True, sudo=True)
        except CmdError as details:
            self.log.debug(str(details))
            self.cancel("Command startsrc -g rsct_rm failed")
        output = process.system_output(
            "lssrc -a", ignore_status=True, shell=True, sudo=True)
        if "inoperative" in output.decode("utf-8"):
            self.cancel("Failed to start the rsct and rsct_rm services")

    # ------------------------------------------------------------------ #
    #  Lockdown helpers — thin wrappers over avocado.utils.linux          #
    # ------------------------------------------------------------------ #

    def _enable_lockdown(self, mode):
        """
        Enable kernel lockdown to *mode* using avocado.utils.linux APIs.

        :param mode: 'integrity' or 'confidentiality'
        :return: True on success, False otherwise.
        """
        if mode == "integrity":
            result = linux.enable_kernel_lockdown_integrity()
        elif mode == "confidentiality":
            result = linux.enable_kernel_lockdown_confidentiality()
        else:
            self.log.error("Unknown lockdown mode: %s", mode)
            return False
        current, _ = linux.is_kernel_lockdown_enabled()
        self.log.info("Lockdown state after enable: %s", current)
        return result

    def _restore_lockdown(self, original_mode):
        """
        Restore lockdown to *original_mode*.
        Note: the kernel only allows escalation
        (none->integrity->confidentiality).
        Downgrade (e.g. integrity->none) is not possible at runtime
        without a reboot; this method logs a warning in that case.
        """
        current_mode, _ = linux.is_kernel_lockdown_enabled()
        if current_mode == original_mode:
            return
        if original_mode == "none":
            self.log.warn(
                "Cannot downgrade lockdown from '%s' to 'none' without "
                "reboot. Manual restore required.", current_mode)
        else:
            self._enable_lockdown(original_mode)

    # ------------------------------------------------------------------ #
    #  DLPAR primitives                                                   #
    # ------------------------------------------------------------------ #

    def find_device_id(self, mac):
        """
        Return the kernel device-tree ID for the interface with given MAC.
        """
        device = self.find_device(mac)
        if not device:
            self.fail("No network interface found for MAC %s" % mac)
        return process.system_output(
            "ls -l /sys/class/net/ | grep -w %s | cut -d '/' -f 5" % device,
            shell=True).decode("utf-8").strip()

    def find_virtual_slot(self, dev_id):
        """
        Return the virtual slot path for the given device-tree ID via lsslot.
        """
        if not dev_id:
            return False
        output = process.system_output(
            "lsslot", ignore_status=True, shell=True, sudo=True)
        for slot in output.decode("utf-8").splitlines():
            if slot.startswith('#'):
                continue
            if dev_id in slot:
                return slot.split()[0]
        return False

    def drmgr_vnic_dlpar(self, operation, slot):
        """
        Perform OS-level drmgr add (-a) or remove (-r) on the given slot.
        """
        cmd = 'drmgr %s -c slot -s %s -w 5 -d 1' % (operation, slot)
        if process.system(cmd, shell=True, sudo=True, ignore_status=True):
            self.fail("drmgr operation %s failed for vNIC slot %s"
                      % (operation, slot))

    def wait_intrerface(self, device_name):
        """
        Poll until the named interface reappears in the OS (up to 120 s).
        Uses NetworkInterface.is_available() from
        avocado.utils.network.interfaces and wait.wait_for() from
        avocado.utils.wait.
        """
        networkinterface = NetworkInterface(device_name, self.local)
        result = wait.wait_for(
            networkinterface.is_available, timeout=120,
            text="Waiting for vNIC %s to come up" % device_name)
        if result:
            self.log.info("vNIC device %s is up", device_name)
        return bool(result)

    def check_dmesg_error(self):
        """
        Fail the test if unexpected kernel errors appear in dmesg.
        Uses dmesg.collect_errors_by_level() from avocado.utils.dmesg.
        """
        skip_errors = [
            'uevent: failed to send synthetic uevent',
            'Invalid request detected while CRQ is inactive',
            'failed to send uevent',
            'registration failed',
            'CRQ-init failed, -11',
        ]
        self.log.info("Checking dmesg for kernel errors")
        try:
            dmesg.collect_errors_by_level(
                level_check=4, skip_errors=skip_errors)
        except Exception as exc:
            self.log.debug(str(exc))
            self.fail("Kernel errors detected — check dmesg in debug log")

    def _verify_traffic(self, networkinterface, device_ip, netmask, peer_ip):
        """
        Configure IP on networkinterface and ping peer to verify
        backend traffic is restored after a DLPAR cycle.
        Uses NetworkInterface from avocado.utils.network.interfaces and
        wait.wait_for() from avocado.utils.wait.
        """
        try:
            networkinterface.add_ipaddr(device_ip, netmask)
        except Exception as exc:
            self.log.debug("add_ipaddr failed (%s), falling back to save", exc)
            networkinterface.save(device_ip, netmask)
        if not wait.wait_for(networkinterface.is_link_up, timeout=120):
            self.fail("Unable to bring up link on vNIC after DLPAR")
        if networkinterface.ping_check(peer_ip, count=5) is not None:
            self.fail("Backend traffic check failed after DLPAR — "
                      "ping to %s failed" % peer_ip)

    # ------------------------------------------------------------------ #
    #  Test cases                                                         #
    # ------------------------------------------------------------------ #

    def test_vnic_dlpar(self):
        """
        Regular vNIC DLPAR: drmgr-based hot remove and hot add.
        Verifies backend traffic with ping after each cycle.
        vNIC must already exist on the LPAR before running this test.
        """
        for _, device_ip, netmask, mac, peer_ip in zip(
                self.slot_num, self.device_ip,
                self.netmask, self.mac_id, self.peer_ip):
            dev_id = self.find_device_id(mac)
            device_name = self.find_device(mac)
            slot = self.find_virtual_slot(dev_id)
            if not slot:
                self.fail("Virtual slot not found for MAC %s" % mac)
            try:
                for _ in range(self.num_of_dlpar):
                    self.drmgr_vnic_dlpar('-r', slot)
                    self.drmgr_vnic_dlpar('-a', slot)
                    self.wait_intrerface(device_name)
            except CmdError as details:
                self.log.debug(str(details))
                self.fail("drmgr DLPAR operation did not complete")
            networkinterface = NetworkInterface(
                self.find_device(mac), self.local)
            self._verify_traffic(
                networkinterface, device_ip, netmask, peer_ip)
        self.check_dmesg_error()

    def test_vnic_dlpar_lockdown(self):
        """
        vNIC DLPAR under kernel lockdown.

        1. Queries lockdown state via linux.is_kernel_lockdown_enabled().
        2. Enables lockdown using linux.enable_kernel_lockdown_integrity()
           or linux.enable_kernel_lockdown_confidentiality() as configured.
        3. Runs the same drmgr remove/add cycles as test_vnic_dlpar.
        4. Verifies backend traffic (ping) after every cycle.
        5. tearDown restores the original lockdown state where possible.
        """
        current_mode, _ = linux.is_kernel_lockdown_enabled()
        if current_mode is None:
            self.cancel(
                "Kernel lockdown not supported — skipping lockdown test")

        self.log.info("Lockdown state at test start: %s", current_mode)

        # Ensure the requested lockdown mode is active for this test.
        if current_mode != self.lockdown_mode:
            if not self._enable_lockdown(self.lockdown_mode):
                self.fail("Could not enable kernel lockdown "
                          "(%s)" % self.lockdown_mode)

        active_mode, _ = linux.is_kernel_lockdown_enabled()
        self.log.info("Running vNIC DLPAR with lockdown mode: %s", active_mode)

        for _, device_ip, netmask, mac, peer_ip in zip(
                self.slot_num, self.device_ip,
                self.netmask, self.mac_id, self.peer_ip):
            dev_id = self.find_device_id(mac)
            device_name = self.find_device(mac)
            slot = self.find_virtual_slot(dev_id)
            if not slot:
                self.fail("Virtual slot not found for MAC %s" % mac)
            try:
                for _ in range(self.num_of_dlpar):
                    self.drmgr_vnic_dlpar('-r', slot)
                    self.drmgr_vnic_dlpar('-a', slot)
                    self.wait_intrerface(device_name)
            except CmdError as details:
                self.log.debug(str(details))
                self.fail("drmgr DLPAR operation failed under lockdown")
            networkinterface = NetworkInterface(
                self.find_device(mac), self.local)
            self._verify_traffic(
                networkinterface, device_ip, netmask, peer_ip)

        self.check_dmesg_error()

    # ------------------------------------------------------------------ #
    #  Cleanup                                                            #
    # ------------------------------------------------------------------ #

    def tearDown(self):
        """
        Restore lockdown state and close HMC session.
        Guards against AttributeError if setUp cancelled early.
        """
        if self.original_lockdown_state is not None:
            self._restore_lockdown(self.original_lockdown_state)
        if self.session_hmc:
            self.session_hmc.quit()
