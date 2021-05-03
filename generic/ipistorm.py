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
# Copyright: 2020 IBM
# Author: Harish <harish@linux.vnet.ibm.com>
#


import os
import time
import platform

from avocado import Test
from avocado import skipIf
from avocado.utils import archive, build, cpu, genio, linux_modules, process
from avocado.utils import distro
from avocado.utils.software_manager import SoftwareManager

IS_POWER_NV = 'PowerNV' in genio.read_file('/proc/cpuinfo')


class DBLIPIStrom(Test):
    """
    Storm IPIs to ensure DBL interrputs/XIVE-IPSs are triggered on XIVE

    :avocado: tags=ipi,power,xive
    """

    @skipIf(IS_POWER_NV, "This test is not supported on PowerNV platform")
    def setUp(self):
        """
        Install necessary packages to build the linux module
        """
        if 'ppc' not in distro.detect().arch:
            self.cancel('Test Only supported on Power')

        pkgs = ['gcc', 'make', 'kernel-devel']

        smm = SoftwareManager()
        for package in pkgs:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

        tarball = self.fetch_asset("ipistorm.zip", locations=[
            "https://github.com/antonblanchard/ipistorm"
            "/archive/master.zip"], expire='7d')
        archive.extract(tarball, self.teststmpdir)
        teststmpdir = os.path.join(self.teststmpdir, "ipistorm-master")
        os.chdir(teststmpdir)
        kernel_version = platform.uname()[2]
        if not os.path.exists(os.path.join("/lib/modules", kernel_version)):
            self.cancel(
                "Modules of running kernel missing to build ipistorm module")
        build.make(teststmpdir)
        if not os.path.isfile(os.path.join(teststmpdir, 'ipistorm.ko')):
            self.fail("No ipistorm.ko found, module build failed")
        int_op = genio.read_file("/proc/interrupts")
        if "XIVE" not in int_op:
            self.cancel("Test is supported only with XIVE")

    @staticmethod
    def get_interrupts(string):
        """
        Find the string and return a list of CPU stats for it
        """
        int_op = genio.read_file("/proc/interrupts")
        for line in int_op.splitlines():
            if string in line:
                line = line.split()[1: cpu.online_cpus_count() + 1]
                return line
        return []

    def test(self):
        """
        Check for the IPIs before and after ipistorm module
        """
        pre_dbl_val = self.get_interrupts("DBL")
        pre_ipi_val = self.get_interrupts("IPI")
        if not linux_modules.module_is_loaded("ipistorm"):
            if process.system(
                    "insmod ./ipistorm.ko", ignore_status=True, shell=True,
                    sudo=True):
                self.fail("Failed to insert ipistorm module")
        else:
            self.cancel(
                "Cannot verify the DBL interrupt with module already loaded")
        time.sleep(5)
        process.system("rmmod ipistorm", ignore_status=True, sudo=True)
        post_dbl_val = self.get_interrupts("DBL")
        post_ipi_val = self.get_interrupts("IPI")
        for idx, _ in enumerate(post_dbl_val):
            if (int(post_dbl_val[idx]) <= int(pre_dbl_val[idx])) or\
                    (int(post_ipi_val[idx]) <= int(pre_ipi_val[idx])):
                self.fail("Interrupts does not seemed to be used")
            else:
                self.log.info("Old DBL %s, New DBL: %s",
                              pre_dbl_val[idx], post_dbl_val[idx])
                self.log.info("Old IPI %s, New IPI: %s",
                              pre_ipi_val[idx], post_ipi_val[idx])
