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
# Copyright: 2021 IBM
# Author: Shirisha Ganta <shirisha.ganta1@ibm.com>

from avocado import Test
from avocado.utils import process, genio
from avocado.utils.software_manager import SoftwareManager
from avocado import skipIf

IS_POWER_NV = 'PowerNV' in genio.read_file('/proc/cpuinfo').rstrip('\t\r\n\0')


class rtas_dbg(Test):

    @skipIf(IS_POWER_NV, "This test is supported on PowerVM environment")
    def setUp(self):
        sm = SoftwareManager()
        if not sm.check_installed("powerpc-utils") and \
           not sm.install("powerpc-utils"):
            self.cancel("Fail to install required 'powerpc-utils' package")

    def test_rtas_dbg(self):
        lists = self.params.get('list', default=['-l', '-l 14', '-l get-power-level'])
        for list_item in lists:
            cmd = "rtas_dbg %s" % list_item
            if process.system(cmd, ignore_status=True, sudo=True):
                self.log.info("%s command failed" % cmd)
                self.fail("rtas_dbg: %s command failed to execute" % cmd)

    def test_negative_rtas_dbg(self):
        # Negative tests
        lists = self.params.get('neg_list', default=['-l get-power', '-l 32'])
        for list_item in lists:
            cmd = "rtas_dbg %s" % list_item
            if not process.system(cmd, ignore_status=True, sudo=True):
                self.log.info("%s command passed" % cmd)
                self.fail("rtas_dbg: Expected failure, %s command exeucted \
                          successfully." % cmd)
