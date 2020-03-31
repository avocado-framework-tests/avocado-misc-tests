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
import re
import platform
from avocado import Test
from avocado import main
from avocado.utils import wait
from avocado.utils import linux_modules, genio, pci, cpu
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
        if cpu._list_matches(open('/proc/cpuinfo').readlines(),
                             'platform\t: pSeries\n'):
            self.power_vm = True
            for mdl in ['rpaphp', 'rpadlpar_io']:
                if not linux_modules.module_is_loaded(mdl):
                    linux_modules.load_module(mdl)
        elif cpu._list_matches(open('/proc/cpuinfo').readlines(),
                               'platform\t: PowerNV\n'):
            self.power_vm = False
            if not linux_modules.module_is_loaded("pnv_php"):
                linux_modules.load_module("pnv_php")
        self.dic = {}
        self.device = self.params.get('pci_device', default=' ').split(",")
        self.count = int(self.params.get('count', default='1'))
        if not self.device:
            self.cancel("PCI_address not given")
        smm = SoftwareManager()
        if not smm.check_installed("pciutils") and not smm.install("pciutils"):
            self.cancel("pciutils package is need to test")
        for pci_addr in self.device:
            if not os.path.isdir('/sys/bus/pci/devices/%s' % pci_addr):
                self.cancel("%s not present in device path" % pci_addr)
            slot = self.get_slot(pci_addr)
            if not slot:
                self.cancel("slot number not available for: %s" % pci_addr)
            self.dic[pci_addr] = slot

    def get_slot(self, pci_addr):
        '''
        Returns the slot number with pci_address
        '''
        if self.power_vm:
            devspec = genio.read_file("/sys/bus/pci/devices/%s/devspec"
                                      % pci_addr)
            slot = genio.read_file("/proc/device-tree/%s/ibm,loc-code"
                                   % devspec)
            slot = re.match(r'((\w+)[\.])+(\w+)-P(\d+)-C(\d+)|Slot(\d+)',
                            slot).group()
        else:
            slot = pci.get_pci_prop(pci_addr, "PhySlot")
        if not os.path.isdir('/sys/bus/pci/slots/%s' % slot):
            self.log.info("%s Slot not available" % slot)
            return ""
        if not os.path.exists('/sys/bus/pci/slots/%s/power' % slot):
            self.log.info("%s Slot does not support hotplug" % slot)
            return ""
        return slot

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
                    self.log.info("%s removed successfully" % pci_addr)
                if not self.hotplug_add(self.dic[pci_addr], pci_addr):
                    err_pci.append(pci_addr)
                else:
                    self.log.info("%s added back successfully" % pci_addr)
        if err_pci:
            self.fail("following devices failed: %s" % ", ".join(err_pci))

    def hotplug_remove(self, slot, pci_addr):
        """
        Hot Plug remove operation
        """
        genio.write_file("/sys/bus/pci/slots/%s/power" % slot, "0")

        def is_removed():
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
            if pci_addr not in pci.get_pci_addresses():
                return False
            return True

        return wait.wait_for(is_added, timeout=10) or False


if __name__ == "__main__":
    main()
