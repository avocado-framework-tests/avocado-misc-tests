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

from avocado import Test
from avocado import main
from avocado import skipIf
from avocado.utils import process
from avocado.utils import genio
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import distro


class Lshwrun(Test):

    """
    lshw is a small tool to extract detailed information on the
    hardware configuration of the machine.
    It can report exact memory configuration,firmware version,
    mainboard configuration, CPU version and speed,cache configuration, bus
    speed, etc. on DMI-capable x86 or IA-64 systems and on some PowerPC
    machines (PowerMac G4 is known to work).

    :avocado: tags=privileged
    """
    interface = process.system_output("ip route show")
    active_interface = process.system_output(
        "ip link ls up  | awk -F: '$0 !~ \"lo|vir|^[^0-9]\"{print $2}'"
        " | cut -d  \" \" -f2 | head -1", shell=True).strip().split()[0]
    fail_cmd = list()

    def run_cmd(self, cmd):
        if process.system(cmd, ignore_status=True, sudo=True, shell=True):
            self.is_fail += 1
            self.fail_cmd.append(cmd)

    @staticmethod
    def run_cmd_out(cmd):
        return process.system_output(cmd, shell=True,
                                     ignore_status=True, sudo=True)

    def setUp(self):
        sm = SoftwareManager()

        dist = distro.detect()
        if dist.name == "SuSE" and dist.version < 15:
            self.cancel("lshw not supported on SUES-%s. Please run " +
                        "on SLES15 or higher versions only " % dist.version)

        for package in ("lshw", "net-tools", "iproute", "pciutils"):
            if not sm.check_installed(package) and not sm.install(package):
                self.error("Fail to install %s required for this"
                           " test." % package)

    def test_lshw(self):
        """
        lshw without any options would generate full information
        report about all detected hardware.
        """
        self.log.info("===============Executing lshw test ===="
                      "===========")
        self.is_fail = 0
        self.run_cmd("lshw")
        self.run_cmd("lshw -version")
        if self.is_fail >= 1:
            self.fail("%s command(s) failed to execute  "
                      % self.fail_cmd)

    def test_lshw_short(self):
        """
        With "-short" option,the lshw command would generate a brief
        information report about the hardware devices
        """
        self.log.info("===============Executing lshw -short tests ===="
                      "===========")
        self.is_fail = 0
        for class_name in ['network', 'storage', 'memory', 'power',
                           'bus', 'processor', 'system']:
            self.run_cmd("lshw -short -class  %s" % class_name)
        if self.is_fail >= 1:
            self.fail("%s command(s) failed to execute "
                      % self.fail_cmd)

    def test_lshw_class(self):
        """
        To display information about any particular hardware,specify the class.
        """
        self.log.info("===============Executing lshw -class tests ===="
                      "===========")
        self.is_fail = 0
        for hw_class in ['disk', 'storage', 'memory', 'cpu', 'volume',
                         'network', 'power', 'generic', 'processor',
                         'bridge', 'multimedia', 'display',
                         'system', 'communication', 'bus']:
            self.run_cmd("lshw -class %s" % hw_class)
        if self.is_fail >= 1:
            self.fail("%s command(s) failed to execute "
                      % self.fail_cmd)

    def test_lshw_verification(self):
        """
        compare the output of lshw with other tools
        which produces similar info of hardware.
        """
        # verifying mac address
        mac = process.system_output("ip addr | awk '/ether/ {print $2}'"
                                    " | head -1", shell=True).strip()
        if mac not in process.system_output("lshw"):
            self.fail("lshw failed to show correct mac address")

        # verify network
        if self.active_interface\
                not in process.system_output("lshw -class network"):
            self.fail("lshw failed to show correct active network interface")

    def test_gen_rep(self):
        """
        Lshw is capable of producing reports in html, xml and json formats.
        """
        self.is_fail = 0
        self.run_cmd("lshw -xml")
        self.run_cmd("lshw -html -class disk")
        self.run_cmd("lshw -json")
        if self.is_fail >= 1:
            self.fail("%s command(s) failed to generate report"
                      % self.fail_cmd)

    def test_businfo(self):
        """
        Outputs the device list showing bus information,
        detailing SCSI, USB, IDE and PCI addresses.
        """
        bus_info = process.run("lshw -businfo")
        if bus_info.exit_status:
            self.fail(" lshw  failed to execute lshw -businfo  ")

        # verifying the bus info for active network
        if_present = 0
        lspci_out = process.system_output("lspci -v ")
        for line in (bus_info.stdout).splitlines():
            get_bus_info_act_inter = line.split(' ')[0]
            if get_bus_info_act_inter in lspci_out:
                if_present = 1
        if not if_present:
            self.fail("Verification of network bus info failed ")

    def test_sanitize(self):
        """
        sanitize output(remove sensitive information like serial numbers,etc.)
        """
        out_with_sanitize = process.system_output("lshw -sanitize")
        for line in process.system_output("lshw").strip('\t\n\r').splitlines():
            if ("serial:" in line) and (line in out_with_sanitize):
                self.fail("Sensitive data is present in output")

    def test_prod_id_serial(self):
        """
        Test verifies the product id and serial number in lshw output.
        """
        self.log.info("===============Validating product id and serial number"
                      "===========")
        self.is_fail = 0
        if 'KVM' in self.run_cmd_out("pseries_platform"):
            product_path = '/proc/device-tree/host-model'
            serial_path = '/proc/device-tree/host-serial'
        else:
            product_path = '/proc/device-tree/model'
            serial_path = '/proc/device-tree/system-id'
        product_name = genio.read_file(product_path).rstrip(' \t\r\n\0')
        serial_num = genio.read_file(serial_path).rstrip(' \t\r\n\0')

        if product_name\
                not in self.run_cmd_out("lshw | grep product | head -1"):
            self.is_fail += 1
        if serial_num not in self.run_cmd_out("lshw | grep serial | head -1"):
            self.is_fail += 1
        if self.is_fail >= 1:
            self.fail("%s command(s) failed to execute "
                      % self.fail_cmd)

    def test_lshw_options(self):
        """
        -disable -> Disables a test.
        -enable -> Enables a test.
        -quiet -> Don't display status.
        -numeric -> Also display numeric IDs.
        """
        self.log.info("===============Verifying -disable, -enable, -quiet,"
                      " and -numeric options ==============")
        self.is_fail = 0
        if "interface" in self.run_cmd_out("lshw -disable network| "
                                           "grep -i interface"):
            self.is_fail += 1
        if "interface" not in self.run_cmd_out("lshw -enable network| "
                                               "grep -i interface"):
            self.is_fail += 1

        self.run_cmd("lshw -class -quiet")
        if 'PowerVM'\
                not in self.run_cmd_out("pseries_platform"):
            if not self.run_cmd_out("lshw"
                                    " -numeric | grep HCI | cut -d':' -f3"):
                self.is_fail += 1
        if self.is_fail >= 1:
            self.fail("%s command(s) failed. %s command(s) failed to execute "
                      % (self.is_fail, self.fail_cmd))

    @skipIf(process.system("lshw --help 2>&1 |grep notime",
            ignore_status=True, sudo=True, shell=True) == 1,
            "-notime option unsupported, skipping")
    def test_lshw_notime(self):
        """
        -notime -> exclude volatile attributes (timestamps) from output.
        """
        self.log.info("===============Verifying -notime option ==============")
        self.is_fail = 0
        if "modified" in self.run_cmd_out("lshw -notime | grep modified"):
            self.fail("modified time stamp is present evev with -notime")
        if self.is_fail >= 1:
            self.fail("%s command(s) failed. %s command(s) failed to execute "
                      % (self.is_fail, self.fail_cmd))


if __name__ == "__main__":
    main()
