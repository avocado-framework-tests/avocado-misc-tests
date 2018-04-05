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
import xml.etree.ElementTree
from avocado import Test
from avocado import main
from avocado.utils import process, distro
from avocado.utils.software_manager import SoftwareManager


class diag_encl(Test):

    """
    This test checks various options of diag_encl tool:
    """
    is_fail = 0

    def run_cmd(self, cmd):
        if (process.run(cmd, ignore_status=True, sudo=True, shell=True)).exit_status:
            self.is_fail += 1
        return

    def run_cmd_out(self, cmd):
        return process.system_output(cmd, shell=True, ignore_status=True, sudo=True)

    def setUp(self):
        if "ppc" not in distro.detect().arch:
            self.cancel("supported only on Power platform")
        sm = SoftwareManager()
        if not sm.check_installed("ppc64-diag"):
            self.fail("ppc64-diag is not installed by default.")

    def test_diag_encl(self):
        self.log.info("===========Executing diag_encl test==========")
        diag_path = '/var/log/ppc64-diag/diag_disk/'
        if not os.path.isdir(diag_path):
            self.fail('diag_disk path does not exists.')
        if not self.run_cmd_out("diag_encl -h | grep -Eai '\-d'").strip():
            self.fail("'-d' option is not available in help message")
        for i in range(4):
            self.run_cmd("diag_encl -d")
        xml_file_path = os.path.join(diag_path, '*diskAnalytics*')
        no_of_files = self.run_cmd_out("ls -lrt %s | wc -l" % xml_file_path).strip()
        if no_of_files == '0':
            self.fail("xml file not generated")
        if no_of_files > '1':
            self.fail("multiple xml files are generated")
        else:
            self.log.info("single xml file is generated")
        xml_file = self.run_cmd_out("ls %s" % diag_path).strip()
        xml_file = os.path.join(diag_path, xml_file)
        e = xml.etree.ElementTree.parse(xml_file).getroot()
        machine_type = e.find('Machine').get('type').strip()
        machine_model = e.find('Machine').get('model').strip()
        machine_serial_xml = e.find('Machine').get('serial').strip()
        if 'KVM' in self.run_cmd_out("pseries_platform"):
            product_path = '/proc/device-tree/host-model'
            serial_path = '/proc/device-tree/host-serial'
        else:
            product_path = '/proc/device-tree/model'
            serial_path = '/proc/device-tree/system-id'
        product_name = self.run_cmd_out("cat %s" % product_path).rstrip(' \t\r\n\0')
        serial_num = self.run_cmd_out("cat %s" % serial_path).rstrip(' \t\r\n\0')
        product_name_xml = "-".join( (machine_type, machine_model) )
        if product_name_xml != product_name:
            self.fail("type and model are incorrect")
        if machine_serial_xml not in serial_num:
            self.fail("serial is incorrect")


if __name__ == "__main__":
    main()
