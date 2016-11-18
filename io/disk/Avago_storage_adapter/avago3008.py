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
This script will list all the adapter connected to the system.
"""


import time
from avocado import Test
from avocado.utils import process
from avocado import main


class Avago3008(Test):

    """
    This script lists all the LSI adapters attached on the machine
    """

    def setUp(self):

        """
        Lists all available Avago adapters (does not need ctlr #>
        """

        self.controller = int(self.params.get('controller', default='0'))
        self.disk = str(self.params.get('disk'))
        if not self.disk:
            self.skip("Please provide disks to run the tests")
        self.disk = self.disk.strip(" ").split(" ")
        self.number_of_disk = len(self.disk)
        if self.number_of_disk < 2:
            self.skip("Not enough drives to perform the test")

    def test_adapterlist(self):

        """
        Lists all the LSI adapters attached to the mahcine
        :return:
        """
        cmd = "./sas3ircu list"
        if process.system(cmd, ignore_status=True, shell=True) != 0:
            self.fail("Failed to list all the Avogo adapters")

    def test_adapterdetails(self):

        """
        Display controller, volume and physical device info
        """

        cmd = "./sas3ircu %d display" % self.controller
        if process.system(cmd, ignore_status=True, shell=True) != 0:
            self.fail("Failed to display details of drives and VR vloumes")

    def test_createraid(self):

        """
        This function creates raid1 array
        """

        if self.number_of_disk >= 2:
            cmd = "./sas3ircu %d create RAID1 max %s %s vr1 noprompt" \
                 % (self.controller, self.disk[0], self.disk[1])
            if process.system(cmd, ignore_status=True, shell=True) != 0:
                self.fail("Failed to create RAID1 on the drives")
        else:
            self.skip("Please provide minimum of two drives")

    def set_online_offline(self, state):

        """
        This is a helper function, to change the state of the drives
        """
        cmd = "./sas3ircu %d set%s %s" \
              % (self.controller, state, self.disk[0])
        if process.system(cmd, ignore_status=True, shell=True) != 0:
            self.fail("Failed to set drive to %s" % state)

    def test_setoffline(self):

        """
        This function set's a drive to offline
        """
        self.set_online_offline("offline")

    def test_setonline(self):

        """
        This function set's a drive to online
        """
        self.set_online_offline("online")

    def test_toggle_online_offline(self):

        """
        This function, toggles the state of the drive b/w online/offline
        """
        for _ in range(0, 5):
            for state in ['offline', 'online']:
                self.set_online_offline(state)
                time.sleep(10)

    def test_hotspare(self):

        """
        This function creates a HotSpare
        """
        if self.number_of_disk > 2:
            cmd = "echo -e 'YES\nNO' | ./sas3ircu %d hotspare %s" \
                 % (self.controller, self.disk[2])
            if process.system(cmd, ignore_status=True, shell=True) != 0:
                self.fail("Failed to set hotspare drive")
        else:
            self.fail("Insufficient number of disk")


if __name__ == "__main__":
    main()
