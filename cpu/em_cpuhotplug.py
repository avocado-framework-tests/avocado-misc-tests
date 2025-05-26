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
# Author: Gautham R. Shenoy <ego@linux.vnet.ibm.com>
# Author: Shriya Kulkarni <shriyak@linux.vnet.ibm.com>

import random

from avocado import Test
from avocado.utils import process, cpu, genio, distro, dmesg


class Cpuhotplug_Test(Test):
    """
    To test hotplug within core in random manner.

    :avocado: tags=cpu,power
    """

    def setUp(self):
        """
        Get the number of cores and threads per core
        Set the SMT value to 4/8
        """
        if distro.detect().arch not in ['ppc64', 'ppc64le']:
            self.cancel("Only supported in powerpc system")

        self.loop = int(self.params.get('test_loop', default=100))
        self.nfail = 0
        lscpu_dict = cpu.lscpu()
        self.CORES = lscpu_dict['virtual_cores']
        self.SOCKETS = lscpu_dict['sockets']
        self.THREADS = lscpu_dict['threads_per_core']
        self.T_CORES = int(self.CORES) * int(self.SOCKETS)
        self.log.info(" Cores = %s and threads = %s "
                      % (self.T_CORES, self.THREADS))

        genio.write_one_line('/proc/sys/kernel/printk', "8")
        # Set SMT to max SMT value (restricted at boot time) and get its value
        process.system("ppc64_cpu --smt=%s" % "on", shell=True)
        ppc_smt = "ppc64_cpu --smt"
        self.max_smt_s = process.system_output(ppc_smt, shell=True).decode()
        self.max_smt = int(self.max_smt_s[4:])
        self.path = "/sys/devices/system/cpu"

    def verify_dmesg(self):
        whiteboard = process.system_output("dmesg").decode()

        pattern = ['WARNING: CPU:', 'Oops', 'Segfault', 'soft lockup',
                   'Unable to handle', 'ard LOCKUP']

        for fail_pattern in pattern:
            if fail_pattern in whiteboard:
                self.fail("Test Failed : %s in dmesg" % fail_pattern)

    def test(self):
        """
        This script picks a random core and then offlines all its threads
        in a random order and onlines all its threads in a random order.
        """
        dmesg.clear_dmesg()
        for val in range(1, self.loop):
            self.log.info("================= TEST %s ==================" % val)
            core_list = self.random_gen_cores()
            for core in core_list:
                cpu_list = self.random_gen_cpu(core)
                self.log.info("Offlining the threads : %s for "
                              "the core : %s" % (cpu_list, core))
                for cpu_num in cpu_list:
                    # If only one core then don't disable cpu 0 - busy
                    if core != 0 or (core == 0 and cpu_num != 0):
                        self.cpu_on_off("offline", cpu_num)
                cpu_list = self.random_gen_cpu(core)
                if core == 0:
                    cpu_list.remove(0)
                self.log.info("Onlining the threads : %s for "
                              "the core : %s" % (cpu_list, core))
                for cpu_num in cpu_list:
                    self.cpu_on_off("online", cpu_num)
        if self.nfail > 0:
            self.fail(" Unable to online/offline few cpus")

        self.verify_dmesg()

    def random_gen_cores(self):
        """
        Generate random core list
        """
        nums = [val for val in range(0, self.T_CORES)]
        random.shuffle(nums)
        self.log.info(" Core list is %s" % nums)
        return nums

    def random_gen_cpu(self, core):
        """
        Generate random cpu number for the given core
        """
        nums = [val for val in range(self.max_smt * core,
                                     ((self.max_smt * core) + self.max_smt))]
        random.shuffle(nums)
        return nums

    def cpu_on_off(self, cpu_mode, cpu_num):
        """
        online and offline the particular CPU.
        cpu_mode:
        1. online mode.
        2. offline mode.
        cpu_num: which cpu need to online or offline.
        """
        cpu_call = getattr(cpu, cpu_mode)
        return_status = cpu_call(cpu_num)
        if (cpu_mode == "online" and return_status):
            self.log.info("{} the cpu : {}".format(cpu_mode, cpu_num))
        elif (cpu_mode == "offline" and not return_status):
            self.log.info("{} the cpu : {}".format(cpu_mode, cpu_num))
        else:
            self.nfail += 1
            self.log.info("Failed to {} the cpu: {}".format(cpu_mode, cpu_num))
