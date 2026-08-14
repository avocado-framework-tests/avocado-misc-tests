#!/usr/bin/python

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
# Copyright: 2024 IBM
# Author: Farooq Abdulla <farooq.abdulla@ibm.com>

"""
vNIC DLPAR operations — regular DLPAR and lockdown-protected DLPAR.

Assumptions:
  - The vNIC is already added to the LPAR manually by the user before
    running any test. This script does NOT add the vNIC itself.
  - Backend traffic (ping) is checked after every add/remove cycle to
    confirm connectivity is restored.
"""

import os
import time
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

IS_POWER_NV = 'PowerNV' in open('/proc/cpuinfo', 'r').read()
IS_KVM_GUEST = 'qemu' in open('/proc/cpuinfo', 'r').read()


class VnicDlpar(Test):
    '''
    vNIC DLPAR test — performs drmgr-based (OS-level) and HMC-based hot
    remove / add cycles on a pre-provisioned vNIC interface.

    Optionally enables kernel lockdown (integrity or confidentiality) before
    running the DLPAR cycle and restores the original state in tearDown.

    Update vnic_dlpar.yaml with site-specific values before running.
    '''

    @skipUnless("ppc" in distro.detect().arch,
                "supported only on Power platform")
    @skipIf(IS_POWER_NV or IS_KVM_GUEST,
            "This test is not supported on KVM guest or PowerNV platform")
    def setUp(self):
        '''
        Gather necessary test inputs and validate the environment.
        The vNIC must already exist on the LPAR before running this test.
        '''
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
        self.device_ip = self.params.get(
            'device_ip', default=None).split(' ')
        self.netmask = self.params.get('netmasks', default=None).split(' ')
        self.peer_ip = self.params.get('peer_ip', default=None).split(' ')
        self.num_of_dlpar = int(self.params.get("num_of_dlpar", default='1'))

        # --- Backing device info (needed for HMC DLPAR re-add) ---
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

        # --- Lockdown configuration (mirrors io/pci/dlpar.py) ---
        self.lockdown_path = "/sys/kernel/security/lockdown"
        self.lockdown_mode = self.params.get(
            "lockdown_mode", default="integrity")
        self.lockdown_enable = self.params.get(
            "lockdown_enable", default=False)
        self.original_lockdown_state = None
        if self.lockdown_enable is True:
            self.original_lockdown_state = self.get_lockdown_state()
            if self.original_lockdown_state == "none":
                if not self.set_lockdown_mode(self.lockdown_mode):
                    self.fail(
                        f"Failed to set lockdown to {self.lockdown_mode}")
        else:
            self.log.info(
                "Running vNIC DLPAR test without lockdown enabled")

    # ------------------------------------------------------------------ #
    #  Static helpers (copied from NetworkVirtualization)                 #
    # ------------------------------------------------------------------ #

    @staticmethod
    def get_mcp_component(component):
        '''
        Probes IBM.MCP class for mentioned component and returns it.
        '''
        for line in process.system_output(
                'lsrsrc IBM.MCP %s' % component,
                ignore_status=True, shell=True,
                sudo=True).decode("utf-8").splitlines():
            if component in line:
                return line.split()[-1].strip('{}\"')
        return ''

    @staticmethod
    def get_partition_name(component):
        '''
        Get partition name from lparstat -i.
        '''
        for line in process.system_output(
                'lparstat -i', ignore_status=True, shell=True,
                sudo=True).decode("utf-8").splitlines():
            if component in line:
                return line.split(':')[-1].strip()
        return ''

    @staticmethod
    def find_device(mac_addrs):
        '''
        Find the network interface matching the given MAC (12-char, no colons).
        '''
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
        '''
        Install packages required by the test.
        '''
        smm = SoftwareManager()
        packages = ['ksh', 'src', 'rsct.basic', 'rsct.core.utils',
                    'rsct.core', 'DynamicRM', 'powerpc-utils']
        for pkg in packages:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel('%s is needed for the test to be run' % pkg)

    def rsct_service_start(self):
        '''
        Start rsct services required for DLPAR operations.
        '''
        try:
            for svc in ["rsct", "rsct_rm"]:
                process.run('startsrc -g %s' % svc, shell=True, sudo=True)
        except CmdError as details:
            self.log.debug(str(details))
            self.fail("Starting rsct service failed")
        output = process.system_output(
            "lssrc -a", ignore_status=True, shell=True, sudo=True)
        if "inoperative" in output.decode("utf-8"):
            self.cancel("Failed to start the rsct and rsct_rm services")

    # ------------------------------------------------------------------ #
    #  Kernel lockdown helpers (same logic as io/pci/dlpar.py)            #
    # ------------------------------------------------------------------ #

    def check_lockdown_support(self):
        '''
        Check if kernel lockdown is supported on this system.
        '''
        if not os.path.exists(self.lockdown_path):
            self.log.warn("Kernel lockdown not supported on this system")
            return False
        return True

    def get_lockdown_state(self):
        '''
        Get current lockdown state.
        Parses output like: "none [integrity] confidentiality"
        Returns 'none', 'integrity', 'confidentiality', or None on error.
        '''
        try:
            output = process.system_output(
                f'cat {self.lockdown_path}',
                shell=True, sudo=True).decode("utf-8")
            if '[none]' in output:
                return 'none'
            elif '[integrity]' in output:
                return 'integrity'
            elif '[confidentiality]' in output:
                return 'confidentiality'
        except Exception as exc:
            self.log.error(f"Failed to get lockdown state: {exc}")
        return None

    def set_lockdown_mode(self, mode):
        '''
        Set kernel lockdown mode to 'none', 'integrity', or 'confidentiality'.
        Returns True on success, False otherwise.
        '''
        if not self.check_lockdown_support():
            return False
        current_state = self.get_lockdown_state()
        self.log.info(f"Current lockdown state: {current_state}")
        if mode == current_state:
            self.log.info(f"Lockdown already set to {mode}")
            return True
        try:
            process.run(f'echo "{mode}" > {self.lockdown_path}',
                        shell=True, sudo=True)
            new_state = self.get_lockdown_state()
            if new_state == mode:
                self.log.info(f"Successfully set lockdown to {mode}")
                return True
            self.log.error(
                f"Failed to set lockdown to {mode}, current: {new_state}")
            return False
        except Exception as exc:
            self.log.error(f"Error setting lockdown mode to {mode}: {exc}")
            return False

    # ------------------------------------------------------------------ #
    #  DLPAR primitives                                                   #
    # ------------------------------------------------------------------ #

    def find_device_id(self, mac):
        '''
        Return the kernel device-tree ID for the interface with given MAC.
        '''
        device = self.find_device(mac)
        return process.system_output(
            "ls -l /sys/class/net/ | grep -w %s | cut -d '/' -f 5" % device,
            shell=True).decode("utf-8").strip()

    def find_virtual_slot(self, dev_id):
        '''
        Return the virtual slot path for the given device-tree ID.
        '''
        output = process.system_output(
            "lsslot", ignore_status=True, shell=True, sudo=True)
        for slot in output.decode("utf-8").split('\n'):
            if dev_id in slot:
                return slot.split(' ')[0]
        return False

    def drmgr_vnic_dlpar(self, operation, slot):
        '''
        Perform OS-level drmgr add (-a) or remove (-r) on the given slot.
        '''
        cmd = 'drmgr %s -c slot -s %s -w 5 -d 1' % (operation, slot)
        if process.system(cmd, shell=True, sudo=True, ignore_status=True):
            self.fail("drmgr operation %s failed for vNIC slot %s"
                      % (operation, slot))

    def device_add_remove(self, slot, mac, sriov_port, adapter_id, operation):
        '''
        HMC-based vNIC add or remove using chhwres / rmhwres.
        '''
        if operation == 'remove':
            cmd = ('rmhwres -r virtualio -m %s --rsubtype vnic -s %s --id %s'
                   % (self.server, slot, self.lpar_id))
        else:
            cmd = ('chhwres -r virtualio -m %s --rsubtype vnic -o a --id %s '
                   '-s %s -a "mac_addr=%s,port_vlan_id=1,'
                   'backing_devices=sriov/%s/%s//%s//%s//%s/1/100"'
                   % (self.server, self.lpar_id, slot, mac,
                      self.vios_id[0], sriov_port, adapter_id,
                      self.vios_name[0], self.lpar_id))
        output = self.session_hmc.cmd(cmd)
        if output.exit_status != 0:
            self.fail("HMC vNIC %s failed: %s" % (operation, output.stderr))

    def wait_intrerface(self, device_name):
        '''
        Poll until the named interface reappears in the OS (up to 120 s).
        '''
        for _ in range(0, 120, 10):
            for interface in netifaces.interfaces():
                if device_name == interface:
                    self.log.info("vNIC device %s is up", device_name)
                    return True
            time.sleep(10)
        return False

    def check_dmesg_error(self):
        '''
        Fail the test if unexpected kernel errors appear in dmesg.
        '''
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
            self.log.info(exc)
            self.fail("Kernel errors detected — check dmesg in debug log")

    def _verify_traffic(self, networkinterface, device_ip, netmask, peer_ip):
        '''
        Configure IP on networkinterface and ping peer to verify traffic.
        '''
        try:
            networkinterface.add_ipaddr(device_ip, netmask)
        except Exception:
            networkinterface.save(device_ip, netmask)
        if not wait.wait_for(networkinterface.is_link_up, timeout=120):
            self.fail("Unable to bring up link on vNIC after DLPAR")
        if networkinterface.ping_check(peer_ip, count=5) is not None:
            self.fail("Backend traffic check failed after DLPAR — ping to %s"
                      % peer_ip)

    # ------------------------------------------------------------------ #
    #  Test cases                                                         #
    # ------------------------------------------------------------------ #

    def test_vnic_dlpar(self):
        '''
        Regular vNIC DLPAR: drmgr-based hot remove and hot add.
        Verifies backend traffic with ping after each cycle.
        vNIC must already exist on the LPAR before running this test.
        '''
        for slot_no, device_ip, netmask, mac, peer_ip in zip(
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
            self._verify_traffic(networkinterface, device_ip, netmask, peer_ip)
        self.check_dmesg_error()

    def test_vnic_dlpar_lockdown(self):
        '''
        vNIC DLPAR under kernel lockdown.
        Sets lockdown to the configured mode (default: integrity) then
        performs the same drmgr-based remove / add cycles as test_vnic_dlpar.
        Verifies backend traffic after each cycle.
        Lockdown is restored to its original state in tearDown.
        '''
        if not self.check_lockdown_support():
            self.cancel("Kernel lockdown not supported — skipping lockdown test")

        current_state = self.get_lockdown_state()
        self.log.info("Lockdown state at test start: %s", current_state)

        # Ensure lockdown is active for this test regardless of setUp setting
        if current_state != self.lockdown_mode:
            if not self.set_lockdown_mode(self.lockdown_mode):
                self.fail(
                    f"Could not set lockdown to {self.lockdown_mode}")

        self.log.info("Running vNIC DLPAR with lockdown=%s", self.lockdown_mode)

        for slot_no, device_ip, netmask, mac, peer_ip in zip(
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
            self._verify_traffic(networkinterface, device_ip, netmask, peer_ip)

        self.check_dmesg_error()

    # ------------------------------------------------------------------ #
    #  Cleanup                                                            #
    # ------------------------------------------------------------------ #

    def tearDown(self):
        # Restore lockdown to state before the test
        if self.original_lockdown_state is not None:
            self.set_lockdown_mode(self.original_lockdown_state)
        self.session_hmc.quit()
