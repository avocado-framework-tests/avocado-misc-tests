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

import re
from avocado import Test
from avocado import skipIf
from avocado.utils import process, cpu
from avocado.utils import genio
from avocado.utils.software_manager.manager import SoftwareManager
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
    # Equivalent Python code for bash command
    # "ip link ls up  | awk -F: '$0 !~ \"lo|vir|^[^0-9]\"{print $2}'"
    #" | cut -d  \" \" -f2 | head -1",
    output = process.system_output("ip link ls up", shell=True).decode().strip()
    active_interface = ""
    for line in output.splitlines():
        # check if the line doesn't contain 'lo' or 'vir' and doesn't start
        # with a non-digit character
        if not re.search(r'lo|vir|^[^0-9]', line):
            fields = line.split(':')
            if fields[1]:
                active_interface = fields[1]
                # for this test we need only one active interface
                break
    fail_cmd = list()

    def run_cmd(self, cmd):
        if process.system(cmd, ignore_status=True, sudo=True, shell=True):
            self.is_fail += 1
            self.fail_cmd.append(cmd)

    def error_check(self):
        if len(self.fail_cmd) > 0:
            for cmd in range(len(self.fail_cmd)):
                self.log.info("Failed command: %s" % self.fail_cmd[cmd])
            self.fail("lshw: Failed commands are: %s" % self.fail_cmd)

    @staticmethod
    def run_cmd_out(cmd):
        return process.system_output(cmd, shell=True,
                                     ignore_status=True,
                                     sudo=True).decode("utf-8")

    def setUp(self):
        sm = SoftwareManager()
        self.is_fail = 0
        dist = distro.detect()
        packages = ['lshw', 'net-tools', 'pciutils']
        if dist.name == "SuSE" and int(dist.version) < 15:
            self.cancel("lshw not supported on SLES-%s. Please run "
                        "on SLES15 or higher versions only " % dist.version)
        if ((dist.name == 'Ubuntu' and int(dist.version.split('.')[0]) >= 18) or
                (dist.name in ["SuSE", 'debian'])):
            packages.extend(['iproute2'])
        else:
            packages.extend(['iproute'])
        if dist.name in ['Ubuntu', 'debian']:
            if 'IBM' in process.system_output('lshw -class system', shell='true').decode():
                packages.extend(['powerpc-ibm-utils'])

        for package in packages:
            if not sm.check_installed(package) and not sm.install(package):
                self.cancel("Fail to install %s required for this"
                            " test." % package)
        self.lshw_output = self.run_cmd_out("lshw")

    def test_lshw(self):
        """
        lshw without any options would generate full information
        report about all detected hardware.
        """
        self.log.info("===============Executing lshw test ===="
                      "===========")
        self.run_cmd("lshw")
        self.run_cmd("lshw -version")
        self.error_check()

    def test_lshw_short(self):
        """
        With "-short" option,the lshw command would generate a brief
        information report about the hardware devices
        """
        self.log.info("===============Executing lshw -short tests ===="
                      "===========")
        for class_name in ['network', 'storage', 'memory', 'power',
                           'bus', 'processor', 'system']:
            self.run_cmd("lshw -short -class  %s" % class_name)
        self.error_check()

    def test_lshw_class(self):
        """
        To display information about any particular hardware,specify the class.
        """
        self.log.info("===============Executing lshw -class tests ===="
                      "===========")
        for hw_class in ['disk', 'storage', 'memory', 'cpu', 'volume',
                         'network', 'power', 'generic', 'processor',
                         'bridge', 'multimedia', 'display',
                         'system', 'communication', 'bus']:
            self.run_cmd("lshw -class %s" % hw_class)
        self.error_check()

    def test_lshw_verification(self):
        """
        compare the output of lshw with other tools
        which produces similar info of hardware.
        """
        # verifying mac address for active device
        # Equivalent Python code for bash command
        # ip addr | awk '/ether/ {print $2}' | head -1
        mac = ''
        output = self.run_cmd_out("ip addr show %s" % self.active_interface)
        for line in output.splitlines():
            if 'ether' in line:
                mac = line.split()[1]
        if not mac:
            self.cancel("Couldn't get mac address from the active interface.")
        if mac not in self.lshw_output:
            self.fail("lshw failed to show correct mac address")

        # verify network
        if self.active_interface not in self.run_cmd_out("lshw -class network"):
            self.fail("lshw failed to show correct active network interface")

    def test_gen_rep(self):
        """
        Lshw is capable of producing reports in html, xml and json formats.
        """
        self.run_cmd("lshw -xml")
        self.run_cmd("lshw -html -class disk")
        self.run_cmd("lshw -json")
        self.error_check()

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
        lspci_out = self.run_cmd_out("lspci -v ")
        for line in (bus_info.stdout.decode("utf-8")).splitlines():
            get_bus_info_act_inter = line.split(' ')[0]
            if get_bus_info_act_inter in lspci_out:
                if_present = 1
        if not if_present:
            self.fail("Verification of network bus info failed ")

    def test_sanitize(self):
        """
        sanitize output(remove sensitive information like serial numbers,etc.)
        """
        out_with_sanitize = self.run_cmd_out("lshw -sanitize")
        for line in self.lshw_output.strip('\t\n\r').splitlines():
            if ("serial:" in line) and (line in out_with_sanitize):
                self.fail("Sensitive data is present in output")

    def _filter_lshw_data(self, filter_string):
        for line in self.lshw_output.splitlines():
            if filter_string in line:
                return line

    def test_prod_id_serial(self):
        """
        Test verifies the product id and serial number in lshw output.
        """
        self.log.info("===============Validating product id and serial number"
                      "===========")
        if 'KVM' in self.run_cmd_out("pseries_platform"):
            product_path = '/proc/device-tree/host-model'
            serial_path = '/proc/device-tree/host-serial'
        else:
            product_path = '/proc/device-tree/model'
            serial_path = '/proc/device-tree/system-id'

        if 'x86_64' in cpu.get_arch():
            product_name = ""
            serial_num = ""
            dmidecode_op = self.run_cmd_out("dmidecode")
            for line in dmidecode_op.split("\n"):
                if 'Product Name' in line and len(product_name) == 0:
                    product_name = line.split(':')[-1]
                if 'Serial Number' in line and len(serial_num) == 0:
                    serial_num = line.split(':')[-1]
        else:
            product_name = genio.read_file(product_path).rstrip(' \t\r\n\0')
            serial_num = genio.read_file(serial_path).rstrip(' \t\r\n\0')

        if product_name not in self._filter_lshw_data('product'):
            self.is_fail += 1
            self.fail_cmd.append("lshw | grep product | head -1")
        if serial_num not in self._filter_lshw_data('serial'):
            self.is_fail += 1
            self.fail_cmd.append("lshw | grep serial | head -1")
        self.error_check()

    def test_lshw_options(self):
        """
        -disable -> Disables a test.
        -enable -> Enables a test.
        -quiet -> Don't display status.
        -numeric -> Also display numeric IDs.
        """
        self.log.info("===============Verifying -disable, -enable, -quiet,"
                      " and -numeric options ==============")
        cmd = "lshw -disable network"
        if "Ethernet interface" in self.run_cmd_out(cmd):
            self.is_fail += 1
            self.fail_cmd.append(cmd)
        cmd = "lshw -enable network"
        if "Ethernet interface" not in self.run_cmd_out(cmd):
            self.is_fail += 1
            self.fail_cmd.append(cmd)

        self.run_cmd("lshw -class -quiet")
        if 'PowerVM'\
                not in self.run_cmd_out("pseries_platform"):
            lshw_out = self.run_cmd_out("lshw -numeric")
            if 'usb' in lshw_out and 'HCI' not in lshw_out:
                self.is_fail += 1
                self.fail_cmd.append(
                    "lshw -numeric | grep HCI | cut -d':' -f3")
        self.error_check()

    @skipIf(process.system("lshw --help 2>&1 |grep notime",
                           ignore_status=True, sudo=True, shell=True) == 1,
            "-notime option unsupported, skipping")
    def test_lshw_notime(self):
        """
        -notime -> exclude volatile attributes (timestamps) from output.
        """
        self.log.info("===============Verifying -notime option ==============")
        if "modified" in self.run_cmd_out("lshw -notime | grep modified"):
            self.fail("modified time stamp is present evev with -notime")
        self.error_check()
