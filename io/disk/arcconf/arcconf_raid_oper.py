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

import time
from avocado import Test
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import process
from avocado import main
from avocado.utils import distro


class Arcconftest(Test):

    """
    Covers functionality relavent to RAID operations like creation,
    deletion, Physical & logical disk format and status information.
    """

    def setUp(self):
        """
        Checking if the required packages are installed,
        if not found specific packages will be installed.
        """
        smm = SoftwareManager()
        if not smm.check_installed("lsscsi") and not smm.install("lsscsi"):
            self.cancel("Unable to install lsscsi")
        self.crtl_no = self.params.get('crtl_no')
        self.channel_no = self.params.get('channel_no')
        self.disk_no = self.params.get('disk_no', default="").split(",")
        self.pci_id = self.params.get('pci_id', default="").split(",")
        self.logicaldrive = self.params.get('logicaldrive')
        self.diskoverwrite = self.params.get('diskoverwrite')
        self.fs_type = self.params.get('fs_type')
        self.mount_point = self.params.get('mount_point')
        self.http_path = self.params.get('http_path')
        self.tool_name = self.params.get('tool_name')

        # Gets the list of PCIIDs on the system
        cmd = r'for device in $(lspci | awk \'{print $1}\') ; do echo \
              $(lspci -vmm -nn -s $device | grep "\[" | awk \'{print $NF}\' \
              | sed -e "s/\]//g" | sed -e "s/\[//g" | tr \'\\n\' \' \' \
              | awk \'{print $2,$3,$4,$5}\') ; done'
        pci_id = self.cmdop_list(cmd)
        pci_id_formatted = []
        for i in pci_id.splitlines():
            pci_id_formatted.append(str(i.replace(" ", ":")))

        # check if all the yaml parameters are entered
        if self.crtl_no is '' or self.channel_no is '' or self.disk_no is \
           '' or self.pci_id is '' or len(self.disk_no) <= 1 or \
           self.fs_type is '' or self.mount_point is '' or self.tool_name \
           is '' or self.http_path is '':
            self.cancel(" Test skipped!!, please ensure yaml parameters are \
            entered or disk count is more than 1")
        elif self.comp(self.pci_id, pci_id_formatted) == 1:
            self.cancel(" Test skipped!!, PMC controller not available")

        detected_distro = distro.detect()
        if not smm.check_installed("Arcconf"):
            if detected_distro.name == "Ubuntu":
                http_repo = "%s%s.deb" % (self.http_path, self.tool_name)
                self.repo = self.fetch_asset(http_repo, expire='10d')
                cmd = "dpkg -i %s" % self.repo
            else:
                http_repo = "%s%s.rpm" % (self.http_path, self.tool_name)
                self.repo = self.fetch_asset(http_repo, expire='10d')
                cmd = "rpm -ivh %s" % self.repo
            if process.run(cmd, shell=True) == 0:
                self.cancel("Unable to install arcconf")

        cmd = "lsscsi  | grep LogicalDrv | awk \'{print $7}\'"
        self.os_drive = self.cmdop_list(cmd)

        if self.diskoverwrite == 'Y' and self.os_drive != "":
            # Delete a logical drive only if it is not OS drive
            cmd = "df -h /boot | grep %s" % self.os_drive
            if process.system(cmd, timeout=300, ignore_status=True,
                              shell=True) == 0:
                self.cancel("Test Skipped!! OS disk requested for removal")

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
        self.log.info("PMC controller details for device ==> %s"
                      % self.crtl_no)
        cmd = "arcconf getconfig %s AL" % self.crtl_no
        self.check_pass(cmd, "Failed to display PMC device details")

        disk_val = ""
        disk_pair = []
        loop_count = 0
        for val in self.disk_no:
            val = val.strip()
            disk_val += " %s %s" % (self.channel_no, val)
            disk_pair += "%s" % (val)
            loop_count += 1

            # Raid create
            if loop_count > 1:
                self.raid_create(disk_val, loop_count, type_name, disk_pair)

    def raid_create(self, disk_data, cnt, type_name1, pair):
        """
        function which decides on RAID level
        """
        self.log.info(" Raid creation with %s Drives, option %s"
                      % (cnt, type_name1))
        if cnt == 2:
            raid_level = ["0", "1"]
        elif cnt == 3:
            raid_level = ["1E"]
        elif cnt == 4:
            raid_level = ["10", "5", "6"]
        elif cnt == 6:
            raid_level = ["50"]
        elif cnt == 8:
            raid_level = ["60"]

        for raid_type in raid_level:
            self.raid_exec(type_name1, disk_data, cnt, raid_type, pair)
            time.sleep(10)

    def raid_exec(self, name1, dsk_data, cnt, raid, pair1):
        """
        function to create different raid functions
        """
        for val1 in pair1:
            # Format all the physical disk drives
            self.log.info(" Formatting physical drives ==>  %s"
                          % val1)
            cmd = "echo y | arcconf task start %s device %s %s \
                  INITIALIZE" % (self.crtl_no, self.channel_no, val1)
            self.check_pass(cmd, "Failed to Format drive")

        self.log.info(" Creating RAID %s with drives %s"
                      % (raid, dsk_data))
        cmd = "echo y | arcconf create %s LOGICALDRIVE %s MAX %s %s" \
            % (self.crtl_no, name1, raid, dsk_data)
        self.check_pass(cmd, "Failed to create RAID %s" % raid)

        if raid == 0:
            self.format_logical(cnt)
        self.make_fs(self.fs_type, self.mount_point)
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

    def make_fs(self, fs_type, mount_drv):
        """
        creates filesystem
        """
        cmd = "lsscsi | grep LogicalDrv | awk '{print $7}'"
        drive = self.cmdop_list(cmd)

        if drive != "":
            cmd = "echo y | mkfs.%s %s && sleep 5 && mount %s %s && \
                  sleep 5 && cd %s && dd if=/dev/random of=Gfile.txt \
                  bs=3M count=1 && cd / && sleep 5 && \
                  umount %s" % (fs_type, drive, drive, mount_drv,
                                mount_drv, drive)
            self.check_pass(cmd, "Failed to create filesystem")
        else:
            self.log.info(" Filesystem creation skipped!!")

    def check_pass(self, cmd, errmsg):
        """
        Function to check if the cmd is successful or not
        """
        if process.system(cmd, timeout=3200, ignore_status=True,
                          shell=True) != 0:
            self.fail(errmsg)

    def cmdop_list(self, cmd):
        """
        Function returns the output of a command
        """
        val = process.run(cmd, shell=True, allow_output_check='stdout')
        if val.exit_status:
            self.fail("cmd %s Failed" % (cmd))
        return val.stdout.rstrip()

    @classmethod
    def comp(cls, list1, list2):
        """
        compares two lists, if match found returns 0
        """
        for val in list1:
            if val in list2:
                return 0
        return 1

    def tearDown(self):
        """
        unmount or delete logical device
        """
        cmd = "mount | grep %s" % self.mount_point
        if process.system(cmd, timeout=300, ignore_status=True,
                          shell=True) == 0:
            cmd = "unmount %s" % self.mount_point
            self.check_pass(cmd, "Failed to cleanup mount point")

        cmd = "lsscsi  | grep LogicalDrv | awk \'{print $7}\'"
        drive = self.cmdop_list(cmd)

        if drive != "":
            # Delete a logical drive only if it is not OS drive
            cmd = "df -h /boot | grep %s" % drive
            if process.system(cmd, timeout=300, ignore_status=True,
                              shell=True) != 0:
                cmd = "echo y | arcconf delete %s logicaldrive %s" % \
                      (self.crtl_no, self.logicaldrive)
                self.check_pass(cmd, "Failed to cleanup Logical drive")


if __name__ == "__main__":
    main()
