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
from shutil import copyfile
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado import skipIf
from avocado.utils.software_manager import SoftwareManager

IS_POWER_NV = 'PowerNV' in open('/proc/cpuinfo', 'r').read()
IS_KVM_GUEST = 'qemu' in open('/proc/cpuinfo', 'r').read()


class RASTools(Test):

    """
    This test checks various RAS tools:
    """
    is_fail = 0

    def run_cmd(self, cmd):
        if (process.run(cmd, ignore_status=True, sudo=True, shell=True)).exit_status:
            self.is_fail += 1
        return

    def setUp(self):
        if "ppc" not in os.uname()[4]:
            self.cancel("supported only on Power platform")
        sm = SoftwareManager()
        for package in ("ppc64-diag", "powerpc-utils", "lsvpd", "sysfsutils"):
            if not sm.check_installed(package) and not sm.install(package):
                self.cancel("Fail to install %s required for this"
                            " test." % package)

    @skipIf(IS_POWER_NV or IS_KVM_GUEST, "This test is not supported on KVM guest or PowerNV platform")
    def test1_uesensor(self):
        self.log.info("===============Executing uesensor tool test===="
                      "===========")
        self.run_cmd("uesensor -l")
        self.run_cmd("uesensor -a")
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in uesensor tool "
                      "verification" % self.is_fail)

    @skipIf(IS_POWER_NV or IS_KVM_GUEST, "This test is not supported on KVM guest or PowerNV platform")
    def test1_serv_config(self):
        self.log.info("===============Executing serv_config tool test===="
                      "===========")
        list = [
            '-l', '-b', '-s', '-r', '-m', '-d', '--remote-maint', '--surveillance',
            '--reboot-policy', '--remote-pon', '-d --force']
        for list_item in list:
            cmd = "serv_config %s" % list_item
            self.run_cmd(cmd)
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in serv_config tool "
                      "verification" % self.is_fail)

    @skipIf(IS_POWER_NV, "This test is not supported on PowerNV platform")
    def test1_rtas_event_decode(self):
        self.log.info("===============Executing rtas_event_decode tool test===="
                      "===========")
        self.run_cmd("rtas_event_decode -w 500 -dv -n 2302 < %s" %
                     os.path.join(self.datadir, 'rtas'))
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in rtas_event_decode tool "
                      "verification" % self.is_fail)

    @skipIf(IS_POWER_NV or IS_KVM_GUEST, "This test is not supported on KVM guest or PowerNV platform")
    def test1_ls_vscsi(self):
        self.log.info("===============Executing ls-vscsi tool test===="
                      "===========")
        self.run_cmd("ls-vscsi")
        self.run_cmd("ls-vscsi -h")
        self.run_cmd("ls-vscsi -V")
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in ls-vscsi tool "
                      "verification" % self.is_fail)

    @skipIf(IS_POWER_NV or IS_KVM_GUEST, "This test is not supported on KVM guest or PowerNV platform")
    def test1_ls_veth(self):
        self.log.info("===============Executing ls-veth tool test===="
                      "===========")
        self.run_cmd("ls-veth")
        self.run_cmd("ls-veth -h")
        self.run_cmd("ls-veth -V")
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in ls-veth tool "
                      "verification" % self.is_fail)

    @skipIf(IS_POWER_NV or IS_KVM_GUEST, "This test is not supported on KVM guest or PowerNV platform")
    def test1_ls_vdev(self):
        self.log.info("===============Executing ls-vdev tool test===="
                      "===========")
        self.run_cmd("ls-vdev")
        self.run_cmd("ls-vdev -h")
        self.run_cmd("ls-vdev -V")
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in ls-vdev tool "
                      "verification" % self.is_fail)

    @skipIf(IS_POWER_NV or IS_KVM_GUEST, "This test is not supported on KVM guest or PowerNV platform")
    def test1_lsdevinfo(self):
        self.log.info("===============Executing lsdevinfo tool test===="
                      "===========")
        self.run_cmd("lsdevinfo")
        list = ['-h', '-V', '-c', '-R', '-F name,type']
        for list_item in list:
            cmd = "lsdevinfo %s" % list_item
            self.run_cmd(cmd)
        interface = process.system_output("ifconfig | head -1 | cut -d':' -f1",
                                          shell=True).strip()
        self.run_cmd("lsdevinfo -q name=%s" % interface)
        disk_name = process.system_output("df -h | egrep '(s|v)d[a-z][1-8]' | "
                                          "tail -1 | cut -d' ' -f1",
                                          shell=True).strip("12345")
        self.run_cmd("lsdevinfo -q name=%s" % disk_name)
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in lsdevinfo tool "
                      "verification" % self.is_fail)

    @skipIf(IS_POWER_NV or IS_KVM_GUEST, "This test is not supported on KVM guest or PowerNV platform")
    def test1_hvcsadmin(self):
        self.log.info("===============Executing hvcsadmin tool test===="
                      "===========")
        list = ['--status', '--version', '-all', '-noisy', '-rescan']
        for list_item in list:
            cmd = "hvcsadmin %s" % list_item
            self.run_cmd(cmd)
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in hvcsadmin tool "
                      "verification" % self.is_fail)

    @skipIf(IS_POWER_NV or IS_KVM_GUEST, "This test is not supported on KVM guest or PowerNV platform")
    def test1_bootlist(self):
        self.log.info("===============Executing bootlist tool test===="
                      "===========")
        list = ['--help', '-m normal -r',
                '-m normal -o', '-m service -o', '-m both -o']
        for list_item in list:
            cmd = "bootlist %s" % list_item
            self.run_cmd(cmd)
        interface = process.system_output("ifconfig | head -1 | cut -d':' -f1",
                                          shell=True).strip()
        disk_name = process.system_output("df -h | egrep '(s|v)d[a-z][1-8]' | "
                                          "tail -1 | cut -d' ' -f1",
                                          shell=True).strip("12345")
        file_path = os.path.join(self.srcdir, 'file')
        process.run("echo %s > %s" %
                    (disk_name, file_path), ignore_status=True, sudo=True, shell=True)
        process.run("echo %s >> %s" %
                    (interface, file_path), ignore_status=True, sudo=True, shell=True)
        self.run_cmd("bootlist -r -m both -f %s" % file_path)
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in bootlist tool "
                      "verification" % self.is_fail)

    @skipIf(IS_KVM_GUEST, "This test is not supported on KVM guest platform")
    def test1_vpdupdate(self):
        self.log.info("===============Executing vpdupdate tool test===="
                      "===========")
        self.run_cmd("vpdupdate")
        list = ['--help', '--version', '--archive', '--scsi']
        for list_item in list:
            cmd = "vpdupdate %s" % list_item
            self.run_cmd(cmd)
        path_db = process.system_output("find /var/lib/lsvpd/ -iname vpd.db | "
                                        "head -1", shell=True).strip()
        if path_db:
            copyfile_path = os.path.join(self.outputdir, 'vpd.db')
            copyfile(path_db, copyfile_path)
            self.run_cmd("vpdupdate --path=%s" % copyfile_path)
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in vpdupdate tool "
                      "verification" % self.is_fail)

    @skipIf(IS_KVM_GUEST, "This test is not supported on KVM guest platform")
    def test3_lsvpd(self):
        self.log.info("===============Executing lsvpd tool test============="
                      "==")
        self.run_cmd("lsvpd")
        list = ['--debug', '--version', '--mark',
                '--serial=STR', '--type=STR', '--list=raid']
        for list_item in list:
            cmd = "lsvpd %s" % list_item
            self.run_cmd(cmd)
        path_db = process.system_output("find /var/lib/lsvpd/ -iname vpd.db | "
                                        "head -1", shell=True).strip()
        if path_db:
            copyfile_path = os.path.join(self.outputdir, 'vpd.db')
            copyfile(path_db, copyfile_path)
            self.run_cmd("lsvpd --path=%s" % copyfile_path)
        path_tar = process.system_output("find /var/lib/lsvpd/ -iname vpd.*.gz"
                                         " | head -1", shell=True).strip()
        if path_tar:
            self.run_cmd("lsvpd --zip=%s" % path_tar)
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in lsvpd tool verification"
                      % self.is_fail)

    @skipIf(IS_KVM_GUEST, "This test is not supported on KVM guest platform")
    def test3_lscfg(self):
        self.log.info("===============Executing lscfg tool test============="
                      "==")
        self.run_cmd("lscfg")
        list = ['--debug', '--version', '-p', '-lcpu']
        for list_item in list:
            cmd = "lscfg %s" % list_item
            self.run_cmd(cmd)
        path_db = process.system_output("find /var/lib/lsvpd/ -iname vpd.db | "
                                        "head -1", shell=True).strip()
        if path_db:
            copyfile_path = os.path.join(self.outputdir, 'vpd.db')
            copyfile(path_db, copyfile_path)
            self.run_cmd("lscfg --data=%s" % copyfile_path)
        path_tar = process.system_output("find /var/lib/lsvpd/ -iname vpd.*.gz"
                                         " | head -1", shell=True).strip()
        if path_tar:
            self.run_cmd("lscfg --zip=%s" % path_tar)
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in lscfg tool verification"
                      % self.is_fail)


if __name__ == "__main__":
    main()
