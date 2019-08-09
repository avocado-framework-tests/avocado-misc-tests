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
# Author: Narasimhan V <sim@linux.vnet.ibm.com>

"""
PCI Hotplug can remove and add pci devices when the system is active.
This test verifies that for supported slots.
"""

import os
import time
import re
import platform
from avocado import Test
from avocado import main
from avocado.utils import linux_modules, genio, pci, cpu


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
            power_vm = True
            for mdl in ['rpaphp', 'rpadlpar_io']:
                if not linux_modules.module_is_loaded(mdl):
                    linux_modules.load_module(mdl)
        elif cpu._list_matches(open('/proc/cpuinfo').readlines(),
                               'platform\t: PowerNV\n'):
            power_vm = False
            if not linux_modules.module_is_loaded("pnv_php"):
                linux_modules.load_module("pnv_php")
        self.return_code = 0
        self.device = self.params.get('pci_device', default=' ')
        self.num_of_hotplug = int(self.params.get('num_of_hotplug', default='1'))
        if not os.path.isdir('/sys/bus/pci/devices/%s' % self.device):
            self.cancel("PCI device given does not exist")
        self.num_of_hotplug = int(self.params.get('num_of_hotplug', default='1'))
        if power_vm:
            devspec = genio.read_file("/sys/bus/pci/devices/%s/devspec"
                                      % self.device)
            self.slot = genio.read_file("/proc/device-tree/%s/ibm,loc-code"
                                        % devspec)
            self.slot = re.match(r'((\w+)[\.])+(\w+)-P(\d+)-C(\d+)|Slot(\d+)',
                                 self.slot).group()
        else:
            self.slot = pci.get_pci_prop(self.device, "PhySlot")
        if not os.path.isdir('/sys/bus/pci/slots/%s' % self.slot):
            self.cancel("%s Slot not available" % self.slot)
        if not os.path.exists('/sys/bus/pci/slots/%s/power' % self.slot):
            self.cancel("%s Slot does not support hotplug" % self.slot)

    def test(self):
        """
        Creates namespace on the device.
        """

        for _ in range(self.num_of_hotplug):
            self.hotplug_remove()
            self.hotplug_add()
            self.check_add_remove()

    def hotplug_remove(self):
        """
        Hot Plug remove operation
        """
        genio.write_file("/sys/bus/pci/slots/%s/power" % self.slot, "0")
        time.sleep(5)
        if self.device in pci.get_pci_addresses():
            self.return_code = 1
        else:
            self.log.info("Adapter %s removed successfully", self.device)

    def hotplug_add(self):
        """
        Hot plug add operation
        """
        genio.write_file("/sys/bus/pci/slots/%s/power" % self.slot, "1")
        time.sleep(5)
        if self.device not in pci.get_pci_addresses():
            self.return_code = 2
        else:
            self.log.info("Adapter %s added back successfully", self.device)

    def check_add_remove(self):
        """
        Function to check if the adapter is removed and
        added back as desired
        """
        if self.return_code == 1:
            self.fail('%s not removed' % self.device)
        if self.return_code == 2:
            self.fail('%s not attached back' % self.device)


if __name__ == "__main__":
    main()
