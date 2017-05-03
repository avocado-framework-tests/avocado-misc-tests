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
import tempfile
import shutil
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils import distro
from avocado.utils.software_manager import SoftwareManager


class sosreport_test(Test):

    is_fail = 0

    def run_cmd(self, cmd):
        self.log.info("executing ============== %s =================", cmd)
        if process.system(cmd, ignore_status=True, sudo=True):
            self.log.info("%s command failed", cmd)
            self.is_fail += 1
        return

    def run_cmd_out(self, cmd):
        return process.system_output(cmd, shell=True, ignore_status=True, sudo=True)

    def setUp(self):
        dist = distro.detect()
        sm = SoftwareManager()
        sos_pkg = ""
        if not process.system("sosreport", ignore_status=True, sudo=True):
            self.log.info("sosreport is installed")
        elif dist.name == 'Ubuntu':
            sos_pkg = 'sosreport'
        # FIXME: "redhat" as the distro name for RHEL is deprecated
        # on Avocado versions >= 50.0.  This is a temporary compatibility
        # enabler for older runners, but should be removed soon
        elif dist.name in ['rhel', 'redhat']:
            sos_pkg = 'sos'
        else:
            self.skip("sosreport is not supported on this distro ")
        if sos_pkg and not sm.check_installed(sos_pkg) and not sm.install(sos_pkg):
            self.skip("Package %s is missing and could not be installed" % sos_pkg)

    def test(self):
        self.log.info(
            "===============Executing sosreport tool test===============")
        directory_name = tempfile.mkdtemp()
        self.run_cmd("sosreport -h")
        self.run_cmd("sosreport -l")
        list = self.params.get('list', default=['--all-logs'])
        for list_item in list:
            cmd = "sosreport --batch --tmp-dir=%s %s" % (directory_name, list_item)
            self.run_cmd(cmd)
        if self.run_cmd_out("sosreport --batch --tmp-dir=%s -n libraries | "
                            "grep libraries" % directory_name):
            self.is_fail += 1
            self.log.info("--skip-plugins option failed")
        self.run_cmd("sosreport --batch --tmp-dir=%s -e ntp,numa,snmp" % directory_name)
        if 'sendmail' not in self.run_cmd_out("sosreport --batch --tmp-dir=%s -e "
                                              "sendmail | grep sendmail" % directory_name):
            self.is_fail += 1
            self.log.info("--enable-plugins option failed")
        if "ppc" in os.uname()[4]:
            self.run_cmd("sosreport --batch --tmp-dir=%s -o "
                         "pci,powerpc,procenv,process,processor,kdump" % directory_name)
        if self.run_cmd_out("sosreport --batch --tmp-dir=%s -o cups | grep kernel" % directory_name):
            self.is_fail += 1
            self.log.info("--only-plugins option failed")
        dir_name = self.run_cmd_out("sosreport --batch --tmp-dir=%s --build | "
                                    "grep located | cut -d':' -f2" % directory_name).strip()
        if not os.path.isdir(dir_name):
            self.is_fail += 1
            self.log.info("--build option failed")
        self.run_cmd("sosreport --batch --tmp-dir=%s -v" % directory_name)
        self.run_cmd("sosreport --batch --tmp-dir=%s --verify" % directory_name)
        if self.run_cmd_out("sosreport --batch --tmp-dir=%s --quiet -e ntp,numa1" % directory_name):
            self.is_fail += 1
            self.log.info("--quiet option failed")
        self.run_cmd("sosreport --batch --tmp-dir=%s --debug" % directory_name)
        ticket_id = self.params.get('ticket_id', default='testid')
        if ticket_id not in self.run_cmd_out("sosreport --batch --ticket-number=%s  | "
                                             "grep tar.xz" % ticket_id):
            self.is_fail += 1
            self.log.info("--ticket-number option failed")
        case_id = self.params.get('case_id', default='testid')
        if case_id not in self.run_cmd_out("sosreport --batch --case-id=%s | "
                                           "grep tar.xz" % case_id):
            self.is_fail += 1
            self.log.info("--case-id option failed")
        self.run_cmd("sosreport --list-profiles")
        self.run_cmd("sosreport --batch --tmp-dir=%s -p boot,memory" % directory_name)
        if 'java' not in self.run_cmd_out("sosreport --batch --tmp-dir=%s -p webserver | "
                                          "grep Running | tail -1" % directory_name):
            self.is_fail += 1
            self.log.info("--profile option failed")
        if 'testname' not in self.run_cmd_out("sosreport --batch --tmp-dir=%s "
                                              "--name=testname | grep tar.xz" % directory_name):
            self.is_fail += 1
            self.log.info("--name option failed")
        self.run_cmd("sosreport --batch --tmp-dir=%s --config-file=/etc/sos.conf" % directory_name)
        file_name = self.run_cmd_out("sosreport --batch --tmp-dir=%s --tmp-dir=/root | "
                                     "grep root | tail -1" % directory_name).strip()
        if not os.path.exists(file_name):
            self.is_fail += 1
            self.log.info("--tmp-dir option failed")
        file_name_bz2 = self.run_cmd_out("sosreport --batch --tmp-dir=%s -z bzip2 | "
                                         "grep tar.bz2" % directory_name).strip()
        if not os.path.exists(file_name_bz2):
            self.is_fail += 1
            self.log.info("-z bzip2 option failed")
        file_name_gz = self.run_cmd_out("sosreport --batch --tmp-dir=%s -z gzip | "
                                        "grep tar.gz" % directory_name).strip()
        if not os.path.exists(file_name_gz):
            self.is_fail += 1
            self.log.info("-z gzip option failed")
        file_name_xz = self.run_cmd_out("sosreport --batch --tmp-dir=%s -z xz | "
                                        "grep tar.xz" % directory_name).strip()
        if not os.path.exists(file_name_xz):
            self.is_fail += 1
            self.log.info("-z xz option failed")
        file_name_xz2 = self.run_cmd_out("sosreport --batch --tmp-dir=%s -z auto | "
                                         "grep tar.xz" % directory_name).strip()
        if not os.path.exists(file_name_xz2):
            self.is_fail += 1
            self.log.info("-z auto option failed")
        md5_sum1 = self.run_cmd_out("cat %s.md5" % file_name_xz2).strip()
        md5_sum2 = self.run_cmd_out("md5sum %s | cut -d' ' -f1" % file_name_xz2).strip()
        if md5_sum1 != md5_sum2:
            self.is_fail += 1
            self.log.info("md5sum check failed")
        dir_name = self.run_cmd_out("sosreport --no-report --batch --build | grep located | "
                                    "cut -d':' -f2").strip()
        sosreport_dir = os.path.join(dir_name, 'sos_reports')
        if os.listdir(sosreport_dir) != []:
            self.is_fail += 1
            self.log.info("--no-report option failed")
        file_list = self.params.get('file_list', default=['proc/device-tree/'])
        for files in file_list:
            file_path = os.path.join(dir_name, files)
            if not os.path.exists(file_path):
                self.is_fail += 1
                self.log.info("%s file/directory not created" % file_path)
        self.run_cmd("sosreport --batch --tmp-dir=%s -s /home/" % directory_name)
        shutil.rmtree(directory_name)
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in sosreport tool verification" %
                      self.is_fail)


if __name__ == "__main__":
    main()
