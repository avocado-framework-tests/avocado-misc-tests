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
#
# Copyright: 2016 IBM
# Author: Pavithra D P <pavithra@linux.vnet.ibm.com>

import random
import platform
from avocado import Test
from avocado import main
from avocado import skipIf
from avocado.utils import process, distro
from avocado.utils.software_manager import SoftwareManager


# TODO : Logic need to change when we have lib fix
IS_POWER_NV = 'PowerNV' in open('/proc/cpuinfo', 'r').read()


class cpupower(Test):

    """
    Testing cpupower command

    :avocado: tags=cpu,power,privileged
    """

    @skipIf(not IS_POWER_NV, "This test is not supported on PowerVM platform")
    def setUp(self):
        smm = SoftwareManager()
        detected_distro = distro.detect()
        kernel_ver = platform.uname()[2]
        if 'Ubuntu' in detected_distro.name:
            deps = ['linux-tools-common', 'linux-tools-%s' % kernel_ver]
        else:
            deps = ['powerpc-utils']

        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

    def test(self):
        self.error_count = 0
        self.cpu = 0
        self.log.info("Get the initial values from the system")
        (min, max, cur, initial_governor) = self.get_initial_values()
        governors = self.get_list_governors()
        for governor in governors:
            if governor in ["ondemand", "conservative", "schedutil"]:
                self.log.info("Dynamic governors,need manual verification")
            else:
                self.log.info("Checking %s governor" % governor)
                self.check_governor(governor, min, max, cur)
        self.log.info("Set the final values on the system")
        self.final_freq(cur, initial_governor)
        if self.error_count:
            self.fail("Test failed with errors")
            self.log.info("The value of error count %s" % (self.error_count))
        else:
            self.log.info("Test passed successfully")

    def get_initial_values(self):
        """
        To get the initial frequency and governor set on system
        """
        min = self.cpu_freq_path('scaling_min_freq', self.cpu)
        max = self.cpu_freq_path('scaling_max_freq', self.cpu)
        cur = self.cpu_freq_path('scaling_cur_freq', self.cpu)
        initial_governor = self.cpu_freq_path('scaling_governor', self.cpu)
        return (min, max, cur, initial_governor)

    def cpu_freq_path(self, file, cpu_num):
        """
        get cpu_freq values
        :param: file: is filename which data needs to be fetched
        :param: cpu_num is value for cpu
        """
        filename = "/sys/devices/system/cpu/cpu%s/cpufreq/%s" % (cpu_num, file)
        return open(filename, 'r').readline().strip('\n').strip(' ')

    def get_list_governors(self):
        """
        Get the list of governors available on the system
        """
        return self.cpu_freq_path('scaling_available_governors',
                                  self.cpu).split()

    def check_governor(self, governor, min, max, cur):
        """
        Validate governor
        """
        if governor == "powersave":
            self.check_powersave_governor(governor, min)
        if governor == "performance":
            self.check_performance_governor(governor, max)
        if governor == "userspace":
            self.check_userspace_governor(governor)

    def set_governor(self, governor):
        """
        Governor setting function
        :param governor: Setting specified governor on the system
        """
        cmd = "cpupower frequency-set -g %s" % (governor)
        output = process.run(cmd)
        cur_governor = self.cpu_freq_path('scaling_governor', self.cpu).strip()
        if (output.exit_status == 0) and (governor == cur_governor):
            self.log.info("%s governor set successfully" % governor)
            return True
        else:
            self.log.error("%s governor set failed" % governor)
            self.error_count += 1
            return False

    def get_cur_freq(self):
        """
        Get the current frequency info on system
        """
        cmd = "cpupower -c %s frequency-info -f" % (self.cpu)
        return process.system_output(cmd).splitlines()[1].split()[3]

    def get_random_freq(self):
        """
        Get random frequency from list
        """
        cmd = "scaling_available_frequencies"
        return random.choice(self.cpu_freq_path(cmd, self.cpu).split(' '))

    def set_freq_val(self, freq):
        """
        Set the freequency value specified in argument
        """
        cmd = "cpupower frequency-set -f %s" % (freq)
        output = process.run(cmd)
        cur_freq = self.get_cur_freq()
        if (output.exit_status == 0) and (cur_freq == freq):
            self.log.info("The userspace governor is working as expected")
        else:
            self.log.error("Userspace governor failed")
            self.error_count += 1

    def check_performance_governor(self, governor, max):
        """
        Validate Performance Governor
        """
        if self.set_governor(governor):
            cur_freq = self.get_cur_freq()
            if cur_freq == max:
                self.log.info("%s governor working as expected" % governor)
            else:
                self.log.error("%s governor not working as expected"
                               % governor)
                self.error_count += 1

    def check_powersave_governor(self, governor, min):
        """
        Validate Powersave governor
        """
        if self.set_governor(governor):
            cur_freq = self.get_cur_freq()
            if cur_freq == min:
                self.log.info("%s governor working as expected" % governor)
            else:
                self.log.error("%s governor not working as expected"
                               % governor)
                self.error_count += 1

    def check_userspace_governor(self, governor):
        """
        Validate Userspace Governor
        """
        return_value = self.set_governor(governor)
        if return_value:
            for var in range(3):
                self.set_freq_val(self.get_random_freq())

    def final_freq(self, cur, initial_governor):
        """
        Set the system with Intial values
        :param cur: Current frequency which was set on system
        :prama initial_governor: Initial governor which was set on the system
        """
        if initial_governor == "userspace":
            self.set_governor(initial_governor)
            self.set_freq_val(cur)
        else:
            self.set_governor(initial_governor)


if __name__ == "__main__":
    main()
