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

IS_POWER_VM = 'pSeries' in open('/proc/cpuinfo', 'r').read()


class DisrtoTool(Test):
    '''
    to test different type of tool
    '''

    def setUp(self):
        '''
        get all parameters
        '''
        self.option = self.params.get("test_opt", default='').split(",")
        self.tool = self.params.get("tool", default='')

    @skipUnless(IS_POWER_VM,
                "supported only on PowerVM platform")
    def lsslot(self, option):
        '''
        run lsslot
        '''
        cmd = "lsslot"
        if option == "pci":
            cmd = "%s -d %s" % (cmd, option)
        else:
            cmd = "%s -c %s" % (cmd, option)
        result = process.run(cmd, shell=True, ignore_status=True)
        if result.exit_status != 0:
            self.fail("Failed to display hot plug slots")

    def netstat(self, option):
        '''
        run netstat
        '''
        cmd = "netstat -%s" % option
        result = process.run(cmd, shell=True, ignore_status=True)
        if result.exit_status != 0:
            self.fail("Failed to monitoring network connections")

    def lsprop(self, option):
        '''
        run lsprop
        '''
        if option == "r":
            cmd = "lsprop --%s" % option
        else:
            cmd = "lsprop -%s" % option
        result = process.run(cmd, shell=True, ignore_status=True)
        if result.exit_status != 0:
            self.fail("lsprop failed")

    def test(self):
        '''
        test different distro tools
        '''
        if self.tool == "lsslot":
            for val in self.option:
                self.lsslot(val)
        elif self.tool == "netstat":
            for val in self.option:
                self.netstat(val)
        elif self.tool == "lsprop":
            for val in self.option:
                self.lsprop(val)


if __name__ == "__main__":
    main()
