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
import re
from avocado import Test
from avocado.utils import process, distro, dmesg
from avocado.utils.software_manager.manager import SoftwareManager


class Hwinfo(Test):

    def run_cmd(self, cmd):
        self.log.info("executing ============== %s =================" % cmd)
        if process.system(cmd, ignore_status=True, sudo=True):
            self.fail("hwinfo: %s command failed to execute" % cmd)

    def setUp(self):
        distro_name = distro.detect().name
        if distro_name != 'SuSE':
            self.cancel("This test case not supported on %s" % distro_name)
        sm = SoftwareManager()
        if not sm.check_installed("hwinfo") and not sm.install("hwinfo"):
            self.cancel("Fail to install hwinfo required for this test.")
        dmesg.clear_dmesg()
        self.disk_name = ''
        output = process.system_output("df -h", shell=True).decode().splitlines()
        filtered_lines = [line for line in output
                          if re.search(r'(s|v)d[a-z][1-8]', line)]
        if filtered_lines:
            self.disk_name = filtered_lines[-1].split()[0].strip("12345")
        if not self.disk_name:
            self.cancel("Couldn't get Disk name.")
        self.Unique_Id = ''
        output = process.system_output("hwinfo --disk --only %s"
                                       % self.disk_name, shell=True).decode()
        for line in output.splitlines():
            if 'Unique' in line:
                self.Unique_Id = line.split(":")[1].strip()
                break
        if not self.Unique_Id:
            self.cancel("Couldn't get Unique ID for the disk: %s" %
                        self.disk_name)

    def test_list_options(self):
        lists = self.params.get('list', default=['--all', '--cpu', '--disk'])
        for list_item in lists:
            cmd = "hwinfo %s" % list_item
            self.run_cmd(cmd)

    def test_only(self):
        self.run_cmd("hwinfo --disk --only %s" % self.disk_name)

    def test_unique_id_save(self):
        if not os.path.isdir("/var/lib/hardware/udi"):
            self.cancel("/var/lib/hardware/udi path does not exist")
        self.run_cmd("hwinfo --disk --save-config %s" % self.Unique_Id)
        if "failed" in process.system_output("hwinfo --disk --save-config %s"
                                             % self.Unique_Id,
                                             shell=True).decode("utf-8"):
            self.fail("hwinfo: --save-config UDI option failed")

    def test_unique_id_show(self):
        if not os.path.isdir("/var/lib/hardware/udi"):
            self.cancel("/var/lib/hardware/udi path does not exist")
        self.run_cmd("hwinfo --disk --show-config %s" % self.Unique_Id)
        if "No config" in process.system_output("hwinfo --disk --show-config %s"
                                                % self.Unique_Id,
                                                shell=True).decode("utf-8"):
            self.cancel(
                "hwinfo: --save-config UDI cancelled, no saved config present")

    def test_verbose_map(self):
        self.run_cmd("hwinfo --verbose --map")

    def test_log_file(self):
        self.run_cmd("hwinfo --all --log FILE")
        if (not os.path.exists('./FILE')) or (os.stat("FILE").st_size == 0):
            self.fail("hwinfo: failed with --log option")

    def test_dump(self):
        level = [0, 1]
        for value in level:
            self.run_cmd("hwinfo --dump-db %i" % value)

    def test_version(self):
        self.run_cmd("hwinfo --version")

    def test_help(self):
        self.run_cmd("hwinfo --help")

    def test_debug(self):
        level = [0, 1]
        for value in level:
            self.run_cmd("hwinfo --debug %i --disk --log=-" % value)

    def test_short_block(self):
        self.run_cmd("hwinfo --short --block")

    def test_save_config(self):
        if not os.path.isdir("/var/lib/hardware/udi"):
            self.cancel("/var/lib/hardware/udi path does not exist")
        self.run_cmd("hwinfo --disk --save-config=all")
        if "failed" in process.system_output("hwinfo --disk --save-config=all",
                                             shell=True).decode("utf-8"):
            self.fail("hwinfo: --save-config=all option failed")
