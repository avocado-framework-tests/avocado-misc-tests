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

from avocado import Test
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import process
from avocado import main
from avocado.utils import distro


class Arcconftest(Test):
    """
    Covers functionality relavent to device settings.
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
        self.http_path = self.params.get('http_path')
        self.tool_name = self.params.get('tool_name')
        self.option = self.params.get("option")
        self.option_args = self.params.get("option_args")
        self.option_args2 = self.params.get("option_args2")

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
           self.tool_name is '' or self.http_path is '':
            self.cancel(" please ensure yaml parameters are not empty or \
                       the total device should be more than 1")
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
            if process.system(cmd, ignore_status=True, shell=True) == 0:
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
        cmd = "arcconf getconfig %s PD" % self.crtl_no
        self.check_pass(cmd, "Failed to display PMC disk details")
        loop_count = 0
        disk_val = ""
        # pick only first two disks
        for disk in self.disk_no[:2]:
            loop_count += 1
            disk_val += " %s %s" % (self.channel_no, disk.strip())
            # test logicaldrive specific options
            if "setname" in self.option or "setboot" in self.option:
                if loop_count == 2:
                    # create logical drive
                    cmd = "arcconf create %s logicaldrive MAX 0 %s"\
                        % (self.crtl_no, disk_val)
                    self.check_pass(cmd, "Failed to run %s" % cmd)
                    if "setname" in self.option:
                        cmd = "%s %s %s %s %s" % (self.option,
                                                  self.crtl_no,
                                                  self.option_args,
                                                  self.logicaldrive,
                                                  self.option_args2)
                    else:
                        cmd = "%s %s %s %s" % (self.option,
                                               self.crtl_no,
                                               self.option_args,
                                               self.logicaldrive)
                    self.check_pass(cmd, "Failed to run %s" % cmd)
            else:
                # Run disk specific test for one drive
                if loop_count == 1:
                    if "setphy" in self.option:
                        cmd = "%s %s %s" % (self.option, self.crtl_no,
                                            self.option_args)
                    else:
                        cmd = "%s %s %s %s %s" % (self.option,
                                                  self.crtl_no,
                                                  self.option_args,
                                                  disk_val,
                                                  self.option_args2)
                    self.check_pass(cmd, "Failed to run %s" % cmd)

    def cmdop_list(self, cmd):
        """
        Function returns the output of a command
        """
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
