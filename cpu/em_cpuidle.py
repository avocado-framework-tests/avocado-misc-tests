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
# Copyright: 2017 IBM
# Author:Shriya Kulkarni <shriyak@linux.vnet.ibm.com>
import os
import random
import subprocess
import re
import platform
from avocado import Test
from avocado import main
from avocado.utils import process, distro, cpu
from avocado.utils.software_manager import SoftwareManager


class cpuidle(Test):
    """
    Test to validate the number of cpu idle states
    """

    def setUp(self):
        """
        Verify it is baremetal
        Install the cpupower tool

        :avocado: tags=cpu,power
        """
        if not os.path.exists('/proc/device-tree/ibm,opal/power-mgt'):
            self.cancel("Supported only on Power Non Virutalized environment")
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

    def cmp(self, first_value, second_value):
        return (first_value > second_value) - (first_value < second_value)

    def test(self):
        """
        Validate the number of cpu idle states against device tree
        """
        for var in range(1, 10):
            cpu_num = random.choice(cpu.cpu_online_list())
            self.log.info("--------CPU: %s--------" % cpu_num)
            states = process.system_output("cpupower -c %s idle-info --silent"
                                           " | grep 'Number of idle states:' |"
                                           "awk '{print $5}'"
                                           % cpu_num, shell=True).decode("utf-8")
            cpu_idle_states = []
            for i in range(1, int(states)):
                val = process.system_output("cat /sys/devices/system/cpu/"
                                            "cpu%s/cpuidle/state%s/"
                                            "name" % (cpu_num, i)).decode("utf-8")
                if 'power8' in cpu.get_cpu_arch():
                    val = self.set_idle_states(val)
                cpu_idle_states.append(val)
            devicetree_list = self.read_from_device_tree()
            res = self.cmp(cpu_idle_states, devicetree_list)
            if res == 0:
                self.log.info("PASS : Validated the idle states")
            else:
                self.log.info(" cpupower tool : %s and device tree"
                              ": %s" % (cpu_idle_states, devicetree_list))
                self.fail("FAIL: Please check the idle states")

    def read_from_device_tree(self):
        """
        Read from device tree
        """
        os.chdir('/proc/device-tree/ibm,opal/power-mgt')
        cmd_args = ['lsprop', 'ibm,cpu-idle-state-names']
        output_string = subprocess.Popen(
            cmd_args, stdout=subprocess.PIPE).communicate()[0].decode("utf-8")
        output = re.findall('\"[a-zA-Z0-9_]+\"', output_string)
        output = [x.strip("\"") for x in output]
        if 'winkle' in output:
            output.pop()
        return output

    def set_idle_states(self, val):
        """
        Small and caps issue while reading idle states from device tree and
        cpupower tool, which results in mismatch.Hence it needs to be
        corrected only for P8.
        """
        if val == 'Nap':
            return 'nap'
        if val == 'FastSleep':
            return 'fastsleep_'


if __name__ == "__main__":
    main()
