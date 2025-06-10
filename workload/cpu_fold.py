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
# Copyright: 2023 IBM
# Author: Samir A Mulani <samir@linux.vnet.ibm.com>

from avocado import Test
from avocado.utils import process, distro
from avocado.utils.software_manager.manager import SoftwareManager
import os
import time


def collect_dmesg(object):
    return process.system_output("dmesg").decode()


class Cpuworkload(Test):
    """
    This test is basically run the cpu workload as a daemon process,
    -> Covers all different cpu off on scenarios for single cpu,
    multiple cpu and multiple cycles of cpu toggle.
    """

    def setUp(self):
        """
        Check required packages is installed.
        """
        if 'ppc' not in distro.detect().arch:
            self.cancel("Processor is not powerpc")
        sm = SoftwareManager()
        for pkg in ['util-linux', 'powerpc-utils', 'numactl']:
            if not sm.check_installed(pkg) and not sm.install(pkg):
                self.cancel("%s is required to continue..." % pkg)
        self.runtime = self.params.get('runtime', default='')

    def dmesg_validater(self):
        """
        This function is responsible to validate the dmesg
        for any errors after smt workload run.
        """
        ERROR = []
        pattern = ['WARNING: CPU:', 'Oops', 'Segfault', 'soft lockup',
                   'Unable to handle', 'ard LOCKUP']
        for fail_pattern in pattern:
            for log in collect_dmesg(self).splitlines():
                if fail_pattern in log:
                    ERROR.append(log)
        if ERROR:
            self.fail("Test failed with following errors in dmesg :  %s " %
                      "\n".join(ERROR))
        cpu_fold = self.logdir + "/cpu_folding"
        os.makedirs(cpu_fold, exist_ok=True)
        cmd = "mv /tmp/cpu_folding.log %s " % (cpu_fold)
        process.run(cmd)

    def test_cpu_start(self):
        """
        Start the CPU Workload
        """
        relative_path = 'cpu_fold.py.data/cpu.sh'
        absolute_path = os.path.abspath(relative_path)
        cpu_folding = "bash " + absolute_path + \
            " &> /tmp/cpu_folding.log &"
        process.run(cpu_folding, ignore_status=True, sudo=True, shell=True)
        self.log.info("CPU Workload started--!!")
        if self.runtime != "":
            runtime = self.runtime * 60
            time.sleep(runtime)

    def test_cpu_stop(self):
        """
        Kill the CPU workload
        """
        self.grep_cmd = "grep -i {}".format("cpu.sh")
        self.awk_cmd = "awk '{print $2}'"
        self.process_kill = "ps aux | {} | {} | head -1 | xargs kill".format(
            self.grep_cmd, self.awk_cmd)
        process.run(self.process_kill, ignore_status=True,
                    sudo=True, shell=True)
        self.log.info("CPU Workload killed successfully--!!")
        self.dmesg_validater()
