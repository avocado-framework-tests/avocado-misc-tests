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
# Copyright: 2021 IBM
# Author: Pavithra Prakash <pavrampu@linux.vnet.ibm.com>

from avocado import Test
from avocado.utils import process, distro
from avocado.utils.software_manager import SoftwareManager


class smtstate_tool(Test):

    '''
    smtstate tool allows to save the current smt value and restore it
    '''

    def setUp(self):

        sm = SoftwareManager()
        self.detected_distro = distro.detect()
        if not sm.check_installed("powerpc-utils") and \
                not sm.install("powerpc-utils"):
            self.cancel("powerpc-utils is needed for the test to be run")
        distro_name = self.detected_distro.name
        distro_ver = self.detected_distro.version
        distro_rel = self.detected_distro.release
        if distro_name == "rhel":
            if (distro_ver < "8" or distro_rel < "4"):
                self.cancel("smtstate tool is supported only after rhel8.4")
        elif distro_name == "SuSE":
            if (distro_ver < 15 or distro_rel < 3):
                self.cancel("smtstate tool is supported only after sles15 sp3")
        else:
            self.cancel("Test case is supported only on RHEL and SLES")

    def test(self):

        process.system("ppc64_cpu --smt=on")
        for i in ["off", "on", 4, 2]:
            for j in [2, 4, "on", "off"]:
                process.system("ppc64_cpu --smt=%s" % j)
                smt_initial = process.system_output(
                    "ppc64_cpu --smt", shell=True)
                if process.system("smtstate --save", ignore_status=True):
                    self.fail("smtstate save failed")
                process.system("ppc64_cpu --smt=%s" % i)
                self.log.info("SMT level before load = %s" %
                              process.system_output("ppc64_cpu --smt"))
                if process.system("smtstate --load", ignore_status=True):
                    self.fail("smtstate load failed")
                smt_final = process.system_output(
                    "ppc64_cpu --smt", shell=True)
                self.log.info("SMT level after load = %s" %
                              process.system_output("ppc64_cpu --smt"))
                if smt_initial == smt_final:
                    print("SMT load is successful for SMT=%s" % j)
                else:
                    self.fail("smt load failed")
