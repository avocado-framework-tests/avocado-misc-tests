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
from avocado import skipIf
from avocado.utils import process
from avocado.utils import distro
from avocado.utils.software_manager import SoftwareManager


class Sosreport(Test):

    def run_cmd(self, cmd, verbose=True):
        self.log.info("executing ============== %s =================", cmd)
        if process.system(cmd, verbose=verbose, ignore_status=True, sudo=True):
            self.log.info("%s command failed", cmd)
            self.is_fail += 1
        return

    @staticmethod
    def run_cmd_out(cmd):
        return process.system_output(cmd, shell=True, ignore_status=True,
                                     sudo=True).decode("utf-8")

    def setUp(self):
        dist = distro.detect()
        sm = SoftwareManager()
        if dist.name == 'Ubuntu':
            sos_pkg = 'sosreport'
        # FIXME: "redhat" as the distro name for RHEL is deprecated
        # on Avocado versions >= 50.0.  This is a temporary compatibility
        # enabler for older runners, but should be removed soon
        elif dist.name in ['rhel', 'redhat']:
            sos_pkg = 'sos'
        else:
            self.cancel("sosreport is not supported on %s" % dist.name)
        if not sm.check_installed(sos_pkg) and not sm.install(sos_pkg):
            self.cancel("Package %s is missing and could not be installed" % sos_pkg)

    def test_short(self):
        """
        execute basic tests:
        - help
        - list available plugins
        - capture enable plugins data
        - ticket-number
        - case-id
        """
        self.log.info(
            "===============Executing sosreport tool test (short)===============")
        directory_name = tempfile.mkdtemp()
        self.is_fail = 0
        self.run_cmd("sosreport -h", False)
        self.run_cmd("sosreport -l", False)
        self.run_cmd("sosreport --batch --tmp-dir=%s --verify" % directory_name)

        ticket_id = self.params.get('ticket_id', default='testid')
        if ticket_id not in self.run_cmd_out("sosreport --batch --ticket-number=%s "
                                             "| grep tar.xz" % ticket_id):
            self.is_fail += 1
            self.log.info("--ticket-number option failed")

        case_id = self.params.get('case_id', default='testid')
        if case_id not in self.run_cmd_out("sosreport --batch --case-id=%s | "
                                           "grep tar.xz" % case_id):
            self.is_fail += 1
            self.log.info("--case-id option failed")

        if 'testname' not in self.run_cmd_out("sosreport --batch --tmp-dir=%s "
                                              "--name=testname | "
                                              "grep tar.xz" % directory_name):
            self.is_fail += 1
            self.log.info("--name option failed")

        shutil.rmtree(directory_name)
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in sosreport tool verification" % self.is_fail)

    def test_user(self):
        """
        execute more tests:
        - capture user provided information
        """
        self.log.info(
            "===============Executing sosreport tool test (User)===============")
        directory_name = tempfile.mkdtemp()
        self.is_fail = 0
        list = self.params.get('list', default=['--all-logs'])
        for list_item in list:
            cmd = "sosreport --batch --tmp-dir=%s %s" % (directory_name, list_item)
            self.run_cmd(cmd)

        shutil.rmtree(directory_name)
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in sosreport tool verification" % self.is_fail)

    def test_plugins(self):
        """
        execute different plugin options:
        - skip plugin
        - enable plugin
        - only plugin
        """
        self.log.info(
            "===============Executing sosreport tool test (plugins)===============")
        directory_name = tempfile.mkdtemp()
        self.is_fail = 0

        if self.run_cmd_out("sosreport --batch --tmp-dir=%s -n libraries | "
                            "grep libraries" % directory_name):
            self.is_fail += 1
            self.log.info("--skip-plugins option failed")

        self.run_cmd("sosreport --batch --tmp-dir=%s -e ntp,numa,snmp" % directory_name)
        if 'sendmail' not in self.run_cmd_out("sosreport --batch --tmp-dir=%s -e "
                                              "sendmail | "
                                              "grep sendmail" % directory_name):
            self.is_fail += 1
            self.log.info("--enable-plugins option failed")

        if self.run_cmd_out("sosreport --batch --tmp-dir=%s -o cups | "
                            "grep kernel" % directory_name):
            self.is_fail += 1
            self.log.info("--only-plugins option failed")

        shutil.rmtree(directory_name)
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in sosreport tool verification" % self.is_fail)

    def test_others(self):
        """
        execute options:
        - list profiles
        - capture profile
        - build (doesn't archives copied data)
        - quiet
        - debug
        - tmp dir
        - no-report
        - sysroot
        """
        self.log.info(
            "===============Executing sosreport tool test (others)===============")
        directory_name = tempfile.mkdtemp()
        self.is_fail = 0
        self.run_cmd("sosreport --list-profiles", None)
        self.run_cmd("sosreport --batch --tmp-dir=%s -p boot,memory" % directory_name)

        if "java" not in self.run_cmd_out("sosreport --batch --tmp-dir=%s -p webserver | "
                                          "grep java" % directory_name):
            self.is_fail += 1
            self.log.info("--profile option failed")

        dir_name = self.run_cmd_out("sosreport --batch --tmp-dir=%s --build | "
                                    "grep located | "
                                    "cut -d':' -f2" % directory_name).strip()
        if not os.path.isdir(dir_name):
            self.is_fail += 1
            self.log.info("--build option failed")

        if self.run_cmd_out("sosreport --batch --tmp-dir=%s --quiet -e ntp,numa1" % directory_name):
            self.is_fail += 1
            self.log.info("--quiet option failed")
        self.run_cmd("sosreport --batch --tmp-dir=%s --debug" % directory_name, None)

        self.run_cmd("sosreport --batch --tmp-dir=%s --config-file=/etc/sos.conf" % directory_name)
        file_name = self.run_cmd_out("sosreport --batch --tmp-dir=%s --tmp-dir=/root | "
                                     "grep root | tail -1" % directory_name).strip()
        if not os.path.exists(file_name):
            self.is_fail += 1
            self.log.info("--tmp-dir option failed")

        dir_name = self.run_cmd_out("sosreport --no-report --batch --build | "
                                    "grep located | "
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

        self.run_cmd("sosreport --batch --tmp-dir=%s -s /" % directory_name)

        shutil.rmtree(directory_name)
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in sosreport tool verification" % self.is_fail)

    def test_archive(self):
        """
        execute archive options:
        - bzip2
        - gzip
        - xz
        - auto
        - md5 check
        """
        self.log.info(
            "===============Executing sosreport tool test (Archive)===============")
        directory_name = tempfile.mkdtemp()
        self.is_fail = 0
        f_name = {'bzip2': 'file_name_bz2', 'gzip': 'file_name_gz',
                  'xz': 'file_name_xz', 'auto': 'file_name_xz2'}
        archive = {'bzip2': 'tar.bz2', 'gzip': 'tar.gz',
                   'xz': 'tar.xz', 'auto': 'tar.xz'}
        for key, value in f_name.iteritems():
            file_name = str(f_name[key])
            file_name = self.run_cmd_out("sosreport --batch --tmp-dir=%s -z %s | grep %s" %
                                         (directory_name, str(key),
                                          str(archive[key]))).strip()
            if not os.path.exists(file_name):
                self.is_fail += 1
                self.log.info("-z %s option failed" % str(key))
            elif file_name is not "file_name_xz2":
                os.remove(file_name)

        if os.path.exists(file_name):
            md5_sum1 = self.run_cmd_out("cat %s.md5" % file_name).strip()
            md5_sum2 = self.run_cmd_out("md5sum %s | cut -d' ' -f1" % file_name).strip()
            if md5_sum1 != md5_sum2:
                self.is_fail += 1
                self.log.info("md5sum check failed")
            os.remove(file_name)

        shutil.rmtree(directory_name)
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in sosreport tool verification" % self.is_fail)

    @skipIf("ppc" not in os.uname()[4], "Skip, Powerpc specific tests")
    def test_PPC(self):
        self.log.info(
            "===============Executing sosreport tool test (PPC)===============")
        directory_name = tempfile.mkdtemp()
        self.is_fail = 0
        self.run_cmd("sosreport --batch --tmp-dir=%s -o "
                     "pci,powerpc,procenv,process,processor,kdump" % directory_name)
        shutil.rmtree(directory_name)
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in sosreport tool verification" % self.is_fail)


if __name__ == "__main__":
    main()
