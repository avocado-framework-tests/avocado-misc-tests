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
# Author: Harish <harish@linux.vnet.ibm.com>
#
# Based on code by Ranjit Manomohan <ranjitm@google.com>
#   copyright: 2008 Google Inc.
#   https://github.com/autotest/autotest-client-tests/tree/master/memory_api
#


import os
import shutil
from avocado import Test
from avocado import main
from avocado.utils import process, build, memory
from avocado.utils.software_manager import SoftwareManager


class MemorySyscall(Test):
    """
    Excercises malloc, mmap, mprotect, mremap syscalls with 90 %
    of the machine's free memory

    :avocado: tags=memory
    """

    def copyutil(self, file_name):
        shutil.copyfile(self.get_data(file_name),
                        os.path.join(self.teststmpdir, file_name))

    def setUp(self):
        smm = SoftwareManager()
        self.memsize = int(self.params.get(
            'memory_size', default=memory.meminfo.MemFree.m) * 1048576 * 0.5)
        self.induce_err = self.params.get('induce_err', default=0)

        for package in ['gcc', 'make']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        for file_name in ['memory_api.c', 'mremap.c', 'Makefile']:
            self.copyutil(file_name)

        build.make(self.teststmpdir)

    def test(self):
        os.chdir(self.teststmpdir)
        proc = process.SubProcess('./memory_api %s %s' % (self.memsize, self.induce_err),
                                  shell=True, allow_output_check='both')
        proc.start()
        while proc.poll() is None:
            pass

        ret = process.system('./memory_api %s 1' % self.memsize,
                             shell=True, ignore_status=True)
        if ret == 255:
            self.log.info("Error obtained as expected")

        if proc.poll() != 0:
            self.fail("Unexpected application abort, check for possible issues")

    def test_mremap(self):
        os.chdir(self.teststmpdir)
        self.log.info("Testing mremap with minimal memory and expand it")
        if process.system('./mremap %s' % str(memory.meminfo.MemFree.k), ignore_status=True):
            self.fail('Mremap expansion failed')


if __name__ == "__main__":
    main()
