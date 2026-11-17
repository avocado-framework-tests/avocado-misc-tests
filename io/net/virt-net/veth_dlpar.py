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
# Author: Bismruti Bidhibrata Pattjoshi<bbidhibr@in.ibm.com>

"""
Veth DLPAR operations
"""

import os
from avocado import Test
from avocado import skipIf, skipUnless
from avocado.utils import process
from avocado.utils import distro
from avocado.utils import dmesg
from avocado.utils import linux
from avocado.utils import wait
from avocado.utils.process import CmdError
from avocado.utils.network.hosts import LocalHost
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.software_manager.manager import SoftwareManager

IS_POWER_NV = 'PowerNV' in open('/proc/cpuinfo', 'r').read()
IS_KVM_GUEST = 'qemu' in open('/proc/cpuinfo', 'r').read()


class VethdlparTest(Test):
    '''
    DLPAR veth script does veth device remove and add using drmgr from the
    host LPAR. The slot of the given interface is discovered automatically.
    Optionally enables kernel lockdown before the DLPAR cycle.
    Update the details in yaml file.
    '''

    @skipUnless("ppc" in distro.detect().arch,
                "supported only on Power platform")
    @skipIf(IS_POWER_NV or IS_KVM_GUEST,
            "This test is not supported on KVM guest or PowerNV platform")
    def setUp(self):
        '''
        Gather necessary test inputs.
        '''
        self.original_lockdown_state = None
        self.install_packages()
        self.rsct_service_start()
        local = LocalHost()
        interfaces = os.listdir('/sys/class/net')
        device = self.params.get('interface', default=None)
        if device in interfaces:
            self.interface = device
        elif local.validate_mac_addr(device) and device in local.get_all_hwaddr():
            self.interface = local.get_interface_by_hwaddr(device).name
        else:
            self.interface = None
            self.cancel("Please check the network device")
        self.ipaddr = self.params.get("host_ip", default="")
        self.netmask = self.params.get("netmask", default="")
        self.peer_ip = self.params.get('peer_ip', default=None)
        self.num_of_dlpar = int(self.params.get("num_of_dlpar", default='1'))
        self.slot = self.find_virtual_slot()
        if not self.slot:
            self.cancel("Virtual slot not found for interface %s"
                        % self.interface)
        self.log.info("Interface %s is on slot %s", self.interface, self.slot)
        self.networkinterface = NetworkInterface(self.interface, local)
        try:
            self.networkinterface.add_ipaddr(self.ipaddr, self.netmask)
            self.networkinterface.save(self.ipaddr, self.netmask)
        except Exception:
            self.networkinterface.save(self.ipaddr, self.netmask)
        self.networkinterface.bring_up()
        if self.networkinterface.ping_check(self.peer_ip, count=5) is not None:
            self.cancel("peer connection is failed")
        dmesg.clear_dmesg()
        self.lockdown_mode = self.params.get("lockdown_mode", default="integrity")
        self.lockdown_enable = self.params.get("lockdown_enable", default=False)
        self.original_lockdown_state, _ = linux.is_kernel_lockdown_enabled()
        if self.lockdown_enable is True:
            if self.original_lockdown_state is None:
                self.cancel("Kernel lockdown not supported on this system")
            if not self._enable_lockdown(self.lockdown_mode):
                self.fail(
                    "Failed to enable kernel lockdown "
                    "(%s)" % self.lockdown_mode)
            else:
                self.log.info("lockdown enabled successfully")
        else:
            self.log.info(
                "Running veth DLPAR test without lockdown enabled")

    def install_packages(self):
        '''
        Install packages required by drmgr based DLPAR.
        '''
        smm = SoftwareManager()
        shell_pkg = 'ksh' if smm.check_installed('ksh') else 'mksh'
        pkgs = [shell_pkg, 'src', 'rsct.basic', 'rsct.core.utils',
                'rsct.core', 'DynamicRM', 'powerpc-utils']
        for pkg in pkgs:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel('%s is needed for the test to be run' % pkg)

    def rsct_service_start(self):
        '''
        Start rsct services required for DLPAR operations.
        '''
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

    def _enable_lockdown(self, mode):
        '''
        Enable kernel lockdown to *mode* using avocado.utils.linux APIs.

        :param mode: 'integrity' or 'confidentiality'
        :return: True on success, False otherwise.
        '''
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
        '''
        Restore lockdown to *original_mode*.
        Note: the kernel only allows escalation
        (none->integrity->confidentiality).
        Downgrade (e.g. integrity->none) is not possible at runtime
        without a reboot; this method logs a warning in that case.
        '''
        current_mode, _ = linux.is_kernel_lockdown_enabled()
        if current_mode != original_mode:
            self.log.info(
                "Kernel lockdown cannot be downgraded at runtime "
                "(current: %s, original: %s).", current_mode, original_mode)

    def find_virtual_slot(self):
        '''
        Return the virtual slot location code of self.interface via lsslot,
        e.g. U9043.MRX.13ECF5X-V9-C5. The interface is mapped to its VIO
        device ID (e.g. 30000005) through sysfs.
        '''
        dev_id = os.path.basename(os.path.realpath(
            os.path.join('/sys/class/net', self.interface, 'device')))
        output = process.system_output(
            "lsslot -c slot", ignore_status=True, shell=True, sudo=True)
        for line in output.decode("utf-8").splitlines():
            if line.startswith('#'):
                continue
            if dev_id in line:
                return line.split()[0]
        return None

    def drmgr_veth_dlpar(self, operation):
        '''
        Perform OS-level drmgr add (-a) or remove (-r) on self.slot.
        '''
        cmd = 'drmgr %s -c slot -s %s -w 5 -d 1' % (operation, self.slot)
        if process.system(cmd, shell=True, sudo=True, ignore_status=True):
            self.fail("drmgr operation %s failed for veth slot %s"
                      % (operation, self.slot))

    def wait_interface(self):
        '''
        Poll until the interface reappears in the OS (up to 120 s).
        '''
        result = wait.wait_for(
            self.networkinterface.is_available, timeout=120,
            text="Waiting for veth %s to come up" % self.interface)
        if not result:
            self.fail("veth %s did not reappear after DLPAR add"
                      % self.interface)
        self.log.info("veth device %s is up", self.interface)

    def check_dmesg_error(self):
        '''
        Fail the test if unexpected kernel errors appear in dmesg.
        '''
        self.log.info("Checking dmesg for kernel errors")
        try:
            dmesg.collect_errors_by_level(level_check=4)
        except Exception as exc:
            self.log.debug(str(exc))
            self.fail("Kernel errors detected - check dmesg in debug log")

    def test_dlpar(self):
        '''
        veth dlpar remove and add operation using drmgr.
        Verifies traffic with ping after each cycle.
        '''
        for _ in range(self.num_of_dlpar):
            self.drmgr_veth_dlpar('-r')
            self.drmgr_veth_dlpar('-a')
            self.wait_interface()
            try:
                self.networkinterface.add_ipaddr(self.ipaddr, self.netmask)
            except Exception as exc:
                self.log.debug("add_ipaddr failed (%s)", exc)
            self.networkinterface.bring_up()
            if self.networkinterface.ping_check(self.peer_ip,
                                                count=5) is not None:
                self.fail("ping failed after add operation")
        self.check_dmesg_error()

    def tearDown(self):
        if hasattr(self, 'original_lockdown_state') and \
                self.original_lockdown_state is not None:
            self._restore_lockdown(self.original_lockdown_state)
        if hasattr(self, 'networkinterface') and self.interface:
            self.networkinterface.remove_ipaddr(self.ipaddr, self.netmask)
            self.networkinterface.restore_from_backup()
