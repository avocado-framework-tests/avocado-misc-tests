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
# Copyright: 2016 IBM
# Author: Naresh Bannoth <nbannoth@in.ibm.com>
# Author: Narasimhan V <sim@linux.vnet.ibm.com>

"""
PCI Hotplug can remove and add pci devices when the system is active.
This test verifies that for supported slots.
"""

import os
import platform

from avocado import Test
from avocado.utils import genio, linux_modules, pci, wait
from avocado.utils.software_manager import SoftwareManager


class PCIHotPlugTest(Test):

    """
    PCI Hotplug can remove and add pci devices when the system is active.
    This test verifies that for supported slots.
    :param device: Name of the pci device
    """

    def setUp(self):
        """
        Setup the device.
        """
        if 'ppc' not in platform.processor():
            self.cancel("Processor is not ppc64")
        if os.path.exists('/proc/device-tree/bmc'):
            self.cancel("Test Unsupported! on this platform")
        if 'pSeries' in open('/proc/cpuinfo', 'r').read():
            for mdl in ['rpaphp', 'rpadlpar_io']:
                if not linux_modules.module_is_loaded(mdl):
                    linux_modules.load_module(mdl)
        elif 'PowerNV' in open('/proc/cpuinfo', 'r').read():
            if not linux_modules.module_is_loaded("pnv_php"):
                linux_modules.load_module("pnv_php")
        self.dic = {}
        self.device = self.params.get('pci_devices', default="")
        self.count = int(self.params.get('count', default='1'))
        if not self.device:
            self.cancel("PCI_address not given")
        self.device = self.device.split(" ")
        smm = SoftwareManager()
        if not smm.check_installed("pciutils") and not smm.install("pciutils"):
            self.cancel("pciutils package is need to test")
        self.end_devices = {}
        for pci_addr in self.device:
            if not os.path.isdir('/sys/bus/pci/devices/%s' % pci_addr):
                self.cancel("%s not present in device path" % pci_addr)
            slot = pci.get_slot_from_sysfs(pci_addr)
            if not slot:
                self.cancel("slot number not available for: %s" % pci_addr)
            self.dic[pci_addr] = slot
            self.end_devices[pci_addr] = len(
                pci.get_disks_in_pci_address(pci_addr))
            self.end_devices[pci_addr] += len(
                pci.get_nics_in_pci_address(pci_addr))

    def test(self):
        """
        Creates namespace on the device.
        """
        err_pci = []
        for pci_addr in self.device:
            for _ in range(self.count):
                if not self.hotplug_remove(self.dic[pci_addr], pci_addr):
                    err_pci.append(pci_addr)
                else:
                    self.log.info("%s removed successfully", pci_addr)
                if not self.hotplug_add(self.dic[pci_addr], pci_addr):
                    err_pci.append(pci_addr)
                else:
                    self.log.info("%s added back successfully", pci_addr)
        if err_pci:
            self.fail("following devices failed: %s" % ", ".join(err_pci))

    @staticmethod
    def hotplug_remove(slot, pci_addr):
        """
        Hot Plug remove operation
        """
        genio.write_file("/sys/bus/pci/slots/%s/power" % slot, "0")

        def is_removed():
            """
            Returns True if pci device is removed, False otherwise.
            """
            if pci_addr in pci.get_pci_addresses():
                return False
            return True

        return wait.wait_for(is_removed, timeout=10) or False

    def hotplug_add(self, slot, pci_addr):
        """
        Hot plug add operation
        """
        genio.write_file("/sys/bus/pci/slots/%s/power" % slot, "1")

        def is_added():
            """
            Returns True if pci device is added, False otherwise.
            """
            if pci_addr not in pci.get_pci_addresses():
                return False
            return True

        def is_recovered():
            """
            Compares current endpoint devices in pci address with
            `pre` value, and returns True if equals pre.
            False otherwise.
            """
            post = len(pci.get_disks_in_pci_address(pci_addr))
            post += len(pci.get_nics_in_pci_address(pci_addr))
            self.log.debug("Pre: %d,  Post: %d",
                           self.end_devices[pci_addr], post)
            if post == self.end_devices[pci_addr]:
                return True
            return False

        if not wait.wait_for(is_added, timeout=10):
            return False
        # Waiting for 10s per end device, for recovery.
        return wait.wait_for(is_recovered,
                             self.end_devices[pci_addr] * 10)
