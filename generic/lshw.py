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
# Copyright: 2016 IBM.
# Author: Ramya BS <ramya@linux.vnet.ibm.com>

import os
import re
import subprocess
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils.software_manager import SoftwareManager


class Lshwrun(Test):

    """
    lshw is a small tool to extract detailed information on the
    hardware configuration of the machine.
    It can report exact memory configuration,firmware version,
    mainboard configuration, CPU version and speed,cache configuration, bus
    speed, etc. on DMI-capable x86 or IA-64 systems and on some PowerPC
    machines (PowerMac G4 is known to work).
    """
    interface = process.system_output("ip route show")
    active_interface = re.search(
        r"default via\s+\S+\s+dev\s+(\w+)\s+proto", interface).group(1)
    is_fail = 0

    def run_cmd(self, cmd):
        cmd_result = process.run(cmd, ignore_status=True, sudo=True,
                                 shell=True)
        if cmd_result.exit_status != 0:
            self.is_fail += 1
        return

    def setUp(self):
        if os.geteuid() != 0:
            self.error("This program requires super user priv to run.")
        soft = SoftwareManager()
        for package in ("lshw", "net-tools", "iproute", "pciutils"):
            if not soft.check_installed(package) and not soft.install(package):
                self.error("Fail to install %s required for this"
                           " test." % package)

    def test_lshw(self):
        """
        lshw without any options would generate full information
        report about all detected hardware.
        """
        self.log.info("===============Executing lshw test ===="
                      "===========")
        self.run_cmd("lshw")
        self.run_cmd("lshw -version")
        if self.is_fail >= 1:
            self.fail("%s command(s) failed to execute  "
                      "verification" % self.is_fail)

    def test_lshw_short(self):
        """
        With "-short" option,the lshw command would generate a brief
        information report about the hardware devices
        """
        self.log.info("===============Executing lshw -short tests ===="
                      "===========")
        self.run_cmd("lshw -short")
        self.run_cmd("lshw -short  -class network")
        self.run_cmd("lshw -short  -class storage")
        self.run_cmd("lshw -short  -class memory")
        self.run_cmd("lshw -short  -class power")
        self.run_cmd("lshw -short  -class bus")
        self.run_cmd("lshw -short  -class processor")
        self.run_cmd("lshw -short  -class system")
        if self.is_fail >= 1:
            self.fail("%s command(s) failed to execute "
                      "verification" % self.is_fail)

    def test_lshw_class(self):
        """
        To display information about any particular hardware,specify the class.
        """
        self.log.info("===============Executing lshw -class tests ===="
                      "===========")
        self.run_cmd("lshw -class disk -class storage")
        self.run_cmd("lshw -class memory")
        self.run_cmd("lshw -class cpu")
        self.run_cmd("lshw -class volume")
        self.run_cmd("lshw -class network")
        self.run_cmd("lshw -class power")
        self.run_cmd("lshw -class generic")
        self.run_cmd("lshw -class processor")
        self.run_cmd("lshw -class bridge")
        self.run_cmd("lshw -class multimedia")
        self.run_cmd("lshw -class display")
        self.run_cmd("lshw -class system")
        self.run_cmd("lshw -class communication")
        self.run_cmd("lshw -class bus")
        if self.is_fail >= 1:
            self.fail("%s command(s) failed to execute "
                      "verification" % self.is_fail)

    def test_lshw_verification(self):
        """
        compare the output of lshw with other tools
        which produces similar info of hardware.
        """
        # verifying mac address
        get_mac = process.system_output(
            " ip link show %s " % self.active_interface)
        mac = re.search(r'link\/\ether (.*) brd', get_mac).group(1)
        lshw_out_mac = process.system_output("lshw")
        if mac not in lshw_out_mac:
            self.fail("lshw failed to show correct mac address")

        # verify network
        lshw_out_net = process.system_output("lshw -class network")
        if self.active_interface not in lshw_out_net:
            self.fail("lshw failed to show correct active network interface")

    def test_gen_rep(self):
        """
        Lshw is capable of producing reports in html, xml and json formats.
        """
        self.run_cmd("lshw -xml")
        self.run_cmd("lshw -html -class disk")
        self.run_cmd("lshw -json")
        if self.is_fail >= 1:
            self.fail("%s command(s) failed to generate report"
                      % self.is_fail)

    def test_businfo(self):
        """
        Outputs the device list showing bus information,
        detailing SCSI, USB, IDE and PCI addresses.
        """
        bus_info = process.run("lshw -businfo")
        if bus_info.exit_status:
            self.fail(" lshw  failed to execute lshw -businfo  ")

        # verifying the bus info for active network
        get_bus = process.system_output('lshw -businfo').splitlines()
        for line in get_bus:
            if self.active_interface in line:
                get_bus_info_act_inter = line.split(' ')[0].split(':', 1)[1]

        get_bus_info_lspci = process.system_output("lspci -v ")
        if get_bus_info_act_inter not in get_bus_info_lspci:
            self.fail("Verification of network bus info failed ")

    def test_sanitize(self):
        """
        sanitize output(remove sensitive information like serial numbers,etc.)
        """
        out = []
        out_lshw = subprocess.Popen("lshw", stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, shell=True)
        for line in iter(out_lshw.stdout.readline, b''):
            if "serial:" in line:
                out.append(line.strip(' \t\n\r'))
        out_with_sanitize = process.system_output("lshw -sanitize")
        for i in out:
            if i in out_with_sanitize:
                self.fail("Sensitive data is present in output")


if __name__ == "__main__":
    main()
