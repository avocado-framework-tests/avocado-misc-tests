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
# Copyright: 2016 IBM
# Author: Pavithra <pavrampu@linux.vnet.ibm.com>

import os
from shutil import copyfile
from avocado import Test
from avocado.utils import process, distro
from avocado import skipIf, skipUnless
from avocado.utils.software_manager import SoftwareManager

IS_POWER_NV = 'PowerNV' in open('/proc/cpuinfo', 'r').read()
IS_KVM_GUEST = 'qemu' in open('/proc/cpuinfo', 'r').read()


class RASTools(Test):

    """
    This test checks various RAS tools:
    """
    fail_cmd = list()

    def run_cmd(self, cmd):
        cmd_result = process.run(cmd, ignore_status=True, sudo=True,
                                 shell=True)
        if cmd_result.exit_status != 0:
            self.fail_cmd.append(cmd)
        return

    def error_check(self):
        if len(self.fail_cmd) > 0:
            for cmd in range(len(self.fail_cmd)):
                self.log.info("Failed command: %s" % self.fail_cmd[cmd])
            self.fail("RAS: Failed commands are: %s" % self.fail_cmd)

    @skipUnless("ppc" in distro.detect().arch,
                "supported only on Power platform")
    def setUp(self):
        sm = SoftwareManager()
        for package in ("ppc64-diag", "powerpc-utils", "lsvpd", "ipmitool"):
            if not sm.check_installed(package) and not sm.install(package):
                self.cancel("Fail to install %s required for this test." %
                            package)

    @staticmethod
    def run_cmd_out(cmd):
        return process.system_output(cmd, shell=True,
                                     ignore_status=True,
                                     sudo=True).decode("utf-8").strip()


    @skipIf(IS_POWER_NV, "Skipping test in PowerNV platform")
    def test9_ofpathname(self):
        """
        ofpathname translates the device name between logical name and Open
        Firmware name
        """
        self.log.info("===============Executing ofpathname tool test=========="
                      "=====")
        self.run_cmd("ofpathname -h")
        self.run_cmd("ofpathname -V")
        disk_name = self.run_cmd_out("df -h | egrep '(s|v)da[1-8]' |"
                                     " tail -1 | cut -d' ' -f1")
        self.run_cmd("ofpathname -V")
        disk_name = self.run_cmd_out("df -h | egrep '(s|v)da[1-8]' | "
                                     "tail -1 | cut -d' ' -f1")
        if disk_name:
            self.run_cmd("ofpathname %s" % disk_name)
            of_name = self.run_cmd_out("ofpathname %s"
                                       % disk_name)
            self.run_cmd("ofpathname -l %s" % of_name.split(':')[0])
        self.error_check()

