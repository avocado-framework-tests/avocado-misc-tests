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
# Copyright: 2018 IBM
# Author:Praveen K Pandey <praveen@linux.vnet.ibm.com>
#


import os

from avocado import Test
from avocado.utils import process, archive, build, dmesg
from avocado.utils.software_manager.manager import SoftwareManager


class FsFuzz(Test):

    """
    fs-fuzz : Two simple fuzzers, both for  filesystem operations
    """

    def verify_dmesg(self):
        self.whiteboard = process.system_output("dmesg").decode()
        pattern = ['WARNING: CPU:', 'Oops',
                   'Segfault', 'soft lockup', 'Unable to handle']
        for fail_pattern in pattern:
            if fail_pattern in self.whiteboard:
                self.fail("Test Failed : %s in dmesg" % fail_pattern)

    def setUp(self):
        '''
        Build fs-fuzz
        Source:
        https://github.com/regehr/fs-fuzz
        '''

        # Check for basic utilities
        smm = SoftwareManager()

        for package in ['make', 'gcc']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        locations = ['https://github.com/regehr/fs-fuzz/archive/master.zip']
        tarball = self.fetch_asset(
            "fs-fuzz.zip", locations=locations, expire='7d')

        archive.extract(tarball, self.workdir)
        self.build_dir = os.path.join(self.workdir, 'fs-fuzz-master')
        build.make(self.build_dir)
        dmesg.clear_dmesg()

    def test_fd(self):
        os.chdir(self.build_dir)

        if process.system('./fd_fuzz 1', shell=True, ignore_status=True) != 0:
            self.fail("stress test for  file I/O layer failed")
        self.verify_dmesg()

    def test_file(self):
        os.chdir(self.build_dir)

        if process.system('./file_fuzz 1', shell=True,
                          ignore_status=True) != 0:
            self.fail("stress test for the C streams layer failed")
        self.verify_dmesg()
