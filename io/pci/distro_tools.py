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
Tests the different tool
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
    @skipUnless(IS_POWER_VM,
                "supported only on PowerVM platform")
    def setUp(self):
        '''
        to check host platform
        '''
        self.option = self.params.get("option", default='')

    def test(self):
        '''
        test the lsslot tool
        '''
        cmd = "lsslot"
        if self.option == "pci":
            cmd = "%s -d %s" % (cmd, self.option)
        else:
            cmd = "%s -c %s" % (cmd, self.option)
        result = process.run(cmd, shell=True, ignore_status=True)
        if result.exit_status != 0:
            self.fail("Failed to display hot plug slots")


if __name__ == "__main__":
    main()
