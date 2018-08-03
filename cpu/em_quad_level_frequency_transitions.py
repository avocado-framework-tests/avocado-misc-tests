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
# Copyright: 2018 IBM
# Author: Shriya Kulkarni <shriyak@linux.vnet.ibm.com>
import os
import time
import random
import platform
from avocado import Test
from avocado import main
from avocado.utils import process, distro, cpu
from avocado import skipIf
from avocado.utils.software_manager import SoftwareManager

IS_POWER_NV = 'POWER8' in open('/proc/cpuinfo', 'r').read()


class freq_transitions(Test):
    """
    To validate quad level frequency transitions.
    """
    @skipIf(IS_POWER_NV, "This test is not supported on Power 8 platform")
    def setUp(self):
        """
        Verify :
        1. It is Power system and platform is Power NV.
        2. Cpupower tool is installed.
        """
        if 'ppc' not in distro.detect().arch:
            self.cancel("Processor is not ppc64")
        if not os.path.exists('/sys/devices/system/cpu/cpu0/cpufreq'):
            self.cancel('CPUFREQ is supported only on Power NV')
        smm = SoftwareManager()
        detected_distro = distro.detect()
        if 'Ubuntu' in detected_distro.name:
            deps = ['linux-tools-common', 'linux-tools-%s'
                    % platform.uname()[2]]
        elif detected_distro.name == "SuSE":
            deps = ['cpupower']
        else:
            deps = ['kernel-tools']
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        self.cpus = cpu.total_cpus_count()
        self.cpu_num = 0
        self.max_freq = 0

    def test(self):
        """
        1) Change governor to userspace on all CPUs.
        2) For each core in the quad, pick a random frequency
        and set cpu with that frequency.
        3) Validate that the cpuinfo_cur_freq on any core in
        the code is set to max(set of frequencies)
        4) Run the perf command on each cpu to validate frequencies
        independently.
        """
        threshold = 300000
        self.quad_dict = {}
        self.max_freq_dict = {}
        self.quad_to_cpu_mapping()
        output = process.run("cpupower frequency-set -g userspace", shell=True)
        cur_governor = self.cpu_freq_path('scaling_governor')
        if 'userspace' == cur_governor and output.exit_status == 0:
            self.log.info("%s governor set successfully" % cur_governor)
        else:
            self.cancel("Unable to set the userspace governor")
        for chip in self.quad_dict:
            for quad in self.quad_dict[chip]:
                for self.cpu_num in self.quad_dict[chip][quad]:
                    process.run("cpupower -c %s frequency-set -f %s"
                                % (self.cpu_num, self.get_random_freq()))
                    time.sleep(1)
                    freq_set = self.cpu_freq_path('cpuinfo_cur_freq')
                    if self.max_freq < freq_set:
                        self.max_freq = freq_set
                if chip not in self.max_freq_dict.keys():
                    self.max_freq_dict[chip] = {}
                if quad not in self.max_freq_dict[chip].keys():
                    self.max_freq_dict[chip][quad] = self.max_freq
                    self.log.info("Maximum frequency set:%s quad:"
                                  "%s" % (self.max_freq, quad))
                self.max_freq = 0
        for chip in self.quad_dict:
            for quad in self.quad_dict[chip]:
                for cpu in self.quad_dict[chip][quad]:
                    freq_get = self.perf_cmd(cpu)
                    freq_max = self.max_freq_dict[chip][quad]
                    diff = float(freq_max) - float(freq_get)
                    if diff > threshold:
                        self.cancel("Quad level max frequency %s is not set on"
                                    "this cpu %s"
                                    % (self.max_freq_dict[chip][quad], cpu))
            self.log.info("Quad level max frequency %s is set on this quad"
                          "%s" % (self.max_freq_dict[chip][quad], quad))

    def quad_to_cpu_mapping(self):
        """
        Get the total quad and cpus list belonging to each quad.
        """
        self.nums = [x for x in range(0, self.cpus)]
        for cpu in self.nums:
            phy_id = process.system_output('cat /sys/devices/system/'
                                           'cpu/cpu%s/physical_id' % cpu)
            quad_id = int(phy_id) >> 4 & 0x7
            chip_id = int(phy_id) >> 8 & 0x7F
            if chip_id not in self.quad_dict.keys():
                self.quad_dict[chip_id] = {}
            if quad_id not in self.quad_dict[chip_id].keys():
                self.quad_dict[chip_id][quad_id] = []
            self.quad_dict[chip_id][quad_id].append(cpu)

    def cpu_freq_path(self, file):
        """
        get cpu_freq values
        :param: file: is filename for which data needs to be fetched
        """
        f_name = "/sys/devices/system/cpu/cpu%s/cpufreq/%s" \
                 % (self.cpu_num, file)
        return open(f_name, 'r').readline().strip('\n').strip(' ')

    def get_random_freq(self):
        """
        Get random frequency from list
        """
        cmd = "scaling_available_frequencies"
        return random.choice(self.cpu_freq_path(cmd).split(' '))

    def perf_cmd(self, cpu):
        """
        Parse the output for perf cmd
        :param: cpu: provide the output for each cpu
        """
        cmd = "perf stat -e cycles -e task-clock timeout 1 taskset -c \
                %s yes>/dev/null" % cpu
        output = process.run(cmd, shell=True, ignore_status=True)
        self.log.info("output : %s" % output.stderr)
        a = output.stderr
        b = a.splitlines()[3].split('#')[1].strip().split(' ')[0]
        b = float(b) * (10 ** 6)
        return b


if __name__ == "__main__":
    main()
