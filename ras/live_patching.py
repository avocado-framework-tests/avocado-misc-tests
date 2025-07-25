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
# Copyright: 2025 IBM
# Author:Pavithra Prakash <pavrampu@linux.vnet.ibm.com>
#


import os
import re
import shutil
import time

from avocado import Test
from avocado.utils import process, git, distro
from avocado.utils.software_manager.manager import SoftwareManager


class LivePatching(Test):
    """
    Test case to verify livepatching feature by livepatching malloc function.
    Ref: https://documentation.suse.com/smart/systems-management/html/ulp-livepatching/index.html
    """

    def copyutil(self, file_name):
        shutil.copyfile(self.get_data(file_name),
                        os.path.join(self.teststmpdir, file_name))

    def setUp(self):
        """
        function sets up the test environment by installing necessary software packages
        and copying required files.
        """
        self.dist = distro.detect()
        if self.dist.name != 'SuSE':
            self.cancel("Test is currently supported only on SLES")
        smm = SoftwareManager()
        deps = ['gcc', 'make', 'libpulp-load-default',
                'libpulp-tools', 'libpulp0', 'libtool', 'automake', 'autoconf',
                'autoconf-archive', 'gcc-c++', 'libjson-c-devel', 'python3-pexpect',
                'psutils', 'libunwind-devel', 'git-core', 'elfutils',
                'libseccomp-devel', 'libelf-devel']
        for packages in deps:
            if not smm.check_installed(packages) and not smm.install(packages):
                self.cancel('%s is needed for the test to be run' % packages)
        for file_name in ['test.c', 'libc_livepatch1.c', 'libc_livepatch1.dsc',
                          'test_2func.c', 'libc_livepatch_2func.c', 'libc_livepatch_2func.dsc',
                          'libc_livepatch_nested.c', 'libc_livepatch_nested.dsc', 'Makefile']:
            self.copyutil(file_name)

    def start_test(self, test='test'):
        """
        function starts running test program
        """
        self.test_process = process.SubProcess(
            'LD_PRELOAD=/usr/lib64/libpulp.so.0 ./%s' % test, shell=True, sudo=True)
        self.pid = self.test_process.start()
        time.sleep(10)

    def apply_livepatch(self, livepatch='libc_livepatch1.so'):
        """
        function applies a live patch to the running test program and returns
        the stderr output
        """
        patch_process = process.SubProcess(
            'ulp trigger -p %s %s' % (self.pid, livepatch), shell=True, sudo=True)
        patch_process.start()
        time.sleep(20)
        return(self.test_process.get_stderr())

    def revert_livepatch(self, livepatch='libc_livepatch1.so'):
        """
        function reverts the applied live patch and returns the stderr output
        """
        revert_process = process.SubProcess(
            'ulp trigger --revert -p %s %s' % (self.pid, livepatch), shell=True, sudo=True)
        revert_process.start()
        self.test_process.wait()
        return (self.test_process.get_stderr())

    def count_string(self, string):
        """
        function counts the occurrences of a given byte string
        """
        return (string.count(b'glibc-livepatch\n'))

    def test_basic(self):
        """
        1. Changes the working directory to the test temporary directory.
        2. Compiles the test program (test.c) and the live patch library (libc_livepatch1.so).
        3. Packages the live patch using ulp packer.
        4. Applies the live patch and checks if at least 10 "glibc-livepatch" messages are
           observed in the output.
        5. Reverts the live patch and verifies that the reversion was successful by checking
           the difference in "glibc-livepatch" messages before and after reversion.
        """
        os.chdir(self.teststmpdir)
        process.system('make', shell=True)
        process.system('ulp packer libc_livepatch1.dsc', shell=True)
        self.start_test()
        livepatch_output = self.apply_livepatch()
        apply_count = self.count_string(livepatch_output)
        if apply_count < 10:
            self.fail("Livepatch test failed")
        else:
            self.log.info(
                "Livepatching is successful %s glibc-livepatch messages observed"
                % apply_count)
        revert_output = self.revert_livepatch()
        if self.count_string(revert_output) - apply_count > 1:
            self.fail("Reverting patch is not successful")

    def test_selftest(self):
        """
        This test case ensures that live patching does not introduce any regressions
        in the self-tests of the `libpulp` repository.
        """
        self.url = self.params.get(
            'url', default="https://github.com/SUSE/libpulp.git")
        git.get_repo(self.url, destination_dir=self.teststmpdir)
        os.chdir(self.teststmpdir)
        process.run('./bootstrap', sudo=True, shell=True)
        process.run('mkdir build', sudo=True, shell=True)
        process.run('./configure --enable-stack-check', sudo=True, shell=True)
        output = process.system_output('make check', sudo=True, shell=True)
        string_output = output.decode()
        match = re.search(r"# FAIL:\s*(\d+)", string_output)
        if match:
            fail_number = int(match.group(1))
        if fail_number > 0:
            self.fail("%s selftests failed for livepatching" % fail_number)
        else:
            self.log.info("livepatching selftests ran without any failures")

    def test_multiple_process_livepatching(self):
        """
        This test case ensures that live patching can successfully
        applied to multiple running processes and prints number of processes patched.
        """
        os.chdir(self.teststmpdir)
        process.system('ulp packer libc_livepatch1.dsc', shell=True)
        self.log.info("Patching all running process")
        output = process.system_output('ulp trigger libc_livepatch1.so',
                                       sudo=True, shell=True, ignore_status=True)
        string_output = output.decode()
        match = re.search(r"Processes patched:\s*(\d+)", string_output)
        if match:
            patch_number = int(match.group(1))
        if patch_number > 1:
            self.log.info("%s process are livepatched" % patch_number)
        else:
            self.log.info("Multiple process livepatching failed")
        output = process.system_output('ulp trigger --revert libc_livepatch1.so',
                                       sudo=True, shell=True, ignore_status=True)
        string_output = output.decode()
        match = re.search(r"Processes patched:\s*(\d+)", string_output)
        if match:
            patch_revert_number = int(match.group(1))
        if patch_revert_number == patch_number:
            self.log.info("livepatch revert successful for %s processes" % patch_revert_number)
        else:
            self.fail("Livepatch revert failed for %s processes" % (patch_number - patch_revert_number))

    def test_two_function_livepatching(self):
        """
        This test function ensures that a livepatch with two functions is successfully applied,
        both functions are live-patched, and the livepatch can be correctly reverted.
        """
        os.chdir(self.teststmpdir)
        process.system('make', shell=True)
        process.system('ulp packer libc_livepatch_2func.dsc', shell=True)
        self.start_test('test_2func')
        livepatch_output = self.apply_livepatch('libc_livepatch_2func.so')
        apply_count = self.count_string(livepatch_output)
        apply_count_2 = livepatch_output.count(b'glibc-livepatch-realloc\n')
        if apply_count_2 < 10:
            self.fail("Livepatch test with 2 functions failed")
        else:
            if apply_count != apply_count_2:
                self.fail("Livepatch test with 2 functions failed,"
                          " both functions are not live patched")
        revert_output = self.revert_livepatch('libc_livepatch_2func.so')
        if self.count_string(revert_output) - apply_count > 1:
            self.fail("Reverting patch is not successful")

    def test_nested_function_livepatching(self):
        """
        This test function ensures that both a primary livepatch and a nested livepatch
        are successfully applied and later reverted.
        """
        os.chdir(self.teststmpdir)
        process.system('make', shell=True)
        process.system('ulp packer libc_livepatch1.dsc', shell=True)
        self.start_test()
        livepatch_output = self.apply_livepatch()
        apply_count_1 = livepatch_output.count(b'glibc-livepatch\n')
        if apply_count_1 < 10:
            self.fail("Applying first livepatch failed.")
        else:
            self.log.info("Successfully applied first livepatch")
        process.system('ulp packer libc_livepatch_nested.dsc', shell=True)
        livepatch_output = self.apply_livepatch('libc_livepatch_nested.so')
        time.sleep(10)
        apply_count_2 = livepatch_output.count(b'glibc-livepatch-nested\n')
        if apply_count_2 < 10:
            self.fail("Applying nested livepatch failed.")
        else:
            self.log.info("Successfully applied nested livepatch")
        process.system_output('ulp trigger --revert -p %s libc_livepatch_nested.so' % self.pid, shell=True)
        time.sleep(10)
        process.system_output('ulp trigger --revert -p %s libc_livepatch1.so' % self.pid, shell=True)
