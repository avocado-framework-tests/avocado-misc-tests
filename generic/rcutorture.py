#!/usr/bin/env python
#
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
# Copyright: 2016 IBM
# Author:Abdul Haleem <abdhalee@in.ibm.com>
#        Praveen K Pandey <praveen@linux.vnet.ibm.com>
#

import os
import re
import time
import multiprocessing

from avocado import Test
from avocado import main
from avocado.utils import process, cpu
from avocado.utils import linux_modules


class Rcutorture(Test):

    """
    CONFIG_RCU_TORTURE_TEST enables an intense torture test of the RCU
    infratructure. It creates an rcutorture kernel module that can be
    loaded to run a torture test.

    :avocado: tags=kernel,privileged
    """

    def setUp(self):
        """
        Verifies if CONFIG_RCU_TORTURE_TEST is enabled
        """
        self.results = []
        self.log.info("Check if CONFIG_RCU_TORTURE_TEST is enabled\n")
        ret = linux_modules.check_kernel_config('CONFIG_RCU_TORTURE_TEST')
        if ret == linux_modules.ModuleConfig.NOT_SET:
            self.cancel("CONFIG_RCU_TORTURE_TEST is not set in .config !!\n")

        self.log.info("Check rcutorture module is already  loaded\n")
        if linux_modules.module_is_loaded('rcutorture'):
            linux_modules.unload_module('rcutorture')

    def cpus_toggle(self):
        """
        Toggle CPUS online and offline
        """
        totalcpus = multiprocessing.cpu_count()
        full_count = int(totalcpus) - 1
        half_count = int(totalcpus) / 2 - 1
        shalf_count = int(totalcpus) / 2
        fcpu = "0 - "  "%s" % half_count
        scpu = "%s - %s" % (shalf_count, full_count)

        self.log.info("Online all cpus %s", totalcpus)
        for cpus in range(0, full_count):
            cpu.online(cpus)
        time.sleep(10)

        self.log.info("Offline all cpus 0 - %s\n", full_count)
        for cpus in range(0, full_count):
            cpu.offline(cpus)
        time.sleep(10)

        self.log.info("Online all cpus 0 - %s\n", full_count)
        for cpus in range(0, full_count):
            cpu.online(cpus)

        self.log.info(
            "Offline and online first half cpus %s\n", fcpu)
        for cpus in range(0, half_count):
            cpu.offline(cpus)
            time.sleep(10)
            cpu.online(cpus)

        self.log.info("Offline and online second half cpus %s\n", scpu)
        for cpus in range(shalf_count, full_count):
            cpu.offline(cpus)
            time.sleep(10)
            cpu.online(cpus)

    def test(self):
        """
        Runs rcutorture test for specified time.
        """
        seconds = 15
        os.chdir(self.logdir)
        if linux_modules.load_module('rcutorture'):
            self.cpus_toggle()
            time.sleep(seconds)
            self.cpus_toggle()
        linux_modules.unload_module('rcutorture')

        dmesg = process.system_output('dmesg').decode("utf-8")

        res = re.search(r'rcu-torture: Reader', dmesg, re.M | re.I)

        self.results = str(res).splitlines()

        """
        Runs log ananlysis on the dmesg logs
        Checks for know bugs
        """
        pipe1 = [r for r in self.results if "!!! Reader Pipe:" in r]
        if len(pipe1) != 0:
            self.error('\nBUG: grace-period failure !')

        pipe2 = [r for r in self.results if "Reader Pipe" in r]
        for p in pipe2:
            nmiss = p.split(" ")[7]
            if int(nmiss):
                self.error('\nBUG: rcutorture tests failed !')

        batch = [s for s in self.results if "Reader Batch" in s]
        for b in batch:
            nmiss = b.split(" ")[7]
            if int(nmiss):
                self.log.info("\nWarning: near mis failure !!")

    def tearDown(self):
        if linux_modules.module_is_loaded('rcutorture'):
            linux_modules.unload_module('rcutorture')


if __name__ == "__main__":
    main()
