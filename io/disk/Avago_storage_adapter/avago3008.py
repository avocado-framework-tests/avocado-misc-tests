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
        self.raidlevel = str(self.params.get('raidlevel', default='0'))
        self.disk = str(self.params.get('disk')).split(" ")
        self.spare = str(self.params.get('spare'))
        self.size = int(self.params.get('size', default='max'))
        if not self.disk:
            self.skip("Please provide disks to run the tests")
        self.number_of_disk = len(self.disk)
        if self.number_of_disk < 2:
            self.skip("Not enough drives to perform the test")
        if self.raidlevel == 'raid1':
            self.raid_disk = " ".join(self.disk[0:2:1]).strip(" ")
        if self.raidlevel == 'raid1e':
            if self.number_of_disk < 3:
                self.skip("Raid1e needs minimum of 3 disks to be tested")
            else:
                self.raid_disk = " ".join(self.disk).strip(" ")
        if self.raidlevel == 'raid10':
            if self.number_of_disk < 4:
                self.skip("Raid10 needs minimum of 4 disks to be tested")
            else:
                self.raid_disk = " ".join(self.disk).strip(" ")
        if self.raidlevel == 'raid0':
            self.raid_disk = " ".join(self.disk).strip(" ")

    def test_run(self):

        """
        Decides which functions to run for given raid_level
        """

        cmd = "echo -e 'YES\nNO' | ./sas3ircu %d delete" \
              % (self.controller)
        if process.system(cmd, ignore_status=True, shell=True) != 0:
            self.fail("Unable to clear entire configuration before starting")
        if self.raidlevel == 'raid0':
            self.basictest()
        else:
            self.extensivetest()

    def extensivetest(self):

        """
        Lists all the LSI adapters attached to the mahcine
        :return:
        """

        self.adapterlist()
        self.adapterdetails()
        self.createraid()
        self.adapterdetails()
        self.adapter_status()
        self.set_online_offline("offline")
        self.set_online_offline("online")
        for _ in range(0, 5):
            for state in ['offline', 'online']:
                self.set_online_offline(state)
                time.sleep(10)
        if self.spare:
            self.hotspare()
        self.deleteraid()
        self.adapterdetails()
        self.adapter_status()

    def hotspare(self):

        """
        This is a helper function to create hot-spare
        """
        cmd = "echo -e 'YES\nNO' | ./sas3ircu %d hotspare %s" \
            % (self.controller, self.spare)
        if process.system(cmd, ignore_status=True, shell=True) != 0:
            self.fail("Failed to set hotspare drive")

    def set_online_offline(self, state):

        """
        This is a helper function, to change the state of the drives
        """
        cmd = "./sas3ircu %d set%s %s" \
              % (self.controller, state, self.disk[0])
        if process.system(cmd, ignore_status=True, shell=True) != 0:
            self.fail("Failed to set drive to %s" % state)

    def adapter_status(self):

        """
        This is a helper function, to check the status of the adapter
        """
        cmd = "./sas3ircu %d status" % self.controller
        if process.system(cmd, ignore_status=True, shell=True) != 0:
            self.fail("Failed to display the status of the adapter")
#        cmd = process.system_output(cmd, shell=True)
        cmd = "./sas3ircu %d status | grep 'Volume state' | awk '{print $4}'" \
              % self.controller
        process.run(cmd, shell=True)
        return cmd

    def adapterlist(self):

        """
        Lists all the LSI adapters attached to the mahcine
        :return:
        """
        cmd = "./sas3ircu list"
        if process.system(cmd, ignore_status=True, shell=True) != 0:
            self.fail("Failed to list all the Avogo adapters")

    def adapterdetails(self):

        """
        Display controller, volume and physical device info
        """

        cmd = "./sas3ircu %d display" % self.controller
        if process.system(cmd, ignore_status=True, shell=True) != 0:
            self.fail("Failed to display details of drives and VR vloumes")

    def createraid(self):

        """
        This function creates raid array
        """
        cmd = "./sas3ircu %d create %s %s %s vr1 noprompt" \
              % (self.controller, self.raidlevel, self.size, self.raid_disk)
        if process.system(cmd, ignore_status=True, shell=True) != 0:
            self.fail("Failed to create raid on the drives")

    def deleteraid(self):

        """
        This function deletes raid array
        """
        cmd = "./sas3ircu %d display | grep 'vr1' -B 2 | grep 'Volume ID' | \
               awk '{print $4}'" % self.controller
        volume_id = int(process.system_output(cmd, shell=True))
        cmd = "echo -e 'YES\nNO' | ./sas3ircu %d deletevolume %d" \
              % (self.controller, volume_id)
        if process.system(cmd, ignore_status=True, shell=True) != 0:
            self.fail("Failed to delete raid array VR1")

    def basictest(self):

        """
        This function does only create and delete Raid
        """
        self.adapterdetails()
        self.createraid()
        self.adapter_status()
        self.adapterdetails()
        self.deleteraid()
        self.adapter_status()


if __name__ == "__main__":
    main()
