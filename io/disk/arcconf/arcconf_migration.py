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
    Covers Migration and rebuilding functionality.
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
        self.disk_size = self.params.get('disk_size')
        self.http_path = self.params.get('http_path')
        self.tool_name = self.params.get('tool_name')
        self.migration_sleep = self.params.get('migration_sleep')
        self.initial_raid = self.params.get('initial_raid')
        self.migrate_raid = self.params.get('migrate_raid',
                                            default="").split(",")
        self.disk_initial = self.params.get('disk_initial')
        self.disk_migrated = self.params.get('disk_migrated')
        self.spare_drive = self.params.get('spare_drive')

        # Gets the list of PCIIDs on the system
        cmd = r'for device in $(lspci | awk \'{print $1}\') ; do echo \
              $(lspci -vmm -nn -s $device | grep "\[" | awk \'{print $NF}\' \
              | sed -e "s/\]//g" | sed -e "s/\[//g" | tr \'\\n\' \' \' \
              | awk \'{print $2,$3,$4,$5}\') ; done'
        pci_id_formatted = []
        for i in self.cmdop_list(cmd).splitlines():
            pci_id_formatted.append(str(i.replace(" ", ":")))

        # check if all the yaml parameters are entered
        if self.crtl_no is '' or self.channel_no is '' or self.disk_no is \
           '' or self.pci_id is '' or len(self.disk_no) <= 1 or \
           self.disk_size is '' or self.tool_name is '' or self.http_path is \
           '' or self.initial_raid is '' or self.migrate_raid is '' or \
           self.disk_initial is '' or self.disk_migrated is '' or \
           len(self.initial_raid) > 1 or self.migration_sleep is '':
            self.cancel(" please ensure yaml parameters are not empty or \
                       the total device should be more than 1")
        elif self.comp(self.pci_id, pci_id_formatted) == 1:
            self.cancel(" Test skipped!!, PMC controller not available")

        if len(self.disk_no) < int(self.disk_initial) or \
           len(self.disk_no) < int(self.disk_migrated):
            self.cancel("Cannot Migrate, please check the prerequisite")

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
            if process.system(cmd, ignore_status=True, shell=True) == 0:
                self.cancel("Unable to install arcconf")

        self.os_drive = self.cmdop_list("OS")

        if self.diskoverwrite == 'Y' and self.os_drive != "":
            # Delete a logical drive only if it is not OS drive
            self.logicalDrive_remove(self.os_drive, "0")

    def test(self):
        """
        Main function
        """
        disk_val1 = ""
        disk_val2 = ""
        # create the inital disk required for raid creation
        loop_count = 0
        for disk in self.disk_no:
            loop_count += 1
            disk_val1 += " %s %s" % (self.channel_no, disk.strip())
            if loop_count == 2 and self.initial_raid in ('0', '1'):
                break
            if loop_count == 3 and self.initial_raid == '5':
                break
            if loop_count == 4 and self.initial_raid in ('6', '10'):
                break
        # create the disk required for migration
        loop_count = 0
        for disk in self.disk_no:
            loop_count += 1
            disk_val2 += " %s %s" % (self.channel_no, disk.strip())
            if loop_count == int(self.disk_migrated):
                break
        # Start migration
        for migrate in self.migrate_raid:
            # create logical drive
            self.log.info("Creating RAID %s" % self.initial_raid)
            cmd = "echo y | arcconf create %s logicaldrive %s %s %s"\
                  % (self.crtl_no, self.disk_size,
                     self.initial_raid, disk_val1)
            self.check_pass(cmd, "Failed to run %s" % cmd)

            time.sleep(int(self.migration_sleep))

            # rebuild tests
            if self.spare_drive != "" and self.initial_raid == '1':
                cmd = "echo y | arcconf setstate %s device %s %s HSP" % \
                      (self.crtl_no, self.channel_no, self.spare_drive)
                self.check_pass(cmd, "Failed to run %s" % cmd)

                time.sleep(int(self.migration_sleep))

                for condition in ("DDD", "RDY"):
                    cmd = "echo y | arcconf setstate %s device %s %s %s"\
                          % (self.crtl_no, self.channel_no,
                             self.disk_no[1], condition)
                    self.check_pass(cmd, "Failed to run %s" % cmd)
                    self.logical_print()
                    time.sleep(int(self.migration_sleep))

            # Migration tests
            else:
                self.log.info("Migrating from RAID %s to %s" %
                              (self.initial_raid, migrate))
                cmd = "echo y | arcconf MODIFY %s FROM %s TO %s %s %s" % \
                      (self.crtl_no, self.logicaldrive,
                       self.disk_size, migrate, disk_val2)
                self.check_pass(cmd, "Failed to run %s" % cmd)
                time.sleep(int(self.migration_sleep))
                self.logical_print()

            if self.cmdop_list("OS"):
                cmd = "echo y | arcconf delete %s logicaldrive \
                       %s" % (self.crtl_no, self.logicaldrive)
                self.check_pass(cmd, "Logical drive deletion failed")

            time.sleep(int(self.migration_sleep))

            # restore global spare only after logical drive delete
            if self.spare_drive != "":
                cmd = "echo y | arcconf setstate %s device %s %s RDY " % \
                    (self.crtl_no, self.channel_no, self.spare_drive)
                self.check_pass(cmd, "Failed to run %s" % cmd)

    def logical_print(self):
        """
        Function to print logical drive status
        """
        cmd = "arcconf getconfig %s LD" % (self.crtl_no)
        self.check_pass(cmd, "Logical drive getconfig failed")

    def cmdop_list(self, cmd):
        """
        Function returns the output of a command
        """
        if cmd == 'OS':
            cmd = "lsscsi  | grep LogicalDrv | awk \'{print $7}\'"
        val = process.run(cmd, shell=True, ignore_status=True,
                          allow_output_check='stdout')
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

    def check_pass(self, cmd, errmsg):
        """
        Function to check if the cmd is successful or not
        """
        if process.system(cmd, timeout=3200, ignore_status=True,
                          shell=True) != 0:
            self.fail(errmsg)

    def tearDown(self):
        """
        Delete logical device
        """
        drive = self.cmdop_list("OS")

        if drive != "":
            # Delete a logical drive only if it is not OS drive
            self.logicalDrive_remove(drive, "1")

    def logicalDrive_remove(self, device, cond):
        """
        Delete logical device
        """
        cmd = "df -h /boot | grep %s" % device
        if process.system(cmd, timeout=300, ignore_status=True,
                          shell=True) != 0:
            cmd = "echo y | arcconf delete %s logicaldrive %s" % \
                  (self.crtl_no, self.logicaldrive)
            self.check_pass(cmd, "Failed to cleanup Logical drive")
        else:
            if cond == 0:
                self.cancel("Test Skipped!! OS disk requested for removal")


if __name__ == "__main__":
    main()
