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
from avocado.utils import build, distro
from avocado.utils import process, cpu
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils import dmesg


class CpupowerMonitor(Test):
    """
    Test to validate idle states using cpupower monitor tool.
    """

    def setUp(self):
        sm = SoftwareManager()
        distro_name = distro.detect().name
        self.runtime = self.params.get("runtime", default=0)
        deps = ['gcc', 'make']
        if distro_name in ['rhel', 'fedora', 'centos']:
            deps.extend(['kernel-tools'])
        elif 'SuSE' in distro_name:
            deps.extend(['cpupower'])

        for package in deps:
            if not sm.check_installed(package) and not sm.install(package):
                self.cancel("%s is needed for the test to be run" % package)
        output = self.run_cmd_out("cpupower idle-info --silent")
        for line in output.splitlines():
            if 'Available idle states: ' in line:
                self.states_list = (line.split('Available idle states: ')[-1])\
                    .split()
                break
        self.log.info("Idle states on the system are: %s" % self.states_list)

        for line in output.splitlines():
            if 'Number of idle states: ' in line:
                self.states_tot = int(line.split('Number of idle states: ')[1])
                break
        self.log.info("Total Idle states: %d" % self.states_tot)
        self.run_cmd_out("cpupower monitor")

    def run_cmd_out(self, cmd):
        return process.system_output(cmd, shell=True, ignore_status=True,
                                     sudo=True).decode("utf-8")

    def check_zero_nonzero(self, stop_state_index):
        output = self.run_cmd_out("cpupower monitor")
        if "CORE" in output:
            stop_state_index = stop_state_index + 2
        values_list = []
        split_index = 2
        if 'WARNING' in output:
            split_index = 3
        for line in output.splitlines()[split_index:]:
            stop_state_values = line.split('|')
            values_list.append(stop_state_values[stop_state_index].strip())
        for value in values_list:
            if float(value) != 0.00:
                return 1
        return 0

    def test_workload(self):
        """
        This test covers:
        1. Collect cpupower monitor output.
        2. Run ebizzy workload.
        3. Check if cpus have not entered idle states while running ebizzy.
        4. Wait till ebizzy stops.
        5. Check if cpus enters idle states.
        """
        tarball = self.fetch_asset('http://sourceforge.net/projects/ebizzy/'
                                   'files/ebizzy/0.3/ebizzy-0.3.tar.gz')
        archive.extract(tarball, self.workdir)
        self.sourcedir = os.path.join(self.workdir, 'ebizzy-0.3')
        os.chdir(self.sourcedir)
        process.run('./configure', shell=True)
        build.make(self.sourcedir)
        self.run_cmd_out("cpupower monitor")
        self.log.info("============ Starting ebizzy tests ==============")
        obj = process.SubProcess('./ebizzy -t 1000 -S 100 &', verbose=False,
                                 shell=True)
        obj.start()
        time.sleep(2)
        for i in range(self.states_tot - 1):
            zero_nonzero = self.check_zero_nonzero(i + 1)
            if zero_nonzero:
                self.fail("cpus entered idle states during ebizzy workload")
            self.log.info("no cpus entered idle states while running ebizzy")
        time.sleep(100)
        zero_nonzero = 0
        for i in range(self.states_tot - 1):
            zero_nonzero = zero_nonzero + self.check_zero_nonzero(i + 1)
        if not zero_nonzero:
            self.log.info("cpus have not entered idle states after killing"
                          " ebizzy workload")
        self.log.info("cpus have entered idle states after killing work load")

    def read_line_with_matching_pattern(self, filename, pattern):
        matching_pattern = []
        with open(filename, 'r') as file_obj:
            for line in file_obj.readlines():
                if pattern in line:
                    matching_pattern.append(line.rstrip("\n"))
        return matching_pattern

    def dmesg_validation(self):
        errors_in_dmesg = []
        pattern = ['WARNING: CPU:', 'Oops', 'Segfault', 'soft lockup',
                   'Unable to handle', 'ard LOCKUP']

        filename = dmesg.collect_dmesg()

        for failed_pattern in pattern:
            contents = self.read_line_with_matching_pattern(
                filename, failed_pattern)
            if contents:
                loop_count = 0
                while loop_count < len(contents):
                    errors_in_dmesg.append(contents[loop_count])
                    loop_count = loop_count + 1

        if errors_in_dmesg:
            self.fail("Failed : Errors in dmesg : %s" %
                      "\n".join(errors_in_dmesg))

    def test_idlestate_mode(self):
        """
        1. Collect list of supported idle states.
        2. Disable first idle statei, check cpus have not entered this state.
        3. Enable all idle states.
        4. Disable second idle state, check cpus have not entered this state.
        5. Repeat test for all states.
        """
        dmesg.clear_dmesg()
        if self.runtime != 0:
            start_time = time.time()
            dtime_check = self.runtime / 4
            while time.time() - start_time < self.runtime:
                for i in range(self.states_tot - 1):
                    process.run('cpupower -c all idle-set -d %s' %
                                i, shell=True)
                    time.sleep(5)
                    zero_nonzero = self.check_zero_nonzero(i + 1)
                    if zero_nonzero:
                        self.fail(
                            "cpus have entered the disabled idle states.")
                    self.log.info("cpus have not entered disabled idle states")
                    process.run('cpupower -c all idle-set -E', shell=True)
                if ((time.time() - start_time) >= dtime_check):
                    dtime_check += dtime_check
                    # Checking dmesg for errors every 1/4 of the time.
                    self.dmesg_validation()
        else:
            for i in range(self.states_tot - 1):
                process.run('cpupower -c all idle-set -d %s' % i, shell=True)
                time.sleep(5)
                zero_nonzero = self.check_zero_nonzero(i + 1)
                if zero_nonzero:
                    self.fail("cpus have entered the disabled idle states.")
                self.log.info("cpus have not entered disabled idle states")
                process.run('cpupower -c all idle-set -E', shell=True)

    @skipIf("powerpc" not in cpu.get_arch(), "Skip, SMT specific tests")
    def test_idlestate_smt(self):
        """
        1. Set smt mode to off.
        2. Run test_workload.
        3. Run test_idlestate_mode.
        4. Repeat test for smt=2. 4.
        """

        for i in ['off', '2', '4', 'on']:
            process.run('ppc64_cpu --smt=%s' % i, shell=True)
            self.test_workload()
            self.test_idlestate_mode()
        process.run('ppc64_cpu --smt=on', shell=True)

    def test_idlestate_single_core(self):
        """
        1. Set single core online.
        2. Run test_workload.
        3. Run test_idlestate_mode.
        4. Repeat test with smt=off, single core
        """

        process.run('ppc64_cpu --cores-on=1', shell=True)
        self.test_workload()
        self.test_idlestate_mode()
        process.run('ppc64_cpu --cores-on=all', shell=True)
        process.run('ppc64_cpu --smt=on', shell=True)

    def test_idle_info(self):
        """
        This test verifies cpupower idle-info with different smt states.
        Prints the duration for which CPU is in snooze and CEDE state.
        """

        process.run('cpupower -c all idle-info', shell=True)
        for i in [1, 2, 4]:
            process.run('ppc64_cpu --smt=%s' % i, shell=True)
            process.run('ppc64_cpu --smt', shell=True)
            output = process.system_output(
                'cpupower -c %s idle-info | grep offline' % i, shell=True).split()
            if "offline" not in str(output[1]):
                self.fail("cpupower tool verification with smt=%s failed" % i)
        process.run('ppc64_cpu --smt=on', shell=True)
        process.run('ppc64_cpu --cores-on=1', shell=True)
        process.run('cpupower -c all idle-info', shell=True)
        process.run('ppc64_cpu --cores-on=all', shell=True)
        process.run('cpupower -c all idle-info', shell=True)
        self.nr_cpus = process.system_output(
            "lscpu | grep ^'CPU(s):'", shell=True).split()
        for i in range(int(self.nr_cpus[1])):
            duration_init = process.system_output(
                'cpupower -c %s idle-info | grep Duration' % i, shell=True).split()
            time.sleep(5)
            duration_final = process.system_output(
                'cpupower -c %s idle-info | grep Duration' % i,
                shell=True).split()
            duration_snooze = int(duration_final[1]) - int(duration_init[1])
            self.log.info("CPU%s has entered snooze state for %s microseconds in 2 seconds" % (
                i, duration_snooze))
            duration_CEDE = int(duration_final[3]) - int(duration_init[3])
            self.log.info("CPU%s has entered CEDE state for %s microseconds in 2 seconds" % (
                i, duration_CEDE))
            if (duration_snooze == 0) and (duration_CEDE == 0):
                self.fail(
                    "CPU%s has not entered snooze or CEDE state even in idle state" % i)
