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
from avocado import skipIf
from avocado.utils import process, distro, cpu
from avocado.utils.software_manager.manager import SoftwareManager

# Check if the platform is PowerNV
IS_POWER_NV = 'PowerNV' in open('/proc/cpuinfo', 'r').read()


class Cpufreq(Test):
    """
    Test to validate the frequency transition on PowerNV.

    :avocado: tags=cpu,power
    """

    # Skip this test if the platform is not PowerNV
    @skipIf(not IS_POWER_NV, "This test is not supported on PowerVM platform")
    def setUp(self):
        smm = SoftwareManager()
        self.detected_distro = distro.detect()
        self.distro_name = self.detected_distro.name
        self.distro_ver = self.detected_distro.version
        self.distro_rel = self.detected_distro.release
        # Get the configured attributes
        self.num_loop = int(self.params.get('test_loop', default=10))
        self.cpufreq_diff_threshold = int(
            self.params.get('cpufreq_diff_threshold', default=10000))
        self.cpu = 0
        if 'Ubuntu' in self.distro_name:
            deps = [
                'linux-tools-common',
                'linux-tools-%s' % platform.uname()[2]
            ]
        else:
            deps = ['kernel-tools']
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
                self.log.info('Checking if %s is installed' % package)

    # Pick a random CPU from the list of online CPUs
    def get_random_cpu(self):
        self.log.info('Getting a random CPU')
        return random.choice(cpu.cpu_online_list())

    # Get the CPU frequency attribute
    def get_cpufreq_attribute(self, file):
        self.log.info('Getting CPU frequency path for file %s' % file)
        f_name = "/sys/devices/system/cpu/cpu%s/cpufreq/%s" % (self.cpu, file)
        return open(f_name, 'r').readline().strip('\n').strip(' ')

    # Get the ppc64 CPU frequency
    def get_ppc64_cpu_frequency(self):
        self.log.info('Getting ppc64 CPU frequency')
        output = process.system_output("ppc64_cpu --frequency -t 5",
                                       shell=True).decode()
        freq_read = 0
        for line in output.splitlines():
            if 'avg' in line:
                freq_read = line.split(":")[1].strip("GHz").strip()
                break
        return float(freq_read) * (10**6)

    # Get a random frequency
    def get_random_freq(self):
        self.log.info('Getting a random frequency')
        cmd = "scaling_available_frequencies"
        return random.choice(self.get_cpufreq_attribute(cmd).split(' '))

    # Compare two frequencies and check if they are within the threshold
    def compare_frequencies(self, loop, freq1, freq2):
        diff = float(freq1) - float(freq2)
        if abs(diff) > self.cpufreq_diff_threshold:
            self.fail("Frequency set and frequency read differs : %s %s" %
                      (freq2, freq1))
        else:
            self.log.info(
                "Frequency set and frequency read are within the threshold : %s %s"
                % (freq1, freq2))
            self.log.info("Difference between the two frequencies is %s" %
                          diff)
            self.log.info("Test %s passed" % loop)

    # Set the CPU frequency
    def set_cpu_frequency(self, rand_freq):
        self.log.info("cpupower frequency-set -f %s" % rand_freq)
        process.run("cpupower frequency-set -f %s" % rand_freq)

    # Perform the test
    def test(self):
        """
        This method performs a series of tests on the CPU frequency settings.

        It sets the CPU governor to 'userspace' and verifies if the governor is set
        successfully. Then, it performs a number of iterations, each time setting a
        random CPU frequency and comparing it with the actual frequency.
        """
        self.log.info('Starting the test')
        output = process.run("cpupower frequency-set -g userspace", shell=True)
        cur_governor = self.get_cpufreq_attribute('scaling_governor')

        if 'userspace' == cur_governor and output.exit_status == 0:
            self.log.info("%s governor set successfully" % cur_governor)
        else:
            self.cancel("Unable to set the userspace governor")

        for loop in range(self.num_loop):
            self.cpu = self.get_random_cpu()
            self.log.info("---------------CPU %s-----------------" % self.cpu)
            self.log.info("---------------Iteration %s-----------------" %
                          loop)
            rand_freq = self.get_random_freq()
            self.set_cpu_frequency(rand_freq)
            freq_set = self.get_cpufreq_attribute("cpuinfo_cur_freq")
            self.compare_frequencies(loop, rand_freq, freq_set)

            freq_read = self.get_ppc64_cpu_frequency()
            self.compare_frequencies(loop, freq_set, freq_read)
