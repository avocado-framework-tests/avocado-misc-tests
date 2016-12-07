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
#
# Copyright: 2016 IBM
# Author: Venkat Rao B <vrbagal1@linux.vnet.ibm.com>


"""
This scripts runs test on LSI9361
"""

from avocado import Test
from avocado.utils import process
from avocado import main


class Avago9361(Test):

    """
    Here test cases related to LSI9361 adapter will be run
    """
    def setUp(self):

        """
        All basic set up for test case are done here
        """

        self.controller = int(self.params.get('controller', default='0'))

    def test_display(self):

        """
        Displays entire adapter configuration
        """
        cmd = "./storcli64 -v"
        self.check_pass(cmd, "Failed to display the version of the tool")
        cmd = "./storcli64 show ctrlcount"
        self.check_pass(cmd, "Failed to show the controleer count")
        cmd = "./storcli64 /c%d show" % self.controller
        self.check_pass(cmd, "Fail to display the adapter details")
        cmd = "./storcli64 /c%d show all" % self.controller
        self.check_pass(cmd, "Fail to display 'show all' o/p of the adapter")

    def check_pass(self, cmd, errmsg):

        """
        Helper function to check, if the cmd is passed or failed
        """
        if process.system(cmd, ignore_status=True, shell=True) != 0:
            self.fail(errmsg)

    def test_adjustablerates(self):

        """
        Function to set all adjustable values of the adapter
        """
        adjustable_rate = ['rebuildrate', 'migraterate', 'ccrate',
                           'bgirate', 'prrate']
        for i in adjustable_rate:
            for j in [0, 10, 30, 60, 100]:
                cmd = "./storcli64 /c%d show %s" % (self.controller, i)
                self.check_pass(cmd, "Failed to show the rate")
                cmd = "./storcli64 /c%d set %s=%d" % (self.controller, i, j)
                self.check_pass(cmd, "Failed to set the rate")

    def test_set_on_off(self):

        """
        Function to set ON/OFF values for the different values
        """
        adjust_on_off = ['restorehotspare', 'autorebuild', 'copyback', 'eghs',
                         'alarm', 'foreignautoimport', 'maintainpdfailhistory',
                         'ocr']
        for i in adjust_on_off:
            cmd = "./storcli64 /c%d show %s" % (self.controller, i)
            self.check_pass(cmd, "Failed to show the deatils of {0}" + i)
            cmd = "./storcli64 /c%d set %s=off" % (self.controller, i)
            self.check_pass(cmd, "Failed to set to OFF for {0}" + i)
            cmd = "./storcli64 /c%d show %s" % (self.controller, i)
            self.check_pass(cmd, "Failed to show the deatils {0}" + i)
            cmd = "./storcli64 /c%d set %s=on" % (self.controller, i)
            self.check_pass(cmd, "Failed to set to ON for {0}" + i)


if __name__ == "__main__":
    main()
