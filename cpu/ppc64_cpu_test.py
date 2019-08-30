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
# Author: Narasimhan V <sim@linux.vnet.ibm.com>

"""
Test to verify ppc64_cpu command.
"""

import os
import glob
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils import cpu
from avocado.utils import distro
from avocado.utils import genio
from avocado.utils.software_manager import SoftwareManager


class PPC64Test(Test):
    """
    Test to verify ppc64_cpu command for different supported values.

    :avocado: tags=cpu,power,privileged
    """

    def setUp(self):
        """
        Verifies if powerpc-utils is installed, and gets current SMT value.
        """
        if 'ppc' not in distro.detect().arch:
            self.cancel("Processor is not ppc64")
        if SoftwareManager().check_installed("powerpc-utils") is False:
            if SoftwareManager().install("powerpc-utils") is False:
                self.cancel("powerpc-utils is not installing")
        self.smt_str = "ppc64_cpu --smt"
        smt_op = process.system_output(self.smt_str, shell=True).decode()
        if "is not SMT capable" in smt_op:
            self.cancel("Machine is not SMT capable")
        if "Inconsistent state" in smt_op:
            self.cancel("Machine has mix of ST and SMT cores")

        self.curr_smt = smt_op.strip().split("=")[-1].split()[-1]
        self.smt_subcores = 0
        if os.path.exists("/sys/devices/system/cpu/subcores_per_core"):
            self.smt_subcores = 1
        self.failures = 0
        self.failure_message = "\n"
        self.smt_values = {1: "off"}
        self.key = 0
        self.value = ""
        self.max_smt_value = 4
        if cpu.get_cpu_arch().lower() == 'power9':
            if 'Hash' in genio.read_file('/proc/cpuinfo').rstrip('\t\r\n\0'):
                self.max_smt_value = 8
        if cpu.get_cpu_arch().lower() == 'power8':
            self.max_smt_value = 8
        if cpu.get_cpu_arch().lower() == 'power6':
            self.max_smt_value = 2

    def equality_check(self, test_name, cmd1, cmd2):
        """
        Verifies if the output of 2 commands are same, and sets failure
        count accordingly.

        :params test_name: Test Name
        :params cmd1: Command 1
        :params cmd2: Command 2
        """
        self.log.info("Testing %s", test_name)
        if str(cmd1) != str(cmd2):
            self.failures += 1
            self.failure_message += "%s test failed when SMT=%s\n" \
                % (test_name, self.key)

    def test_cmd_options(self):
        """
        Sets the SMT value, and calls each of the test, for each value.
        """
        for i in range(2, self.max_smt_value + 1):
            self.smt_values[i] = str(i)
        for self.key, self.value in self.smt_values.items():
            process.system_output("%s=%s" % (self.smt_str,
                                             self.key), shell=True)
            process.system_output("ppc64_cpu --info")
            self.smt()
            self.core()
            if self.smt_subcores == 1:
                self.subcore()
            self.threads_per_core()
            self.smt_snoozedelay()
            self.dscr()

        if self.failures > 0:
            self.log.debug("Number of failures is %s", self.failures)
            self.log.debug(self.failure_message)
            self.fail()

    def smt(self):
        """
        Tests the SMT in ppc64_cpu command.
        """
        op1 = process.system_output(
            self.smt_str,
            shell=True).decode("utf-8").strip().split("=")[-1].split()[-1]
        self.equality_check("SMT", op1, self.value)

    def core(self):
        """
        Tests the core in ppc64_cpu command.
        """
        op1 = process.system_output(
            "ppc64_cpu --cores-present",
            shell=True).decode("utf-8").strip().split()[-1]
        op2 = cpu.online_cpus_count() / int(self.key)
        self.equality_check("Core", op1, op2)

    def subcore(self):
        """
        Tests the subcores in ppc64_cpu command.
        """
        op1 = process.system_output(
            "ppc64_cpu --subcores-per-core",
            shell=True).decode("utf-8").strip().split()[-1]
        op2 = genio.read_file(
            "/sys/devices/system/cpu/subcores_per_core").strip()
        self.equality_check("Subcore", op1, op2)

    def threads_per_core(self):
        """
        Tests the threads per core in ppc64_cpu command.
        """
        op1 = process.system_output(
            "ppc64_cpu --threads-per-core",
            shell=True).decode("utf-8").strip().split()[-1]
        op2 = process.system_output("ppc64_cpu --info",
                                    shell=True).decode("utf-8")
        op2 = len(op2.strip().splitlines()[0].split(":")[-1].split())
        self.equality_check("Threads per core", op1, op2)

    def smt_snoozedelay(self):
        """
        Tests the smt snooze delay in ppc64_cpu command.
        """
        snz_content = set()
        op1 = process.system_output(
            "ppc64_cpu --smt-snooze-delay",
            shell=True).decode("utf-8").strip().split()[-1]
        snz_delay = "cpu*/smt_snooze_delay"
        if os.path.isdir("/sys/bus/cpu/devices"):
            snz_delay = "/sys/bus/cpu/devices/%s" % snz_delay
        else:
            snz_delay = "/sys/devices/system/cpu/%s" % snz_delay
        for filename in glob.glob(snz_delay):
            snz_content.add(genio.read_file(filename).strip())
        op2 = list(snz_content)[0]
        self.equality_check("SMT snooze delay", op1, op2)

    def dscr(self):
        """
        Tests the dscr in ppc64_cpu command.
        """
        op1 = process.system_output(
            "ppc64_cpu --dscr", shell=True).decode("utf-8").strip().split()[-1]
        op2 = int(genio.read_file(
            "/sys/devices/system/cpu/dscr_default").strip(), 16)
        self.equality_check("DSCR", op1, op2)

    def test_smt_loop(self):
        """
        Tests smt on/off in a loop
        """
        for _ in range(1, 100):
            if process.system("%s=off && %s=on" % (self.smt_str, self.smt_str),
                              shell=True):
                self.fail('SMT loop test failed')

    def tearDown(self):
        """
        Sets back SMT to original value as was before the test.
        """
        process.system_output("%s=%s" % (self.smt_str,
                                         self.curr_smt), shell=True)
        process.system_output("dmesg")


if __name__ == "__main__":
    main()
