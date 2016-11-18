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
arcconf - Array configuration utility for PMC-Sierra
(Microsemi) Controllers.
"""

import subprocess
import time
from avocado import Test
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import process
from avocado import main


class Arcconftest(Test):

    """
    arcconf_raid_oper.py covers functionality like RAID
    creation, deletion, Physical disk & logical disk format,
    and gather controller status using getconfig.
    """

    def setUp(self):

        """
        Checking if the required packages are installed,
        if not found specific packages will be installed.
        """

        smm = SoftwareManager()
        if not smm.check_installed("arcconf"):
            self.log.info("arcconf should be installed prior to the test")
            if smm.install("arcconf") is False:
                self.skip("Unable to install arcconf")
        self.crtl_no = self.params.get('crtl_no')
        self.channel_no = self.params.get('channel_no')
        self.disk_no = self.params.get('disk_no', default="").split(",")
        self.pci_id = self.params.get('pci_id', default="").split(",")
        self.logicaldrive = self.params.get('logicaldrive')
        self.diskoverwrite = self.params.get('diskoverwrite')
        self.disk_count = len(self.disk_no)
        # Gets the list of PCIIDs on the system
        cmd = 'for device in $(lspci | awk \'{print $1}\') ; do echo \
              $(lspci -vmm -nn -s $device | grep "\[" | awk \'{print $NF}\' \
              | sed -e "s/\]//g" | sed -e "s/\[//g" | tr \'\\n\' \' \' \
              | awk \'{print $2,$3,$4,$5}\') ; done'

        pci_id = self.cmdop_list(cmd, 'Y')
        pci_id_formatted = []
        pci_host_raw = self.cmdop_list('lspci -nn', 'Y')
        pci_host = []

        for i in range(0, len(pci_id)):
            pci_id_formatted.append(str(pci_id[i]).replace(" ", ":"))
            pci_host.append(str(pci_host_raw[i].replace(
                pci_id_formatted[i][:8], pci_id_formatted[i])))
        # check if all the yaml parameters are entered
        if self.crtl_no is '' or self.channel_no is '' or self.disk_no is \
           '' or self.pci_id is '' or self.disk_count <= 1:
            self.skip(" Test skipped!!, please ensure yaml parameters are \
            entered or disk count is more than 1")
        # ensure if the correct card is being tested
        elif self.comp(self.pci_id, pci_id_formatted) == 1:
            self.skip(" Test skipped!!, PMC controller not available")

        cmd = "lsscsi  | grep LogicalDrv | awk \'{print $7}\'"
        os_drive = self.cmdop_list(cmd, 'N')

        if self.diskoverwrite == 'Y' and os_drive != "":
            # Delete a logical drive only if it is not OS drive
            cmd = "df -h /boot | grep %s" % os_drive
            if process.system(cmd, timeout=300, ignore_status=True,
                              shell=True) == 0:
                self.skip("Test Skipped!! OS disk requested for removal")

            self.log.info("Deleting the default logical drive %s" %
                          (self.logicaldrive))
            cmd = "echo y | arcconf delete %s logicaldrive %s" % \
                (self.crtl_no, self.logicaldrive)
            self.check_pass(cmd, "Failed to delete Logical drive")

    def test(self):
        """
        Main function
        """
        test_type = self.params.get("option")
        self.log.info("Testing with option %s" % test_type)
        self.basictest(test_type)

    def basictest(self, type_name):
        """
        Basic raid operations like getconfig, create, delete and
        format are covered.
        """
        self.log.info("Displaying PMC details for device ==> %s"
                      % self.crtl_no)
        cmd = "arcconf getconfig %s AL" % self.crtl_no
        self.check_pass(cmd, "Failed to display PMC device details")

        disk_val = ""
        loop_count = 0
        for val in self.disk_no:
            disk_val += " %s %s" % (self.channel_no, val)
            loop_count += 1
            # Format all the physical disk drives
            cmd = "echo y | arcconf task start %s device %s %s \
                  INITIALIZE" % (self.crtl_no, self.channel_no, val)
            self.check_pass(cmd, "Failed to Format drive")

            # Raid create
            if loop_count > 1:
                self.raid_create(disk_val, loop_count, type_name)

    def raid_create(self, disk_data, cnt, type_name1):
        """
        function which decides on RAID level
        TODO 50, 60 and 5EE
        """
        self.log.info(" Raid creation with Drives %s, option %s"
                      % (cnt, type_name1))
        if cnt == 2:
            raid = "0"
            self.raid_exec(type_name1, disk_data, cnt, raid)
            time.sleep(10)

            raid = "1"
            self.raid_exec(type_name1, disk_data, cnt, raid)
            time.sleep(10)

        elif cnt == 3:
            raid = "1E"
            self.raid_exec(type_name1, disk_data, cnt, raid)
            time.sleep(10)

        elif cnt == 4:
            raid = "10"
            self.raid_exec(type_name1, disk_data, cnt, raid)
            time.sleep(10)

            raid = "5"
            self.raid_exec(type_name1, disk_data, cnt, raid)
            time.sleep(10)

            raid = "6"
            self.raid_exec(type_name1, disk_data, cnt, raid)
            time.sleep(10)

    def raid_exec(self, name1, dsk_data, cnt, raid):
        """
        function to create different raid functions
        """
        self.log.info(" Creating RAID %s with drives %s"
                      % (raid, dsk_data))
        cmd = "echo y | arcconf create %s LOGICALDRIVE %s MAX %s %s" \
            % (self.crtl_no, name1, raid, dsk_data)
        self.check_pass(cmd, "Failed to create RAID %s" % raid)

        if raid == 0:
            self.format_logical(cnt)
        self.make_fs()
        time.sleep(10)

        self.log.info(" Deleting RAID %s with drives %s"
                      % (raid, dsk_data))
        cmd = "echo y | arcconf delete %s logicaldrive %s" % \
            (self.crtl_no, self.logicaldrive)
        self.check_pass(cmd, "Failed to delete RAID %s" % raid)

    def format_logical(self, count1):
        """
        format logical drive
        """
        self.log.info("Formatting Logical drive %s, having %s drives"
                      % (self.logicaldrive, count1))
        cmd = "echo y | arcconf task start %s LOGICALDRIVE %s CLEAR" \
            % (self.crtl_no, self.logicaldrive)
        self.check_pass(cmd, "Failed to format Logical Drive")
        cmd = "arcconf getconfig %s LD" % self.crtl_no
        self.check_pass(cmd, "Failed to display Logical device details")

    def make_fs(self):
        """
        creates filesystem
        """
        cmd = "lsscsi  | grep LogicalDrv | awk \'{print $7}\'"
        drive = self.cmdop_list(cmd, 'N')

        self.log.info("Creating file system on %s" % (drive))

        cmd1 = "echo y | mkfs.ext4 %s" % drive
        self.check_pass(cmd1, "Failed to create filesystem")

        cmd2 = "mount %s /mnt" % drive
        self.check_pass(cmd2, "Failed to mount filesystem")

        cmd3 = "cd /mnt && dd if=/dev/random of=Gfile.txt bs=3M count=1"
        self.check_pass(cmd3, "Failed to create file")

        cmd4 = "cd / && umount %s" % drive
        self.check_pass(cmd4, "Failed to unmount file")

    def check_pass(self, cmd, errmsg):
        """
        Function to check if the cmd is successful or not
        """
        if process.system(cmd, timeout=3200, ignore_status=True,
                          shell=True) != 0:
            self.fail(errmsg)

    @classmethod
    def cmdop_list(cls, cmd, disk_type):
        """
        Function returns the output of a command
        """
        val = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
        if disk_type == 'Y':
            val = val.stdout.read().strip().split('\n')
        else:
            val = val.stdout.read().rstrip()
        return val

    @classmethod
    def comp(cls, list1, list2):
        """
        compares two lists, if match found returns 0
        """
        for val in list1:
            if val in list2:
                return 0
        return 1


if __name__ == "__main__":
    main()
