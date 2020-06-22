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
# Author: Narasimhan V <sim@linux.vnet.ibm.com>


"""
RAID devices are virtual devices created from two or more real block devices.
This allows multiple devices (typically disk drives or partitions thereof) to
be combined into a single device to hold (for example) a single filesystem.
Some RAID levels include redundancy and so can survive some degree of device
failure.
"""

from avocado import Test
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import softwareraid


class SoftwareRaid(Test):

    """
    This scripts create, assembles and stops md device, using mdadm tool
    """

    def setUp(self):
        """
        Checking if the required packages are installed,
        if not found packages will be installed.
        """

        smm = SoftwareManager()
        if not smm.check_installed("mdadm"):
            self.log.info("Mdadm must be installed before continuing the test")
            if SoftwareManager().install("mdadm") is False:
                self.cancel("Unable to install mdadm")
        disk = self.params.get('disks', default='').strip(" ")
        if not disk:
            self.cancel('No disks given')
        disk = disk.split()
        spare = self.params.get('spare_disks', default='').strip(" ")
        if spare:
            spare = spare.split()
        raid = self.params.get('raidname', default='/dev/md/mdsraid')
        raidlevel = str(self.params.get('raid', default='0'))
        metadata = str(self.params.get('metadata', default='1.2'))
        self.remadd = ''
        if raidlevel not in ['0', 'linear']:
            self.remadd = disk[-1]
        self.sraid = softwareraid.SoftwareRaid(raid, raidlevel, disk,
                                               metadata, spare)

    def test(self):
        """
        Decides which functions to be run for a perticular raid level, and runs
        those tests.
        """

        if not self.sraid.create():
            self.fail("Failed to create")
        if not self.remadd:
            return
        if not self.sraid.remove_disk(self.remadd):
            self.fail("Failed to remove disk")
        if not self.sraid.add_disk(self.remadd):
            self.fail("Failed to add disk")
        if not self.sraid.stop():
            self.fail("Failed to stop raid")
        if not self.sraid.assemble():
            self.fail("Failed to assemble raid")

    def tearDown(self):
        """
        Stop/Remove the raid device.
        """

        if self.sraid:
            self.sraid.stop()
            self.sraid.clear_superblock()
