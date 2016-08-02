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
import commands
from shutil import copyfile
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils.software_manager import SoftwareManager


class RASTools(Test):

    """
    This test checks various RAS tools:
    """
    is_fail = 0

    def run_cmd(self, cmd):
        cmd_result = process.run(cmd, ignore_status=True, sudo=True,
                                 shell=True)
        if cmd_result.exit_status != 0:
            self.is_fail += 1
        return

    def setUp(self):
        architecture = os.uname()[4]
        if "ppc" not in architecture:
            self.skip("supported only on Power platform")
        sm = SoftwareManager()
        for package in ("ppc64-diag", "powerpc-utils", "lsvpd"):
            if not sm.check_installed(package) and not sm.install(package):
                self.error("Fail to install %s required for this"
                           " test." % package)

    def test1_set_poweron_time(self):
        """
        set_poweron_time schedules the power on time
        """
        self.log.info("===============Executing set_poweron_time tool test===="
                      "===========")
        self.run_cmd("set_poweron_time -m")
        self.run_cmd("set_poweron_time -h")
        self.run_cmd("set_poweron_time -d m2")
        self.run_cmd("set_poweron_time -t M6D15h12")
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in set_poweron_time tool "
                      "verification" % self.is_fail)

    def test2_sys_ident_tool(self):
        """
        sys_ident provides unique system identification information
        """
        self.log.info("===============Executing sys_ident_tool test==========="
                      "====")
        self.run_cmd("sys_ident -p")
        self.run_cmd("sys_ident -s")
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in sys_ident tool verification"
                      % self.is_fail)

    def test3_lsmcode(self):
        """
        lsmcode provides FW version information
        """
        self.log.info("===============Executing lsmcode tool test============="
                      "==")
        self.run_cmd("lsmcode")
        self.run_cmd("lsmcode -A")
        self.run_cmd("lsmcode -v")
        self.run_cmd("lsmcode -D")
        self.run_cmd("vpdupdate")
        path_db = commands.getoutput("find /var/lib/lsvpd/ -iname vpd.db | "
                                     "head -1")
        if path_db:
            copyfile_path = os.path.join(self.outputdir, 'vpd.db')
            copyfile(path_db, copyfile_path)
            self.run_cmd("lsmcode --path=%s" % copyfile_path)
        path_tar = commands.getoutput("find /var/lib/lsvpd/ -iname vpd.*.gz | "
                                      "head -1")
        if path_tar:
            self.run_cmd("lsmcode --zip=%s" % path_tar)
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in lsmcode tool verification"
                      % self.is_fail)

    def test4_drmgr(self):
        """
        drmgr can be used for pci, cpu or memory hotplug
        """
        self.log.info("===============Executing drmgr tool test============="
                      "==")
        self.run_cmd("drmgr -h")
        self.run_cmd("drmgr -C")
        lcpu_count = commands.getoutput(
            "lparstat -i | grep \"Online Virtual CPUs\" | cut -d':' -f2")
        if lcpu_count:
            if lcpu_count >= 2:
                self.run_cmd("drmgr -c cpu -r 1")
                self.run_cmd("lparstat")
                self.run_cmd("drmgr -c cpu -a 1")
                self.run_cmd("lparstat")
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in drmgr tool verification"
                      % self.is_fail)

    def test5_lsprop(self):
        """
        lsprop provides device tree information
        """
        self.log.info("===============Executing lsprop tool test============="
                      "==")
        self.run_cmd("lsprop")
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in lsprop tool verification"
                      % self.is_fail)

    def test6_lsslot(self):
        """
        lsslot lists the slots based on the option provided
        """
        self.log.info("===============Executing lsslot tool test============="
                      "==")
        self.run_cmd("lsslot")
        self.run_cmd("lsslot -c mem")
        self.run_cmd("lsslot -ac pci")
        self.run_cmd("lsslot -c cpu -b")
        self.run_cmd("lsslot -c pci -o")
        slot = commands.getoutput("lsslot | cut -d' ' -f1 | head -2 | tail -1")
        if slot:
            self.run_cmd("lsslot -s %s" % slot)
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in lsslot tool verification"
                      % self.is_fail)

    def test7_lsvio(self):
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
            self.fail("%s command(s) failed in lsvio tool verification"
                      % self.is_fail)

    def test8_nvram(self):
        """
        nvram command retrieves and displays NVRAM data
        """
        self.log.info("===============Executing nvram tool test============="
                      "==")
        self.run_cmd("nvram --help")
        self.run_cmd("nvram --partitions")
        self.run_cmd("nvram --print-config -p common")
        self.run_cmd("nvram --dump common --verbose")
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in nvram tool verification"
                      % self.is_fail)

    def test9_ofpathname(self):
        """
        ofpathname translates the device name between logical name and Open
        Firmware name
        """
        self.log.info("===============Executing ofpathname tool test=========="
                      "=====")
        self.run_cmd("ofpathname -h")
        self.run_cmd("ofpathname -V")
        disk_name = commands.getoutput(
            "df -h | egrep '(s|v)da[1-8]' | tail -1 | cut -d' ' -f1")
        if disk_name:
            self.run_cmd("ofpathname %s" % disk_name)
            of_name = commands.getoutput("ofpathname %s" % disk_name)
            self.run_cmd("ofpathname -l %s" % of_name)
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in ofpathname tool verification"
                      % self.is_fail)

    def test10_ppc64_cpu(self):
        """
        ppc64_cpu is used to set cpu options
        """
        self.log.info("===============Executing ppc64_cpu tool test==========="
                      "====")
        self.run_cmd("ppc64_cpu --smt")
        self.run_cmd("ppc64_cpu --smt=8")
        self.run_cmd("ppc64_cpu --smt")
        self.run_cmd("ppc64_cpu --smt=4")
        self.run_cmd("ppc64_cpu --smt")
        self.run_cmd("ppc64_cpu --smt=off")
        self.run_cmd("ppc64_cpu --smt")
        self.run_cmd("ppc64_cpu --smt=on")
        self.run_cmd("ppc64_cpu --smt")
        self.run_cmd("ppc64_cpu --cores-present")
        self.run_cmd("ppc64_cpu --cores-on")
        self.run_cmd("ppc64_cpu --dscr")
        self.run_cmd("ppc64_cpu --dscr=1")
        self.run_cmd("ppc64_cpu --dscr")
        self.run_cmd("ppc64_cpu --dscr=0")
        self.run_cmd("ppc64_cpu --smt-snooze-delay")
        self.run_cmd("ppc64_cpu --smt-snooze-delay=200")
        self.run_cmd("ppc64_cpu --smt-snooze-delay")
        self.run_cmd("ppc64_cpu --smt-snooze-delay=100")
        self.run_cmd("ppc64_cpu --run-mode")
        self.run_cmd("ppc64_cpu --subcores-per-core")
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in ppc64_cpu tool verification"
                      % self.is_fail)

    def test11_rtas_ibm_get_vpd(self):
        """
        rtas_ibm_get_vpd gives vpd data
        """
        self.log.info("===============Executing rtas_ibm_get_vpd tool test===="
                      "===========")
        output_file = os.path.join(self.outputdir, 'output')
        self.run_cmd("rtas_ibm_get_vpd >> %s 2>&1" % output_file)
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in rtas_ibm_get_vpd tool "
                      "verification" % self.is_fail)

    def test12_rtas_errd_and_rtas_dump(self):
        """
        rtas_errd adds RTAS events to /var/log/platform and rtas_dump dumps
        RTAS events
        """
        self.log.info("===============Executing rtas_errd and rtas_dump tools"
                      " test===============")
        self.log.info("1 - Injecting event")
        rtas_file = os.path.join(self.datadir, 'rtas')
        self.run_cmd("/usr/sbin/rtas_errd -d -f %s" % rtas_file)
        self.log.info("2 - Checking if the event was dumped to /var/log/"
                      "platform")
        self.run_cmd("cat /var/log/platform")
        myplatform_file = os.path.join(self.outputdir, 'myplatformfile')
        my_log = os.path.join(self.outputdir, 'mylog')
        self.run_cmd("/usr/sbin/rtas_errd -d -f %s -p %s -l %s" %
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
        if self.is_fail >= 1:
            self.fail("%s command(s) failed in rtas_errd and rtas_dump tools "
                      "verification" % self.is_fail)


if __name__ == "__main__":
    main()
