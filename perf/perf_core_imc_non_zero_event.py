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
# Copyright: 2020 IBM.
# Author: Nageswara R Sastry <rnsastry@linux.vnet.ibm.com>

import os
from avocado import Test
from avocado import skipUnless
from avocado.utils import process
from avocado.utils import distro
from avocado.utils import genio
from avocado.utils.software_manager.manager import SoftwareManager

IS_POWER_NV = 'PowerNV' in genio.read_file('/proc/cpuinfo').rstrip('\t\r\n\0')


class PerfCoreIMCNonZeroEvents(Test):

    """
    Checking core IMC events which shouldn't return zero
    :avocado: tags=privileged,perf
    """

    @skipUnless(IS_POWER_NV, "This test is for PowerNV")
    def setUp(self):
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
        process.run("ppc64_cpu --frequency -t 10 &", shell=True,
                    ignore_status=True, verbose=True, ignore_bg_processes=True)

        output = process.run('perf list')
        if 'core_imc' in output.stdout_text:
            self.log.info('core_imc is present')
        else:
            self.cancel("core_imc not found")

    def parse_op(self, cmd):
        fail_count = 0
        result = process.system_output(cmd, ignore_status=True,
                                       verbose=True, shell=True, sudo=True)
        output = result.stdout.decode() + result.stderr.decode()
        for line in output.split('\n'):
            if 'time' not in line:
                if int(line.strip().split()[1].replace(',', '')) == 0:
                    fail_count = fail_count + 1
        if fail_count > 1:
            self.fail("%s : command failed with zero count" % cmd)

    def test_perf_cpm_cyc(self):
        self.parse_op('perf stat -e core_imc/CPM_CCYC/ -C 0 -I 1000 sleep 5')

    def test_perf_cpm_32mhz_cyc(self):
        self.parse_op('perf stat -e core_imc/CPM_32MHZ_CYC/ -C 0 -I 1000 sleep 5')

    def tearDown(self):
        process.system('pkill ppc64_cpu', ignore_status=True)
