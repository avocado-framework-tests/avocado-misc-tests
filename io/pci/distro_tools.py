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

from avocado import main
from avocado import Test
from avocado.utils import process
from avocado import skipUnless
from avocado.utils import pci
from avocado.utils.software_manager import SoftwareManager

IS_POWER_VM = 'pSeries' in open('/proc/cpuinfo', 'r').read()


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
        self.pci_device = self.params.get("pci_device", default='')
        if not self.pci_device:
            self.cancel("pci bus not give test may fail")
        self.adapter_type = pci.get_pci_class_name(self.pci_device)
        smm = SoftwareManager()
        if not smm.check_installed("pciutils") and not smm.install("pciutils"):
            self.cancel("pciutils package is need to test")

    @skipUnless(IS_POWER_VM,
                "supported only on PowerVM platform")
    def lsslot(self):
        '''
        run lsslot
        '''
        cmd = "lsslot"
        if self.option == "pci":
            cmd = "%s -d %s" % (cmd, self.option)
        else:
            cmd = "%s -c %s" % (cmd, self.option)
        result = process.run(cmd, shell=True, ignore_status=True)
        if result.exit_status != 0:
            self.fail("Failed to display hot plug slots")

    def netstat(self):
        '''
        run netstat
        '''
        cmd = "netstat -%s" % self.option
        result = process.run(cmd, shell=True, ignore_status=True)
        if result.exit_status != 0:
            self.fail("Failed to monitoring network connections")

    def lsprop(self):
        '''
        run lsprop
        '''
        if self.option == "r":
            cmd = "lsprop --%s" % self.option
        else:
            cmd = "lsprop -%s" % self.option
        result = process.run(cmd, shell=True, ignore_status=True)
        if result.exit_status != 0:
            self.fail("lsprop failed")

    def lsvio(self):
        '''
        run lsvio aaplicable only for PowerVM
        '''
        cmd = "lsvio -%s" % self.option
        result = process.run(cmd, shell=True, ignore_status=True)
        if result.exit_status != 0:
            self.fail("lsvio failed")

    def lsdevinfo(self):
        '''
        run lsdevinfo
        '''
        cmd = "lsdevinfo -%s" % self.option
        result = process.run(cmd, shell=True, ignore_status=True)
        if result.exit_status != 0:
            self.fail("lsdevinfo failed")

    def usys(self, tool, option, pci_device):
        '''
        run usysident and usysattn
        '''
        location_code = pci.get_slot_from_sysfs(pci_device)
        interface = pci.get_interfaces_in_pci_address(pci_device,
                                                      self.adapter_type)[0]
        cmd = "%s %s" % (tool, option)
        if '-P' in cmd:
            cmd += " -l %s" % location_code
        if '-t' in cmd:
            cmd += " -d %s" % interface

        result = process.run(cmd, shell=True, ignore_status=True)
        if tool == "usysident":
            if "There is no identify indicator" in result.stdout_text:
                self.log.warn("%s option %s failed" % (tool, self.option))
        elif tool == "usysattn":
            if "There is no fault indicator" in result.stdout_text:
                self.log.warn("%s option %s failed" % (tool, self.option))

    def usysattn(self):
        self.usys(self.tool, self.option, self.pci_device)
        return

    def usysident(self):
        self.usys(self.tool, self.option, self.pci_device)
        return

    @skipUnless(IS_POWER_VM,
                "supported only on PowerVM platform")
    def ofpathname(self):
        '''
        run ofpathname
        '''
        interface = pci.get_interfaces_in_pci_address(self.pci_device,
                                                      self.adapter_type)[0]
        cmd = "ofpathname -%s %s" % (self.option, interface)
        result = process.run(cmd, shell=True, ignore_status=True)
        if result.exit_status != 0:
            self.fail("ofpathname failed")

    def test(self):
        '''
        test different distro tools
        '''
        getattr(self, self.tool)()


if __name__ == "__main__":
    main()
