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
from avocado.utils import process, genio, distro
from avocado.utils.software_manager import SoftwareManager
from avocado import skipIf

IS_POWER_NV = 'PowerNV' in genio.read_file('/proc/cpuinfo').rstrip('\t\r\n\0')


class lparnumascore(Test):

    """
    lparnumascore display the NUMA affinity score for the running LPAR.
    The score is a number between 0 and 100. A score of 100 means that all the
    resources are seen correctly, while a score of 0 means that all the resources
    have been moved to different nodes. There is a dedicated score for
    each resource type
    """
    is_fail = 0

    def run_cmd(self, cmd):
        if (process.run(cmd, ignore_status=True, sudo=True, shell=True)).exit_status:
            self.is_fail += 1
        return

    @skipIf(IS_POWER_NV, "This test is supported on PowerVM environment")
    def setUp(self):
        det_dist = distro.detect()
        if det_dist.name == 'SuSE' or det_dist.name \
           == 'rhel' and int(det_dist.version) <= 8 :
            self.cancel("lparnumascore is not supported on %s" % det_dist.name)
        sm = SoftwareManager()
        if not sm.check_installed("powerpc-utils") and \
           not sm.install("powerpc-utils"):
            self.cancel("Fail to install required 'powerpc-utils' package")

    def test_lparnumascore(self):
        self.log.info("===Executing lparnumascore tool====")
        self.run_cmd('lparnumascore')
        lists = self.params.get('list', default=['-c cpu', '-c mem'])
        for list_item in lists:
            self.run_cmd('lparnumascore %s' % list_item)
        if self.is_fail:
            self.fail("%s command(s) failed to execute  "
                      % self.is_fail)
