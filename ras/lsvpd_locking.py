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
# Copyright: 2022 IBM.
# Author: Shirisha G <shirisha.ganta1@ibm.com>


from avocado import Test
from avocado.utils import process, distro
from avocado.utils.software_manager import SoftwareManager


class lsvpd_vpdupdate(Test):

    """
    This test checks for database locking mechanism:
    """

    def setUp(self):
        if "ppc" not in distro.detect().arch:
            self.cancel("supported only on Power platform")
        sm = SoftwareManager()
        if not sm.check_installed("lsvpd") and not sm.install("lsvpd"):
            self.cancel("Fail to install lsvpd required for this test.")

    def test(self):
        cmd = "for i in $(seq 500) ; do vpdupdate & done ;"
        ret = process.run(cmd, ignore_bg_processes=True,
                          ignore_status=True, shell=True)
        cmd1 = "for in in $(seq 200) ; do lsvpd & done ;"
        process.run(cmd1, ignore_bg_processes=True,
                    ignore_status=True, shell=True)
        if 'locked' in ret.stderr.decode("utf-8").strip():
            self.fail("This is expected with the distros which are below sles15sp5 and rhel8.7")
        else:
            self.log.info("Locking mechanism prevented database corruption")
