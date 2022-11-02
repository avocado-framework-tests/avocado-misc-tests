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
# Copyright: 2022 AMD 
# Author: Kalpana Shetty <kalpana.shetty@amd.com>
#

import os
from avocado import Test
from avocado import skipUnless
from avocado.utils import cpu, git, genio, build, process, linux_modules
from avocado.utils.software_manager.manager import SoftwareManager


class PageTable(Test):
    """
    Tests 5-level, 4-level page table depending on the supported platform.
          * Test will detect CPU feature, 5 Level page table.
          * Check for kernel support
          * Run series of 5-level page tests from "pg-table_tests.git" that covers
	        - heap, mmap, shmat tests.
    :avocado: tags=memory
    """

    @skipUnless('x86_64' in cpu.get_arch(),
                "This test runs on x86-64 platform.\
        If 5-level page table supported on other platform then\
        this condition can be removed")
    def setUp(self):
        '''
        Install pre-requisites packages. 
        Setup pa-table_tests.git
        '''
        smm = SoftwareManager()
        for package in ['gcc', 'make']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

        self.url = self.params.get('url', default=None)
        git.get_repo(self.url, destination_dir=self.teststmpdir)
        os.chdir(self.teststmpdir)
        build.make(self.teststmpdir)

    def test_detect_5lvl(self):
        '''
        Detect 5-Level page table CPU feature
        '''
        cpu_info = genio.read_file("/proc/cpuinfo")
        if 'la57' in cpu_info:
           self.log.info("Detected 5-Level page table cpu support")
        else:
           self.fail("5-Level page table - Unsupported platform")

    def test_kernel(self):
        '''
        Check 5-Level page table support at kernel.
        '''
        cfg_param = "CONFIG_X86_5LEVEL"
        result = linux_modules.check_kernel_config(cfg_param)
        if result == linux_modules.ModuleConfig.NOT_SET:
           self.fail("%s is not set in the kernel." % cfg_param)
        else:
           self.log.info("Detected 5-Level page table config - CONFIG_X86_5LEVEL set in the kernel")

    def test_pg_table_tests(self):
        '''
        Run series of 5-level page tests from "pg-table_tests.git" that covers
                - heap, mmap, shmat tests.
        '''
        output = process.run('./run-tests')
        err_msg = []
        for line in output.stdout.decode('utf-8').splitlines():
            if "failed" in line:
                err_msg.append(line)
        if err_msg:
            self.fail("Page Table tests failed: %s" % err_msg)
        else:
            self.log.info("Page Table tests passed.")
