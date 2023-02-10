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
import shutil
import platform

from avocado import Test
from avocado.utils import process, cpu
from avocado.utils import linux_modules
from avocado.utils import distro
from avocado.utils.software_manager.manager import SoftwareManager


class Rcutorture(Test):

    """
    CONFIG_RCU_TORTURE_TEST enables an intense torture test of the RCU
    infratructure. It creates an rcutorture kernel module that can be
    loaded to run a torture test.

    :avocado: tags=kernel,privileged
    """

    def setUp(self):
        smg = SoftwareManager()
        if "SuSE" in distro.detect().name:
            if not smg.check_installed("kernel-source") and not smg.install(
                "kernel-source"
            ):
                self.cancel("Failed to install kernel-source for this test.")
            if not os.path.exists("/usr/src/linux"):
                self.cancel("kernel source missing after install")
            self.buldir = "/usr/src/linux"
            shutil.copy(
                "/boot/config-%s" % platform.uname()[2], "%s/.config" % self.buldir
            )
            os.chdir(self.buldir)
            process.system(
                "sed -i 's/^.*CONFIG_SYSTEM_TRUSTED_KEYS/#&/g'\
                           .config",
                shell=True,
                sudo=True,
            )
            process.system(
                "sed -i 's/^.*CONFIG_SYSTEM_TRUSTED_KEYRING/#&/g' \
                           .config",
                shell=True,
                sudo=True,
            )
            process.system(
                "sed -i 's/^.*CONFIG_MODULE_SIG_KEY/#&/g' .config",
                shell=True,
                sudo=True,
            )
            process.system(
                "sed -i 's/^.*CONFIG_DEBUG_INFO_BTF/#&/g' .config",
                shell=True,
                sudo=True,
            )
            process.system("make")
            process.system("make modules_install")
        """
        Verifies if CONFIG_RCU_TORTURE_TEST is enabled
        """
        self.results = []
        self.log.info("Check if rcutorture can be loaded or not\n")
        if linux_modules.load_module("rcutorture"):
            if linux_modules.module_is_loaded("rcutorture"):
                self.log.info("rcutorture loaded successfully\n")
                linux_modules.unload_module("rcutorture")
        else:
            self.cancel(f"rcutorture module can't be loaded")

    def online_cpu(self, cpus):
        if cpu.is_hotpluggable(cpus):
            if cpu.online(cpus) is False:
                raise TypeError(f"CPU{cpus} status still offline after toggling")

    def offline_cpu(self, cpus):
        if cpu.is_hotpluggable(cpus):
            if cpu.offline(cpus):
                raise TypeError(f"CPU{cpus} status still online after toggling")

    def cpus_toggle(self):
        """
        Toggle CPUS online and offline
        """
        totalcpus = multiprocessing.cpu_count()
        full_count = totalcpus - 1
        half_count = totalcpus // 2 - 1
        shalf_count = totalcpus // 2
        fcpu = "0 - " "%s" % half_count
        scpu = "%s - %s" % (shalf_count, full_count)

        self.log.info("Online all cpus 0 - %s (if they support)\n", totalcpus)
        for cpus in range(0, full_count):
            self.online_cpu(cpus)
        time.sleep(10)

        self.log.info("Offline all cpus 0 - %s(if they support)\n", full_count)
        for cpus in range(0, full_count):
            self.offline_cpu(cpus)
        time.sleep(10)

        self.log.info("Online all cpus 0 - %s(if they support)\n", full_count)
        for cpus in range(0, full_count):
            self.online_cpu(cpus)

        self.log.info("Offline and online first half cpus %s(if they support)\n", fcpu)
        for cpus in range(0, half_count):
            self.offline_cpu(cpus)
            time.sleep(10)
            self.online_cpu(cpus)

        self.log.info("Offline and online second half cpus %s(if they support)\n", scpu)
        for cpus in range(shalf_count, full_count):
            self.offline_cpu(cpus)
            time.sleep(10)
            self.online_cpu(cpus)

    def test(self):
        """
        Runs rcutorture test for specified time.
        """
        seconds = 15
        os.chdir(self.logdir)
        if linux_modules.load_module("rcutorture"):
            self.cpus_toggle()
            time.sleep(seconds)
            self.cpus_toggle()
        linux_modules.unload_module("rcutorture")

        dmesg = process.system_output("dmesg").decode("utf-8")

        res = re.search(r"rcu-torture: Reader", dmesg, re.M | re.I)

        self.results = str(res).splitlines()

        """
        Runs log ananlysis on the dmesg logs
        Checks for know bugs
        """
        pipe1 = [r for r in self.results if "!!! Reader Pipe:" in r]
        if len(pipe1) != 0:
            self.error("\nBUG: grace-period failure !")

        pipe2 = [r for r in self.results if "Reader Pipe" in r]
        for p in pipe2:
            nmiss = p.split(" ")[7]
            if int(nmiss):
                self.error("\nBUG: rcutorture tests failed !")

        batch = [s for s in self.results if "Reader Batch" in s]
        for b in batch:
            nmiss = b.split(" ")[7]
            if int(nmiss):
                self.log.info("\nWarning: near mis failure !!")

    def tearDown(self):
        if linux_modules.module_is_loaded("rcutorture"):
            linux_modules.unload_module("rcutorture")
