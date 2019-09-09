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
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils import distro
from avocado.utils.software_manager import SoftwareManager


class Hwinfo(Test):

    def clear_dmesg(self):
        process.run("dmesg -C ", sudo=True)

    def run_cmd(self, cmd):
        self.log.info("executing ============== %s =================" % cmd)
        if process.system(cmd, ignore_status=True, sudo=True):
            self.log.info("%s command failed" % cmd)
            self.fail("hwinfo: %s command failed to execute" % cmd)

    def setUp(self):
        # FIXME: "redhat" as the distro name for RHEL is deprecated
        # on Avocado versions >= 50.0.  This is a temporary compatibility
        # enabler for older runners, but should be removed soon
        if distro.detect().name in ['rhel', 'redhat']:
            self.cancel('Hwinfo not supported on RHEL')
        sm = SoftwareManager()
        if not sm.check_installed("hwinfo") and not sm.install("hwinfo"):
            self.cancel("Fail to install hwinfo required for this test.")
        self.clear_dmesg()
        self.disk_name = process.system_output("df -h | egrep '(s|v)d[a-z][1-8]' | "
                                               "tail -1 | cut -d' ' -f1",
                                               shell=True).decode("utf-8").strip("12345")
        self.Unique_Id = process.system_output("hwinfo --disk --only %s | "
                                               "grep 'Unique' | head -1 | "
                                               "cut -d':' -f2" % self.disk_name,
                                               shell=True).decode("utf-8")

    def test_list(self):
        lists = self.params.get('list', default=['--all', '--cpu', '--disk'])
        for list_item in lists:
            cmd = "hwinfo %s" % list_item
            self.run_cmd(cmd)

    def test_disk(self):
        self.run_cmd("hwinfo --disk --only %s" % self.disk_name)

    def test_unique_id_save(self):
        self.run_cmd("hwinfo --disk --save-config %s" % self.Unique_Id)

    def test_unique_id_show(self):
        self.run_cmd("hwinfo --disk --show-config %s" % self.Unique_Id)

    def test_verbose_map(self):
        self.run_cmd("hwinfo --verbose --map")

    def test_log_file(self):
        self.run_cmd("hwinfo --all --log FILE")
        if (not os.path.exists('./FILE')) or (os.stat("FILE").st_size == 0):
            self.log.info("--log option failed")
            self.fail("hwinfo: failed with --log option")

    def test_dump_0(self):
        self.run_cmd("hwinfo --dump-db 0")

    def test_dump_1(self):
        self.run_cmd("hwinfo --dump-db 1")

    def test_version(self):
        self.run_cmd("hwinfo --version")

    def test_help(self):
        self.run_cmd("hwinfo --help")

    def test_debug(self):
        self.run_cmd("hwinfo --debug 0 --disk --log=-")

    def test_short_block(self):
        self.run_cmd("hwinfo --short --block")

    def test_save_config(self):
        self.run_cmd("hwinfo --disk --save-config=all")
        if "failed" in process.system_output("hwinfo --disk --save-config=all",
                                             shell=True).decode("utf-8"):
            self.log.info("--save-config option failed")
            self.fail("hwinfo: --save-config option failed")


if __name__ == "__main__":
    main()
