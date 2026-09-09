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
    with gdb interface. Includes watchpoint tests for different
    data types: local variable, pointer, struct member, array element.

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
            if not smm.check_installed(package):
                if not smm.install(package):
                    self.cancel('%s is needed for the test to be run' % package)
        for value in range(1, 4):
            shutil.copyfile(self.get_data('dawr_v%d.c' % value),
                            os.path.join(self.teststmpdir,
                                         'dawr_v%d.c' % value))
        for fname in ['boundary_check.c', 'dawr_local.c', 'dawr_pointer.c',
                      'dawr_struct.c', 'dawr_array.c', 'Makefile']:
            shutil.copyfile(self.get_data(fname),
                            os.path.join(self.teststmpdir, fname))
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

    def get_address(self, binary):
        output = self.run_test('./%s' % binary)
        data = [addr.strip() for addr in output.stdout.decode("utf-8").split(',')]
        return data

    def address_v1(self):
        # Get memory address of single variable
        return self.get_address('dawr_v1')[0]

    def address_v2(self):
        # Get memory address of two variables
        return self.get_address('dawr_v2')

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
        return_value.append(
            child.expect_exact([pexpect.TIMEOUT,
                               'not enough available hardware']))
        for i in return_value:
            if i == 0:
                self.fail('Test case failed for 3 variables')

    def test_read_dawr_v1_perf(self):
        # Read single dawr register with perf interface
        data = self.get_address('dawr_v1')
        perf_record = 'perf record -o %s -e mem:%s ./dawr_v1' % (
            self.output_file, data[0])
        self.perf_cmd(perf_record)

    def test_read_dawr_v2_perf(self):
        # Read two dawr registers with perf interface
        data = self.get_address('dawr_v2')
        perf_record = 'perf record -o %s -e mem:%s -e mem:%s ./dawr_v2' % (
            self.output_file, data[0], data[1])
        self.perf_cmd(perf_record)

    def test_read_dawr_local_perf(self):
        # Read dawr register with perf interface for local variable
        data = self.get_address('dawr_local')
        perf_record = 'perf record -o %s -e mem:%s ./dawr_local' % (
            self.output_file, data[0])
        self.perf_cmd(perf_record)

    def test_read_dawr_pointer_perf(self):
        # Read dawr register with perf interface for pointer variable
        data = self.get_address('dawr_pointer')
        perf_record = 'perf record -o %s -e mem:%s ./dawr_pointer' % (
            self.output_file, data[0])
        self.perf_cmd(perf_record)

    def test_read_dawr_struct_perf(self):
        # Read dawr register with perf interface for struct member
        data = self.get_address('dawr_struct')
        perf_record = 'perf record -o %s -e mem:%s ./dawr_struct' % (
            self.output_file, data[0])
        self.perf_cmd(perf_record)

    def test_read_dawr_array_perf(self):
        # Read dawr register with perf interface for array element
        data = self.get_address('dawr_array')
        perf_record = 'perf record -o %s -e mem:%s ./dawr_array' % (
            self.output_file, data[0])
        self.perf_cmd(perf_record)

    def test_dawr_local_gdb(self):
        """
        Setting Read/Write watchpoint on a local (stack) variable using
        awatch and verifying the watchpoint triggers on write.
        """
        child, return_value = self.run_cmd('dawr_local')
        child.sendline('break main')
        child.expect('(gdb)')
        child.sendline('r')
        child.expect('(gdb)')
        child.sendline('awatch local')
        return_value.append(child.expect_exact(['watchpoint', pexpect.TIMEOUT]))
        child.sendline('c')
        return_value.append(child.expect_exact(
            ['New value', pexpect.TIMEOUT]))
        for i in return_value:
            if i != 0:
                self.fail('DAWR watchpoint test failed for local variable')

    def test_dawr_pointer_gdb(self):
        """
        Setting Read/Write watchpoint on a pointer-dereferenced variable
        using awatch and verifying the watchpoint triggers on write.
        """
        child, return_value = self.run_cmd('dawr_pointer')
        child.sendline('break main')
        child.expect('(gdb)')
        child.sendline('r')
        child.expect('(gdb)')
        child.sendline('awatch val')
        return_value.append(child.expect_exact(['watchpoint', pexpect.TIMEOUT]))
        child.sendline('c')
        return_value.append(child.expect_exact(
            ['New value', pexpect.TIMEOUT]))
        for i in return_value:
            if i != 0:
                self.fail('DAWR watchpoint test failed for pointer variable')

    def test_dawr_struct_gdb(self):
        """
        Setting Read/Write watchpoint on a struct member (d.y) using
        awatch and verifying the watchpoint triggers on write.
        awatch triggers twice for d.y += 5: first on READ (Value=20),
        then on WRITE (New value=25). Send 'c' twice to reach the write hit.
        """
        child, return_value = self.run_cmd('dawr_struct')
        child.sendline('break main')
        child.expect('(gdb)')
        child.sendline('r')
        child.expect('(gdb)')
        # Step past struct initialization so d.y is in scope
        child.sendline('next')
        child.expect('(gdb)')
        child.sendline('awatch d.y')
        return_value.append(child.expect_exact(['watchpoint', pexpect.TIMEOUT]))
        # First continue: hits READ of d.y (Value = 20)
        child.sendline('c')
        child.expect_exact(['Value = 20', pexpect.TIMEOUT])
        # Second continue: hits WRITE of d.y (New value = 25)
        child.sendline('c')
        return_value.append(child.expect_exact(
            ['New value', pexpect.TIMEOUT]))
        for i in return_value:
            if i != 0:
                self.fail('DAWR watchpoint test failed for struct member')

    def test_dawr_array_gdb(self):
        """
        Setting Read/Write watchpoint on an array element (arr[2]) using
        awatch and verifying the watchpoint triggers on write.
        awatch triggers twice for arr[2] += 10: first on READ (Value=3),
        then on WRITE (New value=13). Send 'c' twice to reach the write hit.
        """
        child, return_value = self.run_cmd('dawr_array')
        child.sendline('break main')
        child.expect('(gdb)')
        child.sendline('r')
        child.expect('(gdb)')
        # arr is global so awatch resolves immediately after run
        child.sendline('awatch arr[2]')
        return_value.append(child.expect_exact(['watchpoint', pexpect.TIMEOUT]))
        # First continue: hits READ of arr[2] (Value = 3)
        child.sendline('c')
        child.expect_exact(['Value = 3', pexpect.TIMEOUT])
        # Second continue: hits WRITE of arr[2] (New value = 13)
        child.sendline('c')
        return_value.append(child.expect_exact(
            ['New value', pexpect.TIMEOUT]))
        for i in return_value:
            if i != 0:
                self.fail('DAWR watchpoint test failed for array element')

    def test_dawr_boundary_check(self):
        """
        Run dawr_boundary_check to check
        unaligned 512-byte DAWR boundary condition
        """
        output = self.run_test('./boundary_check')
        data = output.stdout.decode("utf-8")

        expected_msg = "TEST Boundary check PASSED: unaligned_512bytes"
        if expected_msg not in data:
            self.fail(
                f"TEST Boundary check FAILED: unaligned_512bytes.\n"
                f"Output was:\n{data}")
        else:
            self.log.info(expected_msg)

    def tearDown(self):
        # Delete the temporary file
        if os.path.isfile("perf.data"):
            process.run('rm -f perf.data')
