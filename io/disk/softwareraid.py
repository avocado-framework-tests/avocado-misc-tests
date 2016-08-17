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
RAID devices are virtual devices created from two or more real block devices.
This allows multiple devices (typically disk drives or partitions thereof) to
be combined into a single device to hold (for example) a single filesystem.
Some RAID levels include redundancy and so can survive some degree of device
failure.
"""

import re
from avocado import Test
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import process
from avocado import main


class SoftwareRaid(Test):

    """
    This scripts create, assembles and stops md device, using mdadm tool
    """

    def setUp(self):

        """
        Checking if the required packages are installed,
        if not found packages will be installed
        """

        smm = SoftwareManager()
        if smm.check_installed("mdadm") is False:
            print("Mdadm is not installed")
            if SoftwareManager().install("mdadm") is False:
                self.skip("Unable to install mdadm")
        cmd = "mdadm -V"
        if process.system(cmd, ignore_status=True, shell=True) != 0:
            self.fail("Unable to get the mdadm Version")
        self.loop = ''
        for _ in range(0, 4):
            cmd = "losetup --find"
            varstr = process.system_output(cmd, ignore_status=True, shell=True)
            var = int(re.match(r'(/dev/loop)(\d+)', varstr).group(2))
            cmd = "dd if=/dev/zero of=/file%d bs=1k count=100" % var
            process.system(cmd, ignore_status=True, shell=True)
            cmd = "losetup /dev/loop%d /file%d" % (var, var)
            process.system(cmd, ignore_status=True, shell=True)
            self.loop += "/dev/loop%d " % var
        self.disk = self.params.get('disk', default=self.loop).strip(" ")
        self.raidlevel = str(self.params.get('raid', default='0'))
        self.disk_count = len(self.disk.split(' '))
        if self.raidlevel == '5' or self.raidlevel == '10':
            if self.disk_count < 2:
                self.skip("Minimum of two disk are required \
                          to create Raid5/10")
        if self.raidlevel == '6':
            if self.disk_count < 3:
                self.skip("Minimum of three disk are required to create Raid6")

    def test_createraid(self):

        """
        Creates, stops and assemble's softwareraid on the disk
        """
        cmd = "echo 'yes' | mdadm --create --verbose /dev/md/mdsraid \
             --level=%s " "--raid-devices=%d %s --force" \
              % (self.raidlevel, self.disk_count, self.disk)
        if process.system(cmd, ignore_status=True,
                          shell=True) != 0:
            self.fail("Failed to create a MD device")
        cmd = "mdadm --manage /dev/md/mdsraid --stop"
        if process.system(cmd, ignore_status=True,
                          shell=True) != 0:
            self.fail("Failed to stop/remove the MD device")
        cmd = "mdadm --assemble /dev/md/mdsraid %s" % self.disk
        if process.system(cmd, ignore_status=True,
                          shell=True) != 0:
            self.fail("Failed to assemble back the MD device")
        cmd = "mdadm --manage /dev/md/mdsraid --stop"
        if process.system(cmd, ignore_status=True,
                          shell=True) != 0:
            self.fail("Failed to stop/remove the MD device")

    def tearDown(self):

        """
        Cleaning all the loop devices created
        """
        print "Clean all the loop devices"
        self.loop = self.loop.strip(' ')
        for i in self.loop.split(' '):
            print i
            cmd = "losetup -d %s" % i
            process.system(cmd, ignore_status=True, shell=True)

if __name__ == "__main__":
    main()
