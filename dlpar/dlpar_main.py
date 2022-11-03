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
# Copyright: 2022 IBM
# Author: Kalpana Shetty <kalshett@in.ibm.com>
# Author(Modified): Samir A Mulani <samir@linux.vnet.ibm.com>

import os

from avocado import Test
from avocado.utils import process
from avocado import skipUnless
from avocado.utils import process, distro
from avocado.utils.software_manager import SoftwareManager

IS_POWER_VM = 'pSeries' in open('/proc/cpuinfo', 'r').read()
dlpar_type_flag = ""


class DlparTests(Test):

    """
    Dlpar CPU/MEMORY  tests - ADD/REMOVE/MOVE
    """

    def run_cmd(self, test_cmd, dlpar_type_flag=""):
        os.chmod(test_cmd, 0o755)
        if dlpar_type_flag != "":
            test_cmd = test_cmd + " " + dlpar_type_flag
        result = process.run(test_cmd, shell=True)
        errors = 0
        warns = 0
        for line in result.stdout.decode().splitlines():
            if 'FAILED' in line:
                self.log.info(line)
                errors += 1
            elif 'WARNING' in line:
                self.log.info(line)
                warns += 1

        if errors == 0 and warns > 0:
            self.warn('number of warnings is %s', warns)

        elif errors > 0:
            self.log.warn('number of warnings is %s', warns)
            self.fail("number of errors is %s" % errors)

    @skipUnless(IS_POWER_VM,
                "DLPAR test is supported only on PowerVM platform")
    def setUp(self):
        self.lpar_mode = self.params.get('mode', default='dedicated')
        distro_name = distro.detect().name.lower()
        deps = ['sshpass']
        smm = SoftwareManager()
        if distro_name != 'rhel':
            self.cancel(
                "To run the test, the sshpass package needs to be \
                installed on the current platform..!!")

        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel("Failed to install %s, which is needed for"
                            "the test to be run" % package)

    def dlpar_engine(self):
        '''
        Call and create the log file as per dlpar test case
        Ex: With and without workload(smt, cpu_fold etc)
        '''
        test_cmd = ""
        dlpar_type_flag = ""
        if self.lpar_mode == 'dedicated' or self.lpar_mode \
                == 'ded_smt_workload' or self.lpar_mode \
                == 'ded_cpu_fold_workload':
            self.log.info("Dedicated Lpar....")
            self.test_case = self.params.get('test_case', default='cpu')
            self.log.info("TestCase: %s" % self.test_case)
            if self.test_case == 'cpu':
                test_mode = "DED {}: Calling dedicated_cpu.py".format(
                    self.lpar_mode)
                if self.lpar_mode != 'dedicated':
                    self.log.info(test_mode)
                else:
                    self.log.info("DED : Calling dedicated_cpu.py")
                if (self.lpar_mode == 'ded_smt_workload' or self.lpar_mode
                        == 'ded_cpu_fold_workload'):
                    logfile_name = self.lpar_mode + ".log"
                    dlpar_type_flag = logfile_name
                    # test_cmd = './dedicated_cpu.py ' + logfile_name
                    test_cmd = './dedicated_cpu.py'
                else:
                    test_cmd = './dedicated_cpu.py'
            elif self.test_case == 'mem':
                test_mode = "DED {}: Calling memory.py".format(self.lpar_mode)
                if self.lpar_mode != 'dedicated':
                    self.log.info(test_mode)
                else:
                    self.log.info("DED: Calling memory.py")
                if (self.lpar_mode == 'ded_smt_workload' or self.lpar_mode
                        == 'ded_cpu_fold_workload'):
                    logfile_name = self.lpar_mode + ".log"
                    dlpar_type_flag = logfile_name
                    # test_cmd = './memory.py ' + logfile_name
                    test_cmd = './memory.py'
                else:
                    test_cmd = './memory.py'

        elif self.lpar_mode == 'shared' or self.lpar_mode == \
                'sha_smt_workload' or self.lpar_mode == \
                'sha_cpu_fold_workload':
            self.log.info("Shared Lpar.....")
            self.test_case = self.params.get('test_case', default='cpu')
            self.log.info("TestCase: %s" % self.test_case)
            if self.test_case == 'cpu':
                self.log.info("SHR: Calling cpu_unit.py")
                test_cmd = './cpu_unit.py'
            elif self.test_case == 'mem':
                self.log.info("SHR: Calling memory.py")
                test_cmd = './memory.py'

        if test_cmd != "":
            self.run_cmd(test_cmd, dlpar_type_flag)

    def test_dlpar(self):
        '''
        Execute dlpar dedicated/shared and memory tests
        '''
        dlpar_type_flag = ""
        if (self.lpar_mode == 'ded_smt_workload' or self.lpar_mode ==
                'sha_smt_workload'):
            dlpar_type_flag = "smt"
            self.log.info(
                "SMT Workload: Calling ./dlpar_workload_setup.py ")
            test_cmd = './dlpar_workload_setup.py'
            self.run_cmd(test_cmd, "smt")
        if (self.lpar_mode == 'ded_cpu_fold_workload' or self.lpar_mode ==
                'sha_cpu_fold_workload'):
            dlpar_type_flag = "cpu_fold"
            self.log.info(
                    "CPU folding Workload: Calling ./dlpar_workload_setup.py")
            test_cmd = './dlpar_workload_setup.py'
            self.run_cmd(test_cmd, "cpu_fold")
        self.dlpar_engine()
        if dlpar_type_flag != "":
            test_cmd = './dlpar_workload_setup.py'
            if dlpar_type_flag == "smt":
                self.run_cmd(test_cmd, "smt:kill_process")
            elif dlpar_type_flag == "cpu_fold":
                self.run_cmd(test_cmd, "cpu_fold:kill_process")
