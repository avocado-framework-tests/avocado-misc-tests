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
# Copyright: 2020 IBM.
# Author: Nageswara R Sastry <rnsastry@linux.vnet.ibm.com>
#         Disha Goel <disgoel@linux.ibm.com>

import os
from avocado import Test
from avocado import skipUnless
from avocado.utils import process, distro, genio, dmesg
from avocado.utils.software_manager.manager import SoftwareManager

IS_POWER_NV = 'PowerNV' in genio.read_file('/proc/cpuinfo').rstrip('\t\r\n\0')


class PerfCoreIMCEvents(Test):

    """
    Checking core, thread, trace IMC events
    :avocado: tags=privileged,perf
    """

    @skipUnless(IS_POWER_NV, "This test is for PowerNV")
    def setUp(self):
        '''
        Install the basic packages to support perf
        '''

        smg = SoftwareManager()
        dist = distro.detect()
        if dist.name in ['Ubuntu', 'debian']:
            linux_tools = "linux-tools-" + os.uname()[2][3]
            pkgs = [linux_tools]
            if dist.name in ['Ubuntu']:
                pkgs.extend(['linux-tools-common'])
        elif dist.name in ['centos', 'fedora', 'rhel', 'SuSE']:
            pkgs = ['perf']
        else:
            self.cancel("perf is not supported on %s" % dist.name)

        for pkg in pkgs:
            if not smg.check_installed(pkg) and not smg.install(pkg):
                self.cancel(
                    "Package %s is missing/could not be installed" % pkg)

        # running some workload in background
        process.run("ppc64_cpu --frequency -t 10 &", shell=True,
                    ignore_status=True, verbose=True, ignore_bg_processes=True)

        # collect all imc events
        self.list_core_imc = []
        self.list_thread_imc = []
        self.list_trace_imc = []
        for line in process.get_command_output_matching('perf list', 'imc'):
            line = "%s" % line.split()[0]
            if 'core_imc' in line:
                self.list_core_imc.append(line)
            elif 'thread_imc' in line:
                self.list_thread_imc.append(line)
            elif 'trace_imc' in line:
                self.list_trace_imc.append(line)

        # Clear the dmesg, by that we can capture delta at the end of the test
        dmesg.clear_dmesg()

    def parse_op(self, cmd):
        # helper function to run events and check for failure
        fail_count = 0
        result = process.run(cmd, shell=True, sudo=True)
        output = result.stdout.decode() + result.stderr.decode()
        if ("not counted" in output) or ("not supported" in output):
            fail_count = fail_count + 1
        if fail_count > 0:
            self.fail("%s : command failed" % cmd)

    def imc_events(self, event):
        # helper function to parse different imc events
        for line in event:
            if line in self.list_core_imc:
                cmd = "perf stat -e %s -I 1000 sleep 5" % line
                self.parse_op(cmd)
            # running thread_imc events with workload
            if line in self.list_thread_imc:
                cmd = "perf stat -e %s -I 1000 ls -R /usr/ > /dev/null" % line
                self.parse_op(cmd)
            # running trace_imc events with record/report and
            # validating perf.data samples
            if line in self.list_trace_imc:
                cmd = "perf record -o perf.data -e %s -C 0 sleep 5" % line
                process.run(cmd, shell=True, sudo=True)
                res = process.run(
                    "perf report --stdio -i perf.data", shell=True, sudo=True)
                if "data has no samples!" in res.stderr.decode():
                    self.fail("trace_imc perf.data sample not captured")

    def test_core_imc(self):
        # test function to run each imc events in the list
        for event in [self.list_core_imc, self.list_thread_imc,
                      self.list_trace_imc]:
            self.imc_events(event)

        # negative testcase running two different imc events parallely
        process.run("perf stat -e core_imc/CPM_CCYC/ -I 1000 &",
                    sudo=True, shell=True, ignore_bg_processes=True)
        if not process.system("perf stat -e thread_imc/CPM_CCYC/ -I 1000 ls",
                              ignore_status=True, sudo=True):
            self.fail("test failed because able to run two different imc "
                      "events parallely")

    def tearDown(self):
        # kill process running in background
        process.system("pkill perf", ignore_status=True)
        process.system('pkill ppc64_cpu', ignore_status=True)
        # remove perf.data file generated from perf record
        if os.path.isfile("perf.data"):
            process.run('rm -f perf.data')
        # Collect the dmesg
        dmesg.collect_dmesg()
