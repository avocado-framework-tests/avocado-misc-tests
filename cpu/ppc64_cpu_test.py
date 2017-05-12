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
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils import cpu
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
        command = "uname -p"
        if 'ppc' not in process.system_output(command, ignore_status=True):
            self.skip("Processor is not ppc64")
        if SoftwareManager().check_installed("powerpc-utils") is False:
            if SoftwareManager().install("powerpc-utils") is False:
                self.skip("powerpc-utils is not installing")
        if "is not SMT capable" in process.system_output("ppc64_cpu --smt"):
            self.skip("Machine is not SMT capable")
        self.curr_smt = process.system_output("ppc64_cpu --smt | awk -F'=' \
                '{print $NF}' | awk '{print $NF}'", shell=True)
        self.smt_subcores = 0
        if os.path.exists("/sys/devices/system/cpu/subcores_per_core"):
            self.smt_subcores = 1
        self.failures = 0
        self.failure_message = "\n"
        self.smt_values = {1: "off"}
        self.key = 0
        self.value = ""
        self.max_smt_value = 8
        if cpu.get_cpu_arch().lower() == 'power7':
            self.max_smt_value = 4
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
        self.log.info("Testing %s" % test_name)
        if process.system_output(cmd1, shell=True) != \
                process.system_output(cmd2, shell=True):
            self.failures += 1
            self.failure_message += "%s test failed when SMT=%s\n" \
                % (test_name, self.key)

    def test(self):
        """
        Sets the SMT value, and calls each of the test, for each value.
        """
        for i in range(2, self.max_smt_value + 1):
            self.smt_values[i] = str(i)
        for self.key, self.value in self.smt_values.iteritems():
            process.system_output("ppc64_cpu --smt=%s" % self.key, shell=True)
            process.system_output("ppc64_cpu --info")
            self.smt()
            self.core()
            if self.smt_subcores == 1:
                self.subcore()
            self.threads_per_core()
            self.smt_snoozedelay()
            self.dscr()

        self.smt_loop()

        if self.failures > 0:
            self.log.debug("Number of failures is %s" % self.failures)
            self.log.debug(self.failure_message)
            self.fail()

        process.system_output("dmesg")

    def smt(self):
        """
        Tests the SMT in ppc64_cpu command.
        """
        command1 = "ppc64_cpu --smt | awk -F'=' '{print $NF}' | awk \
                '{print $NF}'"
        command2 = "echo %s" % self.value
        self.equality_check("SMT", command1, command2)

    def core(self):
        """
        Tests the core in ppc64_cpu command.
        """
        command1 = "ppc64_cpu --cores-present | awk '{print $NF}'"
        command2 = "expr $(grep -w processor /proc/cpuinfo | wc -l) / %d" \
            % self.key
        self.equality_check("Core", command1, command2)

    def subcore(self):
        """
        Tests the subcores in ppc64_cpu command.
        """
        command1 = "ppc64_cpu --subcores-per-core | awk '{print $NF}'"
        command2 = "cat /sys/devices/system/cpu/subcores_per_core"
        self.equality_check("Subcore", command1, command2)

    def threads_per_core(self):
        """
        Tests the threads per core in ppc64_cpu command.
        """
        command1 = "ppc64_cpu --threads-per-core | awk '{print $NF}'"
        command2 = "ppc64_cpu --info | grep '[0-9]*' | cut -d ':' -f2- | \
                head -1 | wc -w"
        self.equality_check("Threads per core", command1, command2)

    def smt_snoozedelay(self):
        """
        Tests the smt snooze delay in ppc64_cpu command.
        """
        command1 = "ppc64_cpu --smt-snooze-delay | awk '{print $NF}'"
        command2 = "cat /sys/bus/cpu/devices/cpu*/smt_snooze_delay | uniq"
        self.equality_check("SMT snooze delay", command1, command2)

    def dscr(self):
        """
        Tests the dscr in ppc64_cpu command.
        """
        command1 = "ppc64_cpu --dscr | awk '{print $NF}'"
        command2 = "cat /sys/devices/system/cpu/dscr_default"
        self.equality_check("DSCR", command1, command2)

    def smt_loop(self):
        """
        Tests smt on/off in a loop
        """
        for _ in range(1, 100):
            process.run("ppc64_cpu --smt=off && ppc64_cpu --smt=on",
                        shell=True)

    def tearDown(self):
        """
        Sets back SMT to original value as was before the test.
        """
        process.system_output("ppc64_cpu --smt=%s" % self.curr_smt, shell=True)


if __name__ == "__main__":
    main()
