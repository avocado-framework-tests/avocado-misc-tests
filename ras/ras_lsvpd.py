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
# Author: Sachin Sant <sachinp@linux.ibm.com>

import os
import shutil
from shutil import copyfile
from avocado import Test
from avocado.utils import process, distro
from avocado import skipIf
from avocado.utils.software_manager.manager import SoftwareManager

IS_POWER_NV = 'PowerNV' in open('/proc/cpuinfo', 'r').read()
IS_KVM_GUEST = 'qemu' in open('/proc/cpuinfo', 'r').read()


class RASToolsLsvpd(Test):

    """
    This test checks various RAS tools bundled as a part of lsvpd
    package/repository

    :avocado: tags=ras,ppc64le
    """
    is_fail = 0

    def run_cmd(self, cmd):
        if (process.run(cmd, ignore_status=True, sudo=True, shell=True)).exit_status:
            self.is_fail += 1
        return

    def setUp(self):
        if "ppc" not in distro.detect().arch:
            self.cancel("supported only on Power platform")
        sm = SoftwareManager()
        for package in ("lsvpd", "sysfsutils"):
            if not sm.check_installed(package) and not sm.install(package):
                self.cancel("Fail to install %s required for this"
                            " test." % package)

    @staticmethod
    def run_cmd_out(cmd):
        return process.system_output(cmd, shell=True,
                                     ignore_status=True,
                                     sudo=True).decode("utf-8").strip()

    @skipIf(IS_KVM_GUEST, "This test is not supported on KVM guest platform")
    def test_vpdupdate(self):
        self.log.info("===============Executing vpdupdate tool test===="
                      "===========")
        self.run_cmd("vpdupdate")
        list = ['--help', '--version', '--archive', '--scsi']
        for list_item in list:
            cmd = "vpdupdate %s" % list_item
            self.run_cmd(cmd)
        path_db = self.run_cmd_out("find /var/lib/lsvpd/ -iname vpd.db | "
                                   "head -1")
        if path_db:
            copyfile_path = os.path.join(self.outputdir, 'vpd.db')
            shutil.copyfile(path_db, copyfile_path)
            self.run_cmd("vpdupdate --path=%s" % copyfile_path)
        if os.path.exists('/var/lib/lsvpd/run.vpdupdate'):
            path = '/var/lib/lsvpd/run.vpdupdate'
        elif os.path.exists('/run/run.vpdupdate'):
            path = '/run/run.vpdupdate'
        move_path = '/root/run.vpdupdate'
        shutil.move(path, move_path)
        self.log.info("Running vpdupdate after removing run.vpdupdate")
        self.run_cmd("vpdupdate")
        shutil.move(move_path, path)
        process.run("rm -f /var/lib/lsvpd/vpd.db; touch /var/lib/lsvpd/vpd.db",
                    shell=True)
        for command in ["lsvpd", "lscfg", "lsmcode"]:
            if not self.run_cmd_out("%s | grep run | grep vpdupdate" % command):
                self.fail(
                    "Error message is not displayed when vpd.db is corrupted.")
        self.run_cmd("vpdupdate")
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in vpdupdate tool "
                      "verification" % self.is_fail)

    @skipIf(IS_KVM_GUEST, "This test is not supported on KVM guest platform")
    def test_lsvpd(self):
        self.log.info("===============Executing lsvpd tool test============="
                      "==")
        self.run_cmd("vpdupdate")
        self.run_cmd("lsvpd")
        list = ['--debug', '--version', '--mark',
                '--serial=STR', '--type=STR', '--list=raid']
        for list_item in list:
            cmd = "lsvpd %s" % list_item
            self.run_cmd(cmd)
        path_db = self.run_cmd_out("find /var/lib/lsvpd/ -iname vpd.db | "
                                   "head -1").strip()
        if path_db:
            copyfile_path = os.path.join(self.outputdir, 'vpd.db')
            shutil.copyfile(path_db, copyfile_path)
            self.run_cmd("lsvpd --path=%s" % copyfile_path)
        path_tar = self.run_cmd_out("find /var/lib/lsvpd/ -iname vpd.*.gz"
                                    " | head -1")
        if path_tar:
            self.run_cmd("lsvpd --zip=%s" % path_tar)
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in lsvpd tool verification"
                      % self.is_fail)

    @skipIf(IS_KVM_GUEST, "This test is not supported on KVM guest platform")
    def test_lscfg(self):
        self.log.info("===============Executing lscfg tool test============="
                      "==")
        self.run_cmd("lscfg")
        list = ['--debug', '--version', '-p']
        device = self.run_cmd_out('lscfg').splitlines()[-1]
        if device.startswith("+"):
            list.append("-l%s" % device.split(" ")[1])

        for list_item in list:
            cmd = "lscfg %s" % list_item
            self.run_cmd(cmd)
        path_db = self.run_cmd_out("find /var/lib/lsvpd/ -iname vpd.db | "
                                   "head -1")
        if path_db:
            copyfile_path = os.path.join(self.outputdir, 'vpd.db')
            shutil.copyfile(path_db, copyfile_path)
            self.run_cmd("lscfg --data=%s" % copyfile_path)
        path_tar = self.run_cmd_out("find /var/lib/lsvpd/ -iname vpd.*.gz"
                                    " | head -1")
        if path_tar:
            self.run_cmd("lscfg --zip=%s" % path_tar)
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in lscfg tool verification"
                      % self.is_fail)

    def test_lsmcode(self):
        """
        lsmcode provides FW version information
        """
        self.log.info("===============Executing lsmcode tool test============="
                      "==")
        self.run_cmd("vpdupdate")
        if 'FW' not in self.run_cmd_out("lsmcode"):
            self.fail("lsmcode command failed in verification")
        self.run_cmd("lsmcode -A")
        self.run_cmd("lsmcode -v")
        self.run_cmd("lsmcode -D")
        path_db = self.run_cmd_out("find /var/lib/lsvpd/ -iname vpd.db"
                                   " | head -1")
        if path_db:
            copyfile_path = os.path.join(self.outputdir, 'vpd.db')
            copyfile(path_db, copyfile_path)
            self.run_cmd("lsmcode --path=%s" % copyfile_path)
        path_tar = self.run_cmd_out("find /var/lib/lsvpd/ -iname vpd.*.gz"
                                    " | head -1")
        if path_tar:
            self.run_cmd("lsmcode --zip=%s" % path_tar)
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in lsmcode tool verification"
                      % self.is_fail)

    @skipIf(IS_POWER_NV, "Skipping test in PowerNV platform")
    def test_lsvio(self):
        """
        lsvio lists the virtual I/O adopters and devices
        """
        self.log.info("===============Executing lsvio tool test============="
                      "==")
        self.run_cmd("lsvio -h")
        self.run_cmd("lsvio -v")
        self.run_cmd("lsvio -s")
        self.run_cmd("lsvio -e")
        self.run_cmd("lsvio -d")
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in lsmcode tool verification"
                      % self.is_fail)

    def test_locking_mechanism(self):
        """
        This tests database (vpd.db) locking mechanism when multiple
        instances of vpdupdate and lsvpd are running simultaneously.
        Locking mechanism prevents corruption of database file
        when running vpdupdate multiple instances
        """

        cmd = "for i in $(seq 500) ; do vpdupdate & done ;"
        ret = process.run(cmd, ignore_bg_processes=True, ignore_status=True,
                          shell=True)
        cmd1 = "for in in $(seq 200) ; do lsvpd & done ;"
        ret1 = process.run(cmd1, ignore_bg_processes=True, ignore_status=True,
                           shell=True)
        if 'SQLITE Error' in ret.stderr.decode("utf-8").strip()\
                or 'corrupt' in ret1.stdout.decode("utf-8").strip():
            self.fail("Database corruption detected")
        else:
            self.log.info("Locking mechanism prevented database corruption")
