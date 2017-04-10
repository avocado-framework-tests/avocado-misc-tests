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
# Copyright: 2017 IBM
# Author: Pavithra <pavrampu@linux.vnet.ibm.com>

import os
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils import distro
from avocado.utils.software_manager import SoftwareManager


class sosreport_test(Test):

    is_fail = 0

    def run_cmd(self, cmd):
        self.log.info("executing ============== %s =================" % cmd)
        if process.system(cmd, ignore_status=True, sudo=True):
            self.log.info("%s command failed" % cmd)
            self.is_fail += 1
        return

    def setUp(self):
        if "ppc" not in os.uname()[4]:
            self.skip("supported only on Power platform")
        dist = distro.detect()
        sm = SoftwareManager()
        if dist.name == 'Ubuntu':
            if not sm.check_installed("sosreport") and not sm.install("sosreport"):
                self.skip("Fail to install sosreport required for this test.")
        if dist.name == 'redhat':
            if not sm.check_installed("sos") and not sm.install("sos"):
                self.skip("Fail to install sos package required for this test.")
        if distro.detect().name == 'SuSE':
            self.skip('sosreport is not supported on SLES')

    def test(self):
        self.log.info(
            "===============Executing sosreport tool test===============")
        self.run_cmd("sosreport -h")
        self.run_cmd("sosreport -l")
        self.run_cmd("sosreport --batch --case-id=test123 -n memory,samba")
        if process.system_output("sosreport --batch --case-id=test123 -n libraries | "
                                 "grep libraries", shell=True, ignore_status=True):
            self.is_fail += 1
            self.log.info("--skip-plugins option failed")
        self.run_cmd("sosreport --batch --case-id=test123 -e ntp,numa,snmp")
        if 'sendmail' not in process.system_output("sosreport --batch --case-id=test123 -e sendmail | "
                                                   "grep sendmail", shell=True, ignore_status=True):
            self.is_fail += 1
            self.log.info("--enable-plugins option failed")
        self.run_cmd("sosreport --batch --case-id=test123 -o pci,powerpc,procenv,process,processor,kdump")
        if process.system_output("sosreport --batch --case-id=test123 -o cups | "
                                 "grep kernel", shell=True, ignore_status=True):
            self.is_fail += 1
            self.log.info("--only-plugins option failed")
        self.run_cmd("sosreport --batch --case-id=test123 -o dlm -k dlm.lockdump")
        self.run_cmd("sosreport --batch --case-id=test123 -k filesys.dumpe2fs=on")
        self.run_cmd("sosreport --batch --case-id=test123 --log-size=2000")
        self.run_cmd("sosreport --batch --case-id=test123 -a")
        self.run_cmd("sosreport --batch --case-id=test123 --all-logs")
        self.run_cmd("sosreport --batch --case-id=test123 --build")
        dir_name = process.system_output("sosreport --batch --case-id=test123 --build | "
                                         "grep located | cut -d':' -f2", shell=True, ignore_status=True).strip()
        if not os.path.isdir(dir_name):
            self.is_fail += 1
            self.log.info("--build option failed")
        self.run_cmd("sosreport --batch --case-id=test123 -v")
        self.run_cmd("sosreport --batch --case-id=test123 --verify")
        if process.system_output("sosreport --batch --case-id=test123 --quiet -e ntp,numa1", shell=True, ignore_status=True):
            self.is_fail += 1
            self.log.info("--quiet option failed")
        self.run_cmd("sosreport --batch --case-id=test123 --debug")
        if 'test123' not in process.system_output("sosreport --batch --ticket-number=test123  | "
                                                  "grep tar.xz", shell=True, ignore_status=True):
            self.is_fail += 1
            self.log.info("--ticket-number option failed")
        self.run_cmd("sosreport --list-profiles")
        self.run_cmd("sosreport --batch --case-id=test123 -p boot,memory")
        if 'java' not in process.system_output("sosreport --batch --case-id=test123 -p webserver | "
                                               "grep Running | tail -1", shell=True, ignore_status=True):
            self.is_fail += 1
            self.log.info("--profile option failed")
        if 'testname' not in process.system_output("sosreport --batch --case-id=test123 --name=testname  | "
                                                   "grep tar.xz", shell=True, ignore_status=True):
            self.is_fail += 1
            self.log.info("--name option failed")
        self.run_cmd("sosreport --batch --case-id=test123 --config-file=/etc/sos.conf")
        file_name = process.system_output("sosreport --batch --case-id=test123 --tmp-dir=/root | "
                                          "grep root | tail -1", shell=True, ignore_status=True).strip()
        if not os.path.exists(file_name):
            self.is_fail += 1
            self.log.info("--tmp-dir option failed")
        file_name_bz2 = process.system_output("sosreport --batch --case-id=test123 -z bzip2 | "
                                              "grep tar.bz2", shell=True, ignore_status=True).strip()
        if not os.path.exists(file_name_bz2):
            self.is_fail += 1
            self.log.info("-z bzip2 option failed")
        file_name_gz = process.system_output("sosreport --batch --case-id=test123 -z gzip | "
                                             "grep tar.gz", shell=True, ignore_status=True).strip()
        if not os.path.exists(file_name_gz):
            self.is_fail += 1
            self.log.info("-z gzip option failed")
        file_name_xz = process.system_output("sosreport --batch --case-id=test123 -z xz | "
                                             "grep tar.xz", shell=True, ignore_status=True).strip()
        if not os.path.exists(file_name_xz):
            self.is_fail += 1
            self.log.info("-z xz option failed")
        file_name_xz2 = process.system_output("sosreport --batch --case-id=test123 -z auto | "
                                              "grep tar.xz", shell=True, ignore_status=True).strip()
        if not os.path.exists(file_name_xz2):
            self.is_fail += 1
            self.log.info("-z auto option failed")
        self.run_cmd("sosreport --batch --case-id=test123 --chroot=always")
        self.run_cmd("sosreport --batch --case-id=test123 --chroot=auto")
        self.run_cmd("sosreport --batch --case-id=test123 --chroot=never")
        dir_name = process.system_output("sosreport --no-report --batch --build | "
                                         "grep located | cut -d':' -f2", shell=True, ignore_status=True).strip()
        sosreport_dir = os.path.join(dir_name, 'sos_reports')
        if os.listdir(sosreport_dir) != []:
            self.is_fail += 1
            self.log.info("--no-report option failed")
        self.run_cmd("sosreport --batch --case-id=test123 -s /home/")
        process.run("rm -rf /tmp/sosreport*test123*")
        process.run("rm -rf /root/sosreport*test123*")
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in sosreport tool verification" %
                      self.is_fail)


if __name__ == "__main__":
    main()
