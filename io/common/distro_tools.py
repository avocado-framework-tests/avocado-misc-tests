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
# Author: Bimurti Bidhibrata Pattjoshi <bbidhibr@in.ibm.com>
#

"""
Test the different tools
"""

from avocado import Test
from avocado.utils import pci, process
from avocado.utils.software_manager import SoftwareManager


class DisrtoTool(Test):
    '''
    to test different type of tool
    '''

    def setUp(self):
        '''
        get all parameters
        '''
        self.option = self.params.get("test_opt", default='')
        self.tool = self.params.get("tool", default='')
        self.warn_msg = self.params.get("warn_msg", default='')
        self.pci_device = self.params.get("pci_device", default=None)

        if self.pci_device:
            if 'LOC_CODE' in self.option:
                location_code = pci.get_slot_from_sysfs(self.pci_device)
                self.option = self.option.replace('LOC_CODE', location_code)
            if 'INTERFACE' in self.option:
                adapter_type = pci.get_pci_class_name(self.pci_device)
                interface = pci.get_interfaces_in_pci_address(self.pci_device,
                                                              adapter_type)[0]
                self.option = self.option.replace('INTERFACE', interface)

        if 'DEVICE_PATH_NAME' in self.option:
            adapter_type = pci.get_pci_class_name(self.pci_device)
            interface = pci.get_interfaces_in_pci_address(self.pci_device,
                                                          adapter_type)[0]
            path = '/sys/class/net/%s/device/uevent' % interface
            output = open(path, 'r').read()
            for line in output.splitlines():
                if "OF_FULLNAME" in line:
                    device_path_name = line.split('=')[-1]
            self.option = self.option.replace('DEVICE_PATH_NAME',
                                              device_path_name)

        smm = SoftwareManager()
        if not smm.check_installed("pciutils") and not smm.install("pciutils"):
            self.cancel("pciutils package is need to test")

    def test(self):
        '''
        test all distro tools
        '''
        cmd = "%s %s" % (self.tool, self.option)
        result = process.run(cmd, shell=True, ignore_status=True)

        if self.warn_msg:
            if self.warn_msg in result.stdout_text:
                self.log.warn("%s option %s failed" % (self.tool, self.option))
        else:
            if result.exit_status != 0:
                self.fail("%s tool failed" % self.tool)
