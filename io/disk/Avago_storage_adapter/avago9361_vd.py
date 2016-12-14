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
This scripts performs Virtual Drive(VD) operations on drives
"""

import time
from avocado import Test
from avocado.utils import process
from avocado import main


class Avago9361(Test):

    """
    This class contains functions for VD operations
    """
    def setUp(self):

        """
        All basic set up is done here
        """
        self.controller = int(self.params.get('controller', default='0'))
        self.disk = str(self.params.get('disk')).split(" ")
        self.raid_level = str(self.params.get('raid_level', default='0'))
        self.size = str(self.params.get('size', default='all'))
        if not self.disk:
            self.skip("Please provide disk to perform VD operations")
        self.dict_raid = {'r0': [1, None], 'r1': [2, 'Multiple2'],
                          'r5': [3, None], 'r6': [3, None],
                          'r00': [4, 'Multiple2'], 'r10': [4, 'Multiple2'],
                          'r50': [6, 'Multiple3'], 'r60': [6, 'Multiple3']}
        self.value = self.dict_raid[self.raid_level]

        if len(self.disk) < self.value[0]:
            self.skip("Please give enough number of drives to create %s"
                      % self.raid_level)
        if self.value[1] is not None:
            multiple = int(self.value[1].split("Multiple")[-1])
            self.disk = self.disk[:len(self.disk) -
                                  (len(self.disk) % multiple)]
        self.raid_disk = ",".join(self.disk).strip(" ")
        if self.raid_level == 'r10' or self.raid_level == 'r00':
            self.pdperarray = 2
        elif self.raid_level == 'r50' or self.raid_level == 'r60':
            self.pdperarray = 3
        if self.raid_level == 'r0':
            if 'cc' in str(self.name):
                self.skip("CC not applicable for Raid0")

    def test_createall(self):

        """
        Function to create different raid level
        """
        write_policy = ['WT', 'WB', 'AWB']
        read_policy = ['nora', 'ra']
        io_policy = ['direct', 'cached']
        strip = [64, 128, 256, 512, 1024]
        for write in write_policy:
            for read in read_policy:
                for iopolicy in io_policy:
                    for stripe in strip:
                        self.vd_create(write, read, iopolicy, stripe)
                        self.vd_details()
                        self.vd_delete()

    def test_maxvd(self):

        """
        Function to create max VD
        """
        for _ in range(1, 17):
            self.vd_create('WT', 'nora', 'direct', 1024)
        self.vd_details()
        self.vd_delete()
        if self.raid_level == 'r0':
            for disk in range(0, 3):
                if disk > len(self.disk):
                    self.raid_disk = self.disk[disk]
                    for _ in range(1, 17):
                        self.vd_create('WT', 'nora', 'direct', 512)
                    self.vd_details()
                self.vd_delete()

    def test_cc(self):

        """
        Function to do consistency operations on VD
        """
        self.vd_create('WT', 'nora', 'direct', 256)
        self.vd_details()
        self.cc_operations()
        self.vd_delete()

    def vd_details(self):

        """
        Function to display the VD details
        """
        cmd = "./storcli64 /c%d/vall show" % self.controller
        self.check_pass(cmd, "Failed to display VD configuration")

    def vd_delete(self):

        """
        Function to delete the VD
        """
        cmd = "./storcli64 /c%d/vall delete force" % self.controller
        self.check_pass(cmd, "Failed to delete VD")

    def vd_create(self, write, read, iopolicy, stripe):

        """
        Function to create a VD
        """
        if self.raid_level in ['r00', 'r10', 'r50', 'r60']:
            cmd = "./storcli64 /c%d add vd %s size=%s drives=%s PDperArray=%d %s %s %s \
                   strip=%d" % (self.controller, self.raid_level, self.size,
                                self.raid_disk, self.pdperarray, write, read,
                                iopolicy, stripe)
            self.check_pass(cmd, "Failed to create raid")

        else:
            cmd = "./storcli64 /c%d add vd %s size=%s drives=%s %s %s %s \
                   strip=%d" % (self.controller, self.raid_level, self.size,
                                self.raid_disk, write, read, iopolicy, stripe)
            self.check_pass(cmd, "Failed to create raid")

    def check_pass(self, cmd, errmsg):

        """
        Helper function to check, if the cmd is passed or failed
        """
        if process.system(cmd, ignore_status=True, shell=True) != 0:
            self.fail(errmsg)

    def cc_showprogress(self):

        """
        Helper function to see the CC progress
        """
        cmd = "./storcli64 /c%d/v0 show cc" % self.controller
        output = process.run(cmd, ignore_status=True, shell=True)
        if output.exit_status != 0:
            self.fail("Failed to display the CC progress")
        for lines in output.stdout.splitlines():
            for times in ['Hour', 'Minute', 'Second']:
                if times in lines:
                    return True

    def cc_operations(self):

        """
        Helper function CC operations
        """
        for state in ['start', 'stop', 'start', 'pause', 'resume']:
            self.cc_state(state)
            self.cc_showprogress()
        while self.cc_showprogress() is True:
            time.sleep(30)

    def cc_state(self, state):

        """
        Helper function for all CC operations
        """
        cmd = "./storcli64 /c%d/v0 %s cc force" % (self.controller, state)
        self.check_pass(cmd, "Failed to %s CC" % state)
        time.sleep(10)


if __name__ == "__main__":
    main()
