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
import shutil
import time

from avocado import Test
from avocado.utils import process
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
        smm = SoftwareManager()
        deps = ['gcc', 'make', 'libpulp-load-default',
                'libpulp-tools', 'libpulp0']
        for packages in deps:
            if not smm.check_installed(packages) and not smm.install(packages):
                self.cancel('%s is needed for the test to be run' % packages)
        for file_name in ['test.c', 'libc_livepatch1.c', 'libc_livepatch1.dsc']:
            self.copyutil(file_name)

    def apply_livepatch(self):
        """
        function applies a live patch to the running test program and returns
        the stderr output
        """
        self.test_process = process.SubProcess(
            'LD_PRELOAD=/usr/lib64/libpulp.so.0 ./test', shell=True, sudo=True)
        self.pid = self.test_process.start()
        a = self.test_process.get_stderr()
        time.sleep(10)
        patch_process = process.SubProcess(
            'ulp trigger -p %s libc_livepatch1.so' % self.pid,  shell=True, sudo=True)
        patch_process.start()
        time.sleep(20)
        return (self.test_process.get_stderr())

    def revert_livepatch(self):
        """
        function reverts the applied live patch and returns the stderr output
        """
        revert_process = process.SubProcess(
            'ulp trigger --revert -p %s libc_livepatch1.so' % self.pid,  shell=True, sudo=True)
        revert_process.start()
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
        process.system('gcc -o test test.c', shell=True, ignore_status=True)
        process.system('gcc -fPIC -fpatchable-function-entry=16,14 -shared -o '
                       'libc_livepatch1.so libc_livepatch1.c',
                       shell=True, ignore_status=True)
        process.system('ulp packer libc_livepatch1.dsc',
                       shell=True, ignore_status=True)
        livepatch_output = self.apply_livepatch()
        apply_count = self.count_string(livepatch_output)
        if apply_count < 10:
            self.fail("Livepatch test failed")
        else:
            self.log.info(
                "Livepatching is successful %s glibc-livepatch messages observed" % apply_count)
        revert_output = self.revert_livepatch()
        self.test_process.wait()
        if self.count_string(revert_output) - apply_count:
            self.fail("Reverting patch is not successful")
