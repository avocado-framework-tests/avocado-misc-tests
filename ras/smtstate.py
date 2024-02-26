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
from avocado.utils.software_manager.manager import SoftwareManager


class smtstate_tool(Test):

    '''
    smtstate tool allows to save the current smt value and restore it
    '''

    def setUp(self):

        sm = SoftwareManager()
        self.detected_distro = distro.detect()
        deps = ['powerpc-utils', 'time']
        for packages in deps:
            if not sm.check_installed(packages) and not sm.install(packages):
                self.cancel("powerpc-utils is needed for the test to be run")
        smt_op = process.run("ppc64_cpu --smt", shell=True,
                             ignore_status=True).stderr.decode("utf-8")
        if "is not SMT capable" in smt_op:
            self.cancel("Machine is not SMT capable, skipping the test")
        distro_name = self.detected_distro.name
        distro_ver = eval(self.detected_distro.version)
        distro_rel = eval(self.detected_distro.release)
        if distro_name == "rhel":
            if (distro_ver == 7 or
                    (distro_ver == 8 and distro_rel < 4)):
                self.cancel("smtstate tool is supported only after RHEL8.4")
        elif distro_name == "SuSE":
            if (distro_ver == 12 or (distro_ver == 15 and distro_rel < 3)):
                self.cancel("smtstate tool is supported only after SLES15 SP3")
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
                    self.log.info("SMT load is successful for SMT=%s" % j)
                else:
                    self.fail("smt load failed")

    def test_smt_state_switching(self):
        """
        Test to check the time taken for switching between different
        SMT levels. The time taken in general cases should not exceed
        beyond 5 minutes.
        """
        time_in_seconds = self.params.get('time_in_seconds', default=300)
        process.system("ppc64_cpu --smt=on")

        for i in [0, 1, 2, 4]:
            if i == 0:
                cmd_output = process.run(
                    "/usr/bin/time -p ppc64_cpu --smt=off", shell=True,
                    sudo=True)
            elif i == 1:
                cmd_output = process.run(
                    "/usr/bin/time -p ppc64_cpu --smt=on", shell=True,
                    sudo=True)
            else:
                cmd_output = process.run(
                    "/usr/bin/time -p ppc64_cpu --smt=%s" % i,
                    shell=True, sudo=True)

            if (int(cmd_output.duration) > time_in_seconds):
                self.fail("FAIL: SMT has taken longer than expected")
            else:
                self.log.info("Test Passed")
