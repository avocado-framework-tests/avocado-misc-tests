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
# Copyright: 2017 IBM
# Author: Shriya Kulkarni <shriyak@linux.vnet.ibm.com>
import random
import platform
from avocado import Test
from avocado import main
from avocado import skipIf
from avocado.utils import process, distro, cpu
from avocado.utils.software_manager import SoftwareManager

IS_POWER_NV = 'PowerNV' in open('/proc/cpuinfo', 'r').read()


class Cpufreq(Test):
    """
    Test to validate the frequency transition.

    :avocado: tags=cpu,power
    """
    @skipIf(not IS_POWER_NV, "This test is not supported on PowerVM platform")
    def setUp(self):
        smm = SoftwareManager()
        detected_distro = distro.detect()
        if 'Ubuntu' in detected_distro.name:
            deps = ['linux-tools-common', 'linux-tools-%s'
                    % platform.uname()[2]]
        else:
            deps = ['kernel-tools']
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

    def test(self):
        """
        Set the governor to userspace
        choose random frequency and cpu
        validate the frequency is set using ppc64_cpu tool.
        """
        self.cpu = 0
        threshold = 10000
        output = process.run("cpupower frequency-set -g userspace", shell=True)
        cur_governor = self.cpu_freq_path('scaling_governor')
        if 'userspace' == cur_governor and output.exit_status == 0:
            self.log.info("%s governor set successfully" % cur_governor)
        else:
            self.cancel("Unable to set the userspace governor")
        for var in range(1, 10):
            self.cpu = self.__get_random_cpu()
            self.log.info(" cpu is %s" % self.cpu)
            self.log.info("---------------Iteration %s-----------------" % var)
            process.run("cpupower frequency-set -f %s"
                        % self.get_random_freq())
            freq_set = self.cpu_freq_path("cpuinfo_cur_freq")
            freq_read = process.system_output("ppc64_cpu --frequency -t 5"
                                              "| grep 'avg:' | awk "
                                              "'{print $2}'", shell=True)
            freq_read = float(freq_read) * (10 ** 6)
            diff = float(freq_read) - float(freq_set)
            self.log.info(" Difference is %s" % diff)
            if diff > threshold:
                self.log.info("Frequency set and frequency read differs :"
                              "%s %s " % (freq_set, freq_read))
            else:
                self.log.info("Works as expected for iteration %s " % var)

    def get_random_freq(self):
        """
        Get random frequency from list
        """
        cmd = "scaling_available_frequencies"
        return random.choice(self.cpu_freq_path(cmd).split(' '))

    @staticmethod
    def __get_random_cpu():
        """
        Get random online cpu
        """
        return random.choice(cpu.cpu_online_list())

    def cpu_freq_path(self, file):
        """
        get cpu_freq values
        :param: file: is filename which data needs to be fetched
        :param: cpu_num is value for cpu
        """
        f_name = "/sys/devices/system/cpu/cpu%s/cpufreq/%s" % (self.cpu, file)
        return open(f_name, 'r').readline().strip('\n').strip(' ')


if __name__ == "__main__":
    main()
