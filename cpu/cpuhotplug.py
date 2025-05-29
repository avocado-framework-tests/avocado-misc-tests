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
# Author: Abdul Haleem <abdhalee@linux.vnet.ibm.com>

"""
Stress test for CPU
"""

import multiprocessing
from random import randint
from avocado import Test
from avocado.utils import process, cpu, distro, dmesg
from avocado.utils.software_manager.manager import SoftwareManager


pids = []
totalcpus = int(multiprocessing.cpu_count()) - 1
errorlog = ['WARNING: CPU:', 'Oops',
            'Segfault', 'soft lockup', 'ard LOCKUP',
            'Unable to handle paging request',
            'rcu_sched detected stalls',
            'NMI backtrace for cpu',
            'Call Trace:']


def collect_dmesg(object):
    object.whiteboard = process.system_output("dmesg").decode('utf-8')


class cpuHotplug(Test):

    """
    Test to stress the CPU's and its functionality.
    Covers all different cpu off on scenarios for single cpu, multiple cpu and
    multiple cycles of cpu toggle

    1. serial off all, serial on all cpus
    2. off/on single cpu 100 times all cpus
    3. off/on one cpu at a time all cpus
    4. toggle first off and second half cpus on
    5. Affine task to single cpu and do off on check for the process (init)
    6. affine to shared multiple cpus and off on (sleep)
    7. Do multiple cpu off on at once ppc64_cpu --smt
    8. LPAR/GUEST : trigger DLPAR CPU using drmgr command

    :avocado: tags=cpu,power,privileged
    """

    def setUp(self):
        """
        Check required packages is installed, and get current SMT value.
        """
        if 'ppc' not in distro.detect().arch:
            self.cancel("Processor is not powerpc")
        sm = SoftwareManager()
        self.curr_smt = process.system_output(
            "ppc64_cpu --smt | awk -F'=' '{print $NF}' | awk '{print $NF}'",
            shell=True).decode("utf-8")
        for pkg in ['util-linux', 'powerpc-utils', 'numactl']:
            if not sm.check_installed(pkg) and not sm.install(pkg):
                self.cancel("%s is required to continue..." % pkg)
        self.iteration = int(self.params.get('iteration', default='10'))
        self.tests = self.params.get('test', default='all')

    @staticmethod
    def __error_check():
        ERROR = []
        logs = process.system_output("dmesg -Txl 1,2,3,4"
                                     "").decode("utf-8").splitlines()
        for error in errorlog:
            for log in logs:
                if error in log:
                    ERROR.append(log)
        return "\n".join(ERROR)

    @staticmethod
    def __isSMT():
        if 'is not SMT capable' in process.system_output("ppc64_cpu --smt"
                                                         "").decode("utf-8"):
            return False
        return True

    @staticmethod
    def __online_cpus(cores):
        for cpus in range(cores):
            cpu.online(cpus)

    @staticmethod
    def __offline_cpus(cores):
        for cpus in range(cores):
            cpu.offline(cpus)

    @staticmethod
    def __cpu_toggle(core):
        if cpu._get_cpu_status(core):
            cpu.offline(core)
        else:
            cpu.online(core)

    @staticmethod
    def __kill_process(pids):
        for pid in pids:
            process.run("kill -9 %s" % pid, ignore_status=True)

    def test(self):
        """
        calls each of the test in a loop for the given values
        """
        self.__online_cpus(totalcpus)
        if 'all' in self.tests:
            tests = ['cpu_serial_off_on',
                     'single_cpu_toggle',
                     'cpu_toggle_one_by_one',
                     'multiple_cpus_toggle',
                     'pinned_cpu_stress',
                     'dlpar_cpu_hotplug']
        else:
            tests = self.tests.split()

        for method in tests:
            self.log.info("\nTEST: %s\n", method)
            dmesg.clear_dmesg()
            run_test = 'self.%s()' % method
            eval(run_test)
            msg = self.__error_check()
            if msg:
                collect_dmesg()
                self.log.info('Test: %s. ERROR Message: %s', run_test, msg)
            self.log.info("\nEND: %s\n", method)

    def cpu_serial_off_on(self):
        """
        Offline all the cpus serially and online again
        offline 0 -> 99
        online 99 -> 0
        offline 99 -> 0
        online 0 -> 99
        """
        for _ in range(self.iteration):
            self.log.info("OFF-ON Serial Test %s", totalcpus)
            if totalcpus != 0:
                for cpus in range(1, totalcpus):
                    self.log.info("Offlining cpu%s", cpus)
                    cpu.offline(cpus)
            self.log.info("Online CPU's in reverse order %s", totalcpus)
            for cpus in range(totalcpus, -1, -1):
                self.log.info("Onlining cpu%s", cpus)
                cpu.online(cpus)
            self.log.info("Offline CPU's in reverse order %s", totalcpus)
            if totalcpus != 0:
                for cpus in range(totalcpus, -1, -2):
                    self.log.info("Offlining cpu%s", cpus)
                    cpu.offline(cpus)
            self.log.info("Online CPU's in serial")
            for cpus in range(0, totalcpus):
                self.log.info("Onlining cpu%s", cpus)
                cpu.online(cpus)

    def single_cpu_toggle(self):
        """
        Offline-online single cpu for given iteration
        and loop over all cpus.
        @BUG: https://lkml.org/lkml/2017/6/12/212
        """
        for cpus in range(1, totalcpus):
            for _ in range(self.iteration):
                if totalcpus != 0:
                    self.log.info("Offlining cpu%s", cpus)
                    cpu.offline(cpus)
                self.log.info("Onlining cpu%s", cpus)
                cpu.online(cpus)

    def cpu_toggle_one_by_one(self):
        """
        Wait for the given timeout between Off/On single cpu.
        loop over all cpus for given iteration.
        """
        for _ in range(self.iteration):
            for cpus in range(totalcpus):
                if totalcpus != 0:
                    self.log.info("Offlining cpu%s", cpus)
                    cpu.offline(cpus)
                self.log.info("Onlining cpu%s", cpus)
                cpu.online(cpus)

    def multiple_cpus_toggle(self):
        """
        offline/online multiple CPUS at once
        enable different smt options to offline multiple cpus
        @BUG : https://lkml.org/lkml/2017/7/3/21
        """
        if self.__isSMT():
            for _ in range(self.iteration):
                self.log.info("SMT toggle")
                process.run("ppc64_cpu --smt=off && ppc64_cpu --smt=on",
                            shell=True)
        else:
            self.log.info('Machine is not SMT capable')

    def pinned_cpu_stress(self):
        """
        Set process affinity and do cpu off on
        @BUG : https://lkml.org/lkml/2017/5/30/122
        """
        nodes = []
        self.log.info("\nCreate %s pids and set proc affinity", totalcpus)
        for proc in range(0, totalcpus):
            pid = process.SubProcess(
                "while :; do :; done", shell=True).start()
            pids.append(pid)
            process.run("taskset -pc %s %s" %
                        (proc, pid), ignore_status=True, shell=True)

        self.log.info("\noffline cpus and see the affinity change")
        count = 0
        for pid in pids:
            cpu.offline(count)
            process.run("taskset -pc %s" % pid, ignore_status=True, shell=True)
            count = count + 1

        self.__online_cpus(totalcpus)

        self.log.info("\nShift affinity for the same process and toggle")
        for proc in range(totalcpus):
            process.run("taskset -pc $((%s<<1)) $$" %
                        proc, ignore_status=True, shell=True)
            cpu.offline(proc)

        self.__online_cpus(totalcpus)

        self.log.info("\nSet all process affine to single NUMA node")
        nodes = process.system_output(
            "numactl --hardware | grep cpus:", shell=True)
        nodes = nodes.decode().split('\n')
        for node in nodes:
            cores = node.split(': ')[-1].replace(" ", ",")
            if cores:
                for pid in pids:
                    process.run("taskset -pc %s %s" %
                                (cores, pid), ignore_status=True, shell=True)

        self.log.info(
            "\ntoggle random cpu, while shifting affinity of same pid")
        for _ in range(self.iteration):
            core = randint(0, totalcpus)
            process.run("taskset -pc $((%s<<1)) $$" %
                        core, ignore_status=True, shell=True)
            self.__cpu_toggle(core)

        self.__kill_process(pids)

    def dlpar_cpu_hotplug(self):
        """
        PowerVM and Guest only: Dynamic Resource Manager
        use drmgr command to hotplug and hotunplug cpus
        """
        if 'PowerNV' not in open('/proc/cpuinfo', 'r').read():
            if "cpu_dlpar=yes" in process.system_output("drmgr -C",
                                                        ignore_status=True,
                                                        shell=True).decode("utf-8"):
                for _ in range(self.iteration):
                    self.log.info("DLPAR remove cpu operation")
                    init_count = int(multiprocessing.cpu_count())
                    process.run(
                        "drmgr -c cpu -d 5 -w 30 -r -q 1", shell=True,
                        ignore_status=True, sudo=True)
                    if int(multiprocessing.cpu_count()) >= init_count:
                        self.log.info("no more hotunpluggable cpus")
                    self.log.info("DLPAR add cpu operation")
                    process.run(
                        "drmgr -c cpu -d 5 -w 30 -a -q 1", shell=True,
                        ignore_status=True, sudo=True)
                    if init_count != int(multiprocessing.cpu_count()):
                        self.log.info("no more hotpluggable cpus")
            else:
                self.log.info('UNSUPPORTED: dlpar not configured..')
        else:
            self.log.info("UNSUPPORTED: Test not supported on bare-metal")

    def tearDown(self):
        """
        Sets back SMT to original value as was before the test.
        Sets back cpu states to online
        """
        if hasattr(self, 'curr_smt'):
            process.system_output(
                "ppc64_cpu --smt=off && ppc64_cpu --smt=on && ppc64_cpu --smt=%s"
                % self.curr_smt, shell=True)
        self.__online_cpus(totalcpus)
