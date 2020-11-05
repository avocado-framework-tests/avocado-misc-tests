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
# Copyright: 2020 IBM
# Author: Pavithra Prakash <pavrampu@linux.vnet.ibm.com>

import os
import time

from avocado import Test
from avocado import skipIf
from avocado.utils import archive
from avocado.utils import build
from avocado.utils import process
from avocado.utils.software_manager import SoftwareManager

class CpupowerMonitor(Test):

    """
    Test to validate idle states using cpupowe monitor tool.
    """

    def setUp(self):
        sm = SoftwareManager()
        for package in ['gcc', 'make']:
            if not sm.check_installed(package) and not sm.install(package):
                self.cancel("%s is needed for the test to be run" % package)
        output = self.run_cmd_out("cpupower idle-info --silent")
        for line in output.splitlines():
            if 'Available idle states: ' in line:
                self.states_list = line.split()
                break
        del self.states_list[0:3]
        self.log.info("Idle states on the system are: ", self.states_list)
        self.run_cmd_out("cpupower monitor")

    def run_cmd_out(self, cmd):
        return process.system_output(cmd, shell=True, ignore_status=True,
                                     sudo=True).decode("utf-8")

    def check_zero_nonzero(self, cmd, stop_state_index):
        output = self.run_cmd_out(cmd)
        values_list = []
        if 'WARNING' in output:
            output = output.split("\n",1)[1]
        for line in output.splitlines()[2:]:
            stop_state_values = line.split('|')
            values_list.append(stop_state_values[stop_state_index].strip())
        for value in values_list:
            if float(value) != 0.00:
                return 1
        return 0

    def test_workload(self):
        tarball = self.fetch_asset('http://sourceforge.net/projects/ebizzy/files/ebizzy/' \
                                   '0.3/ebizzy-0.3.tar.gz')
        archive.extract(tarball, self.workdir)
        self.sourcedir = os.path.join(self.workdir, 'ebizzy-0.3')
        os.chdir(self.sourcedir)
        process.run('./configure', shell=True)
        build.make(self.sourcedir)
        self.run_cmd_out("cpupower monitor")
        self.log.info("============ Starting ebizzy tests ==============")
        obj = process.SubProcess('./ebizzy &', verbose=False,
                                         shell=True)
        obj.start()
        time.sleep(2)
        for i in range(len(self.states_list)):
            zero_nonzero = self.check_zero_nonzero("cpupower monitor", i + 1)
            if zero_nonzero:
                self.fail("cpus entered idle states during ebizzy workload")
            self.log.info("no cpus entered idle states while running ebizzy")
        time.sleep(10)
        zero_nonzero = 0
        for i in range(len(self.states_list)):
            zero_nonzero = zero_nonzero + self.check_zero_nonzero("cpupower monitor", i + 1)
        if not zero_nonzero:
            self.fail("cpus have not entered idle states after killing ebizzy workload")
        self.log.info("cpus have entered idle states after killing work load")

    def test_disable_idlestate(self):
        for i in range(len(self.states_list)):
            process.run('cpupower -c all idle-set -d %s' % i, shell=True)
            time.sleep(5)
            zero_nonzero = self.check_zero_nonzero("cpupower monitor", i + 1)
            if zero_nonzero:
                self.fail("cpus have entered the disabled idle states.")
            self.log.info("cpus have not entered disabled idle states")
            process.run('cpupower -c all idle-set -E', shell=True)

    @skipIf("ppc" not in os.uname()[4], "Skip, SMT specific tests")
    def test_idlestate_smt(self):
        process.run('ppc64_cpu --smt=off', shell=True)
        self.test_workload()
        self.test_disable_idlestate()
        process.run('ppc64_cpu --smt=2', shell=True)
        self.test_workload()
        self.test_disable_idlestate()
        process.run('ppc64_cpu --smt=4', shell=True)
        self.test_workload()
        self.test_disable_idlestate()
        process.run('ppc64_cpu --smt=on', shell=True)

    def test_idlestate_single_core(self):
        process.run('ppc64_cpu --cores-on=1', shell=True)
        self.test_workload()
        self.test_disable_idlestate()
