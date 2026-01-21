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
# Copyright: 2023 IBM
# Author: Shirisha Ganta <shirisha@linux.ibm.com>

from avocado import Test
from avocado.utils import process, distro
from avocado.utils.software_manager.manager import SoftwareManager


class dlpar_smtcheck(Test):

    '''
    1.Check smt state
    2.Perform the DLPAR cpu add operation.
    3.Check SMT state again, check if it matched before operation state
      if it does not match fail
    '''

    def setUp(self):

        sm = SoftwareManager()
        self.detected_distro = distro.detect()
        if not sm.check_installed("powerpc-utils") and \
                not sm.install("powerpc-utils"):
            self.cancel("powerpc-utils is needed for the test to be run")
        smt_op = process.run("ppc64_cpu --smt", shell=True,
                             ignore_status=True).stderr.decode("utf-8")
        if "is not SMT capable" in smt_op:
            self.cancel("Machine is not SMT capable, skipping the test")

    def test(self):

        process.system("ppc64_cpu --smt=on")
        lcpu_count = process.system_output("lparstat -i | "
                                           "grep \"Online Virtual CPUs\" | "
                                           "cut -d':' -f2", shell=True)
        if lcpu_count:
            lcpu_count = int(lcpu_count)
            if lcpu_count >= 2:
                process.system("drmgr -c cpu -r 1")
                for i in range(1, 9):
                    process.system("ppc64_cpu --smt=%s" % i)
                    smt_initial = process.system_output(
                        "ppc64_cpu --smt", shell=True)
                    process.system("drmgr -c cpu -a 1")
                    smt_final = process.system_output(
                        "ppc64_cpu --smt", shell=True)
                    process.system("drmgr -c cpu -r 1")
                    if smt_initial == smt_final:
                        self.log.info(
                            "newly added CPU is running at the correct SMT level %s" % i)
                    else:
                        self.fail(
                            "newly added CPU is not running at the correct SMT level %s" % i)
        else:
            self.fail("configure more than one CPU")
