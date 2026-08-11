#!/usr/bin/env python
#
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
# Copyright: 2019 IBM
# Author: Nageswara R Sastry <rnsastry@linux.vnet.ibm.com>

import os
from avocado import Test
from avocado.utils import process, dmesg
from avocado.utils.software_manager.distro_packages import ensure_tool


class perf_bench(Test):

    """
    Tests perf bench and it's options
    :avocado: tags=perf,bench
    """

    def setUp(self):
        '''
        Install the basic packages to support perf
        '''

        # Check for basic utilities
        perf_path = self.params.get('perf_bin', default='')
        distro_pkg_map = {
            "Ubuntu": [f"linux-tools-{os.uname()[2]}", "linux-tools-common"],
            "debian": ["linux-perf"],
            "centos": ["perf"],
            "fedora": ["perf"],
            "rhel": ["perf"],
            "SuSE": ["perf"],
        }
        try:
            perf_version = ensure_tool("perf", custom_path=perf_path,
                                       distro_pkg_map=distro_pkg_map)
            self.log.info(f"Perf version: {perf_version}")
            self.perf_bin = perf_path if perf_path else "perf"
        except RuntimeError as e:
            self.cancel(str(e))

        # Getting the parameters from yaml file
        self.optname = self.params.get('name', default='all')
        self.option = self.params.get('option', default='')

        # Clear the dmesg, by that we can capture the delta at the end of the test.
        dmesg.clear_dmesg()

    def verify_dmesg(self):
        self.whiteboard = process.system_output("dmesg").decode("utf-8")
        pattern = ['WARNING: CPU:', 'Oops',
                   'Segfault', 'soft lockup', 'Unable to handle']
        for fail_pattern in pattern:
            if fail_pattern in self.whiteboard:
                self.fail("Test Failed : %s in dmesg" % fail_pattern)

    def run_cmd(self, cmd):
        err_ln = "Assertion `!(ret)' failed"
        try:
            op = process.run(cmd, ignore_status=False, sudo=True)
        except process.CmdError as details:
            self.fail("Command %s failed: %s" % (cmd, details))
        output = op.stdout.decode() + op.stderr.decode()
        if err_ln in output:
            self.fail("command %s failed with assertion code" % cmd)

    def test_bench(self):
        # perf bench command
        bench_cmd = "%s bench %s %s" % (self.perf_bin, self.optname, self.option)
        self.run_cmd(bench_cmd)
        self.verify_dmesg()
