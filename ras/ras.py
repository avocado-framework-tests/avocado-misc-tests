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
# Author: Sachin Sant <sachinp@linux.ibm.com>

import os
from shutil import copyfile
from avocado import Test
from avocado.utils import process, distro
from avocado import skipIf, skipUnless
from avocado.utils.software_manager.manager import SoftwareManager

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
        """
        Prepare the system for test run
        """
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

    @skipIf(IS_POWER_NV or IS_KVM_GUEST,
            "This test is not supported on KVM guest or PowerNV platform")
    def test1_set_poweron_time(self):
        """
        set_poweron_time schedules the power on time
        """
        self.log.info("===============Executing set_poweron_time tool test===="
                      "===========")
        cmd_list = ["set_poweron_time -m", "set_poweron_time -h",
                    "set_poweron_time -d m2", "set_poweron_time -t M6D15h12"]
        for cmd in cmd_list:
            self.run_cmd(cmd)
        self.error_check()

    @skipIf(IS_POWER_NV or IS_KVM_GUEST,
            "This test is not supported on KVM guest or PowerNV platform")
    def test2_sys_ident_tool(self):
        """
        sys_ident provides unique system identification information
        """
        self.log.info("===============Executing sys_ident_tool test==========="
                      "====")
        cmd_list = ["sys_ident -p", "sys_ident -s"]
        for cmd in cmd_list:
            self.run_cmd(cmd)
        self.error_check()

    def test3_lsmcode(self):
        """
        lsmcode provides FW version information
        """
        self.log.info("===============Executing lsmcode tool test============="
                      "==")
        self.run_cmd("vpdupdate")
        if 'FW' not in self.run_cmd_out("lsmcode"):
            self.fail("lsmcode command failed in verification")
        cmd_list = ["lsmcode -A", "lsmcode -v", "lsmcode -D"]
        for cmd in cmd_list:
            self.run_cmd(cmd)
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
        self.error_check()

    @skipIf(IS_POWER_NV, "Skipping test in PowerNV platform")
    def test4_drmgr(self):
        """
        drmgr can be used for pci, cpu or memory hotplug
        """
        self.log.info("===============Executing drmgr tool test============="
                      "==")
        self.run_cmd("drmgr -h")
        self.run_cmd("drmgr -C")
        lcpu_count = self.run_cmd_out("lparstat -i | "
                                      "grep \"Online Virtual CPUs\" | "
                                      "cut -d':' -f2")
        if lcpu_count:
            lcpu_count = int(lcpu_count)
            if lcpu_count >= 2:
                cmd_list = ["drmgr -c cpu -r 1", "drmgr -c cpu -a 1"]
                for cmd in cmd_list:
                    self.run_cmd(cmd)
                    self.run_cmd("lparstat")
        self.error_check()

    def test5_lsprop(self):
        """
        lsprop provides device tree information
        """
        self.log.info("===============Executing lsprop tool test============="
                      "==")
        self.run_cmd("lsprop")
        self.error_check()

    @skipIf(IS_POWER_NV, "Skipping test in PowerNV platform")
    def test6_lsslot(self):
        """
        lsslot lists the slots based on the option provided
        """
        self.log.info("===============Executing lsslot tool test============="
                      "==")
        self.run_cmd("lsslot")
        self.run_cmd("lsslot -c mem")
        if self.run_cmd_out("lspci"):
            self.run_cmd_out("lsslot -ac pci")
        if not IS_KVM_GUEST:
            self.run_cmd("lsslot -c cpu -b")
        self.run_cmd("lsslot -c pci -o")
        slot = self.run_cmd_out("lsslot | cut -d' ' -f1 | head -2"
                                " | tail -1")
        if slot:
            self.run_cmd("lsslot -s %s" % slot)
        self.error_check()

    @skipIf(IS_POWER_NV, "Skipping test in PowerNV platform")
    def test7_lsvio(self):
        """
        lsvio lists the virtual I/O adopters and devices
        """
        self.log.info("===============Executing lsvio tool test============="
                      "==")
        cmd_list = [" -h", " -v", " -s", " -e", " -d"]
        for cmd in cmd_list:
            cmd_str = "lsvio" + cmd
            self.run_cmd(cmd_str)
        self.error_check()

    def test8_nvram(self):
        """
        nvram command retrieves and displays NVRAM data
        """
        self.log.info("===============Executing nvram tool test============="
                      "==")
        cmd_list = [" --help", " --print-config -p common",
                    " --partitions", " --dump common --verbose"]
        for cmd in cmd_list:
            cmd_str = "nvram" + cmd
            self.run_cmd(cmd_str)
        self.error_check()

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
            of_name = self.run_cmd_out("ofpathname %s" %
                                       disk_name).split(':')[0]
            self.run_cmd("ofpathname -l %s" % of_name)
        self.error_check()

    @skipIf(IS_POWER_NV or IS_KVM_GUEST,
            "This test is not supported on KVM guest or PowerNV platform")
    def test11_rtas_ibm_get_vpd(self):
        """
        rtas_ibm_get_vpd gives vpd data
        """
        self.log.info("===============Executing rtas_ibm_get_vpd tool test===="
                      "===========")
        output_file = os.path.join(self.outputdir, 'output')
        self.run_cmd("rtas_ibm_get_vpd >> %s 2>&1" % output_file)
        self.error_check()

    @skipIf(IS_POWER_NV, "Skipping test in PowerNV platform")
    def test12_rtas_errd_and_rtas_dump(self):
        """
        rtas_errd adds RTAS events to /var/log/platform and rtas_dump dumps
        RTAS events
        """
        self.log.info("===============Executing rtas_errd and rtas_dump tools"
                      " test===============")
        self.log.info("1 - Injecting event")
        rtas_file = self.get_data('rtas')
        self.run_cmd("rtas_errd -d -f %s" % rtas_file)
        self.log.info("2 - Checking if the event was dumped to /var/log/"
                      "platform")
        self.run_cmd("cat /var/log/platform")
        myplatform_file = os.path.join(self.outputdir, 'myplatformfile')
        my_log = os.path.join(self.outputdir, 'mylog')
        self.run_cmd("rtas_errd -d -f %s -p %s -l %s" %
                     (rtas_file, myplatform_file, my_log))
        self.run_cmd("cat %s" % myplatform_file)
        self.run_cmd("cat %s" % my_log)
        self.log.info("3 - Verifying rtas_dump command")
        self.run_cmd("rtas_dump -f %s" % rtas_file)
        self.log.info("4 - Verifying rtas_dump with event number 2302")
        self.run_cmd("rtas_dump -f %s -n 2302" % rtas_file)
        self.log.info("5 - Verifying rtas_dump with verbose option")
        self.run_cmd("rtas_dump -f %s -v" % rtas_file)
        self.log.info("6 - Verifying rtas_dump with width 20")
        self.run_cmd("rtas_dump -f %s -w 20" % rtas_file)
        self.error_check()

    @skipIf(IS_POWER_NV, "This test is not supported on PowerNV platform")
    def test13_rtas_event_decode(self):
        """
        Verify RTAS event data using rtas_event_decode
        """
        self.log.info("==============Executing rtas_event_decode tool test===="
                      "===========")
        cmd = "rtas_event_decode -w 500 -dv -n 2302 < %s" % self.get_data(
            'rtas')
        cmd_result = process.run(
            cmd, ignore_status=True, sudo=True, shell=True)
        if cmd_result.exit_status not in [17, 13]:
            self.fail("rtas_event_decode tool: %s command failed in "
                      "verification" % cmd)
