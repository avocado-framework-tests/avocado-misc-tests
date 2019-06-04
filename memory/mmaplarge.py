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
# Copyright: 2019 IBM
# Author: Kalpana Shetty
# Description: Test to check process exit / memory unmap on a large
# memory system.
# The 'c' test code is authored by Mikey - Michael Neuling <mikey@linux.ibm.com>.

import os
import shutil
from avocado import Test
from avocado import main
from avocado.utils import process, build, memory
from avocado.utils.software_manager import SoftwareManager


class process_exit_unmap(Test):
    """
    Test to check the process exit / memory unmap on a large
    memory system
    """

    def copyutil(self, file_name):
        shutil.copyfile(self.get_data(file_name),
                        os.path.join(self.teststmpdir, file_name))

    def setUp(self):
        smm = SoftwareManager()
        self.memsize = int(memory.meminfo.MemFree.m)
        self.log.info("memsize=%s", self.memsize)

        for package in ['gcc', 'make']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        for file_name in ['mmaplarge.c', 'Makefile']:
            self.copyutil(file_name)

        build.make(self.teststmpdir)

    def test(self):
        os.chdir(self.teststmpdir)

        if process.system('./mmaplarge %s' % self.memsize,
                          shell=True, ignore_status=True):
            self.fail("Error obtained as unexpected")

        self.log.info("process exit/memory unmap tests pass")


if __name__ == "__main__":
    main()
