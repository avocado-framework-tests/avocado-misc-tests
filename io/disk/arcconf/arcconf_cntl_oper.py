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
    Covers functionality relavent to controller settings.
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
        self.pci_id = self.params.get('pci_id', default="").split(",")
        self.http_path = self.params.get('http_path')
        self.tool_name = self.params.get('tool_name')
        self.firmware_path = self.params.get('firmware_path')
        self.firmware_name = self.params.get('firmware_name')
        self.option = self.params.get("option")
        self.option_args = self.params.get("option_args")

        # Gets the list of PCIIDs on the system
        cmd = r'for device in $(lspci | awk \'{print $1}\') ; do echo \
              $(lspci -vmm -nn -s $device | grep "\[" | awk \'{print $NF}\' \
              | sed -e "s/\]//g" | sed -e "s/\[//g" | \\tr \'\\n\' \' \' \
              | awk \'{print $2,$3,$4,$5}\') ; done'
        pci_id_formatted = []
        for i in self.cmdop_list(cmd).splitlines():
            pci_id_formatted.append(str(i.replace(" ", ":")))

        # check if all the yaml parameters are entered
        if self.crtl_no is '' or self.pci_id is '' or self.tool_name \
           is '' or self.http_path is '' or self.firmware_path\
           is '' or self.firmware_name is '':
            self.cancel(" please ensure yaml parameters are not empty")
        elif self.comp(self.pci_id, pci_id_formatted) == 1:
            self.cancel(" Test skipped!!, PMC controller not available")

        http_repo1 = "%s%s" % (self.firmware_path, self.firmware_name)
        self.repo1 = self.fetch_asset(http_repo1, expire='10d')
        self.repo1 = "%s.ufi" % self.repo1

        detected_distro = distro.detect()
        installed_package = "Arcconf"
        if detected_distro.name == "Ubuntu":
            installed_package = "arcconf"
        if not smm.check_installed(installed_package):
            if detected_distro.name == "Ubuntu":
                http_repo = "%s%s.deb" % (self.http_path, self.tool_name)
                self.repo = self.fetch_asset(http_repo, expire='10d')
                cmd = "dpkg -i %s" % self.repo
            else:
                http_repo = "%s%s.rpm" % (self.http_path, self.tool_name)
                self.repo = self.fetch_asset(http_repo, expire='10d')
                cmd = "rpm -ivh %s" % self.repo
            if process.system(cmd, ignore_status=True, shell=True) != 0:
                self.cancel("Unable to install arcconf")

    def test(self):
        """
        Main function
        """
        self.log.info("PMC controller details for ==> %s"
                      % self.crtl_no)
        cmd = "arcconf getconfig %s AD" % self.crtl_no
        self.check_pass(cmd, "Failed to display PMC controller details")

        if "SETCONFIG" in self.option:
            # reset the config only if no OS drive found
            cmd = "lsscsi  | grep LogicalDrv | awk \'{print $7}\'"
            drive = self.cmdop_list(cmd)
            if drive != "":
                cmd = "df -h /boot | grep %s" % drive
                if process.system(cmd, timeout=300, ignore_status=True,
                                  shell=True) != 0:
                    cmd = "%s %s %s" % (self.option, self.crtl_no,
                                        self.option_args)
        elif "CONFIG" in self.option or "SAVESUPPORTARCHIVE" in self.option:
            cmd = "%s %s" % (self.option, self.option_args)
        elif "ROMUPDATE" in self.option:
            cmd = "%s %s %s %s" % (self.option, self.option_args,
                                   self.crtl_no, self.repo1)
        else:
            cmd = "%s %s %s" % (self.option, self.crtl_no, self.option_args)
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
        remove the log files
        """
        if "SAVECONFIG" not in self.option:
            cmd = "rm -rf /tmp/arcconf_cntl*"
            self.check_pass(cmd, "Failed to remove temporary files")


if __name__ == "__main__":
    main()
