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
# Author: Manvanthara B Puttashankar <manvanth@linux.vnet.ibm.com>


"""
smartctl - controls  the Self-Monitoring, Analysis and Reporting 
Technology (SMART) system built into most ATA/SATA and SCSI/SAS 
hard drives and solid-state drives
"""

import time
from avocado import Test
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import process
from avocado import main


class SmartctlTest(Test):

    """
    This scripts performs S.M.A.R.T relavent tests using smartctl tool 
    on one or more disks
    """

    def setUp(self):

        """
        Checking if the required packages are installed,
        if not found packages will be installed
        """

        smm = SoftwareManager()
        if not smm.check_installed("smartctl"):
            self.log.info("smartctl should be installed prior to the test")
            if SoftwareManager().install("smartmontools") is False:
                self.skip("Unable to install smartctl")
        self.option = self.params.get('option')
        disk_list = self.params.get('disk').strip(" ")
        self.disk_list = disk_list.split()
        self.to = self.params.get("timeout", default="2400")
        if self.disk_list is '' or self.option is '':
            self.skip(" Test skipped!!, please ensure Block device and options are specified in yaml file")

    def test(self):
        """
        executes S.M.A.R.T options using smartctl tool 
        """
        for disks in self.disk_list:
            self.log.info(" Trying with Disk %s" % (disks))
            if self.option == "--test=long":
                # Self Test will be run for 2 min
                cmd = "timeout %s smartctl %s %s; sleep 120; smartctl -X %s; smartctl -A %s" % ( self.to, self.option, disks, disks, disks )
            else:
                cmd = "timeout %s smartctl %s %s" % ( self.to, self.option, disks )
            if process.system(cmd, ignore_status=True, shell=True):
                # TODO: tool can be improved to validate the disk data for different vendors
                self.fail("Smartctl option %s FAILS" % self.option)

if __name__ == "__main__":
    main()
