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
# Copyright: 2022 IBM
# Author: Akanksha J N <akanksha@linux.ibm.com>

import time
import sys
import os
import shutil
import pexpect
from avocado import Test
from avocado.utils import build, distro, genio, process

from avocado.utils.software_manager.manager import SoftwareManager


class Dawr(Test):
    """
    Reading single Dawr register and multiple Dawr registers
    with gdb interface

    :avocado: tags=trace,ppc64le
    """

    def setUp(self):
        '''
        Install the basic packages to support gdb and perf
        '''
        val = genio.read_file("/proc/cpuinfo")
        power_ver = ['POWER10', 'Power11']
        if not any(x in val for x in power_ver):
            self.cancel("LPAR on Power10 and above is required for this test.")
        # Check for basic utilities
        smm = SoftwareManager()
        self.detected_distro = distro.detect()
        self.distro_name = self.detected_distro.name
        deps = ['gcc', 'make', 'gdb', 'perf']
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        for value in range(1, 4):
            shutil.copyfile(self.get_data('dawr_v%d.c' % value),
                            os.path.join(self.teststmpdir,
                                         'dawr_v%d.c' % value))
        shutil.copyfile(self.get_data('Makefile'),
                        os.path.join(self.teststmpdir, 'Makefile'))
        build.make(self.teststmpdir)
        os.chdir(self.teststmpdir)
        self.output_file = "perf.data"

    def run_cmd(self, bin_var):
        child = pexpect.spawn('gdb ./%s' % bin_var, encoding='utf-8')
        time.sleep(0.3)
        child.logfile = sys.stdout
        child.expect('(gdb)')
        if self.distro_name in ['fedora', 'SuSE']:
            child.sendline('set debuginfod enabled on')
            child.expect_exact([pexpect.TIMEOUT, ''])
        return_value = []
        return child, return_value

    def run_test(self, cmd):
        return process.run(cmd, shell=True)

    def perf_cmd(self, perf_record):
        process.run(perf_record, shell=True, ignore_status=True,
                    verbose=True, ignore_bg_processes=True)
        report = "perf report --input=%s" % self.output_file
        self.run_test(report)
        if not os.stat(self.output_file).st_size:
            self.fail("%s sample not captured" % self.output_file)

    def address_v1(self):
        # Get memory address of single variable
        output = self.run_test('./dawr_v1')
        data = output.stdout.decode("utf-8")
        return data

    def address_v2(self):
        # Get memory address of two variables
        output = self.run_test('./dawr_v2')
        data = output.stdout.decode("utf-8").split(',')
        return data

    def test_read_dawr_v1_gdb(self):
        """
        Setting Read/Write watchpoint on single variable using awatch and
        executing the program
        """
        child, return_value = self.run_cmd('dawr_v1')
        i = 0
        child.sendline('awatch a')
        return_value.append(child.expect_exact(['watchpoint 1: a',
                                                pexpect.TIMEOUT]))
        child.sendline('r')
        return_value.append(child.expect_exact(
            ['Value = 10', pexpect.TIMEOUT]))
        child.sendline('c')
        return_value.append(child.expect_exact(
            ['New value = 20', pexpect.TIMEOUT]))
        for i in return_value:
            if i != 0:
                self.fail('Test case failed for 1 variable')

    def test_read_dawr_v2_gdb(self):
        """
        Setting Read/Write watchpoints on two variables using awatch and
        executing the program
        """
        child, return_value = self.run_cmd('dawr_v2')
        i = 0
        for value in ['a', 'b']:
            i = i+1
            child.sendline('awatch %s' % value)
            return_value.append(child.expect_exact([pexpect.TIMEOUT,
                                                    'watchpoint %s: %s'
                                                    % (i, value)]))
        child.sendline('r')
        values = [pexpect.TIMEOUT, 'Value = 10', 'New value = 20',
                  'Value = 10', 'New value = 20', 'Value = 20', 'Value = 20']
        for match in values:
            return_value.append(child.expect_exact([pexpect.TIMEOUT, match]))
            child.sendline('c')
        return_value.append(child.expect_exact(
            [pexpect.TIMEOUT, 'exited normally']))
        for i in return_value:
            if i == 0:
                self.fail('Test case failed for 2 variables')

    def test_read_dawr_v3_gdb(self):
        """
        Setting Read/Write watchpoints on three variables using awatch and
        executing the program
        """
        child, return_value = self.run_cmd('dawr_v3')
        i = 0
        for value in ['a', 'b', 'c']:
            i = i+1
            child.sendline('awatch %s' % value)
            return_value.append(child.expect_exact([pexpect.TIMEOUT,
                                                    'watchpoint %s: %s'
                                                    % (i, value)]))
        child.sendline('r')
        return_value.append(child.expect_exact([pexpect.TIMEOUT,
                                                'not enough available hardware']))
        for i in return_value:
            if i == 0:
                self.fail('Test case failed for 3 variables')

    def test_read_dawr_v1_perf(self):
        # Read single dawr register with perf interface
        data = self.address_v1()
        perf_record = 'perf record -o %s -e mem:%s ./dawr_v1' % (
            self.output_file, data)
        self.perf_cmd(perf_record)

    def test_read_dawr_v2_perf(self):
        # Read two dawr registers with perf interface
        data = self.address_v2()
        perf_record = 'perf record -o %s -e mem:%s -e mem:%s ./dawr_v2' % (
            self.output_file, data[0], data[1][1:11])
        self.perf_cmd(perf_record)

    def tearDown(self):
        # Delete the temporary file
        if os.path.isfile("perf.data"):
            process.run('rm -f perf.data')
