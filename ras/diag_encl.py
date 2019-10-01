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
# Copyright: 2018 IBM
# Author: Pavithra <pavrampu@linux.vnet.ibm.com>

import os
import glob
import xml.etree.ElementTree
from avocado import Test
from avocado import main
from avocado.utils import process, distro
from avocado.utils import genio
from avocado.utils.software_manager import SoftwareManager


class DiagEncl(Test):

    """
    This test checks various options of diag_encl tool:
    """
    is_fail = 0

    def run_cmd(self, cmd):
        if (process.run(cmd, ignore_status=True, sudo=True,
                        shell=True)).exit_status:
            self.is_fail += 1
        return

    @staticmethod
    def run_cmd_out(cmd):
        return process.system_output(cmd, shell=True,
                                     ignore_status=True,
                                     sudo=True).decode("utf-8")

    def setUp(self):
        if "ppc" not in distro.detect().arch:
            self.cancel("supported only on Power platform")
        sof_m = SoftwareManager()
        if not sof_m.check_installed("ppc64-diag"):
            self.cancel("ppc64-diag is not installed by default.")

    def test_diag_encl(self):
        self.log.info("===========Executing diag_encl test==========")
        diag_path = '/var/log/ppc64-diag/diag_disk/'
        if 'disk health' not in self.run_cmd_out("diag_encl -h"):
            self.fail("'-d' option is not available in help message")
        self.run_cmd("vpdupdate")
        if not os.path.isdir(diag_path):
            self.run_cmd_out("diag_encl -d")
        for _ in range(4):
            self.run_cmd("diag_encl -d")
        no_of_files = len(glob.glob1(diag_path, "*diskAnalytics*"))

        if no_of_files == 0:
            self.fail("xml file not generated")
        if no_of_files > 1:
            self.fail("multiple xml files are generated")
        xml_file = os.listdir(diag_path)[0]
        xml_file = os.path.join(diag_path, xml_file)
        e_xml = xml.etree.ElementTree.parse(xml_file).getroot()
        machine_type = e_xml.find('Machine').get('type').strip()
        machine_model = e_xml.find('Machine').get('model').strip()
        machine_serial_xml = e_xml.find('Machine').get('serial').strip()
        if 'KVM' in self.run_cmd_out("pseries_platform"):
            product_path = '/proc/device-tree/host-model'
            serial_path = '/proc/device-tree/host-serial'
        else:
            product_path = '/proc/device-tree/model'
            serial_path = '/proc/device-tree/system-id'
        product_name = genio.read_one_line(product_path).rstrip(' \t\r\n\0')
        if 'PowerNV' not in open('/proc/cpuinfo', 'r').read():
            product_name = product_name.split(',')[1]
        serial_num = genio.read_one_line(serial_path).rstrip(' \t\r\n\0')
        product_name_xml = "-".join((machine_type, machine_model))
        if product_name_xml != product_name:
            self.fail("type and model are incorrect")
        if machine_serial_xml not in serial_num:
            self.fail("serial is incorrect")


if __name__ == "__main__":
    main()
