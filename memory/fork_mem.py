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


import os
import shutil
from avocado import Test
from avocado import main
from avocado.utils import process, build, memory
from avocado.utils.software_manager import SoftwareManager


class Forkoff(Test):
    """
    Perform mmap and process forking to maxiumum extent

    :avocado: tags=memory
    """

    def setUp(self):
        '''
        Use 85% of memory with/without many process forked
        WARNING: System may go out-of-memory based on the available resource
        '''
        smm = SoftwareManager()
        self.itern = int(self.params.get('iterations', default='10'))
        self.procs = int(self.params.get('procs', default='1'))
        self.minmem = int(self.params.get('minmem', default='10'))
        self.fails = []

        if not (self.itern and self.procs and self.minmem):
            self.cancel(
                'Please use a non-zero value for number'
                ' of iterations, processes and memory to be used')

        self.freemem = int(0.85 * memory.meminfo.MemFree.m)
        # Check for basic utilities
        for packages in ['gcc', 'make']:
            if not smm.check_installed(packages) and not smm.install(packages):
                self.cancel('%s is needed for the test to be run' % packages)

        shutil.copyfile(self.get_data('forkoff.c'),
                        os.path.join(self.teststmpdir, 'forkoff.c'))

        shutil.copyfile(self.get_data('Makefile'),
                        os.path.join(self.teststmpdir, 'Makefile'))

        build.make(self.teststmpdir)

    def run_test(self, mem, proc, itern):
        cmd = "./forkoff %s %s %s" % (mem, proc, itern)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fails.append(cmd)

    def test(self):
        '''
        Execute memory fork off tests
        1. Total memory with one process
        2. Split memeory between given processes
        3. Maximum process with minimum memory (10 MB) per process
        '''
        os.chdir(self.teststmpdir)

        self.run_test(self.freemem, 1, self.itern)
        self.run_test(self.freemem // self.procs, self.procs, self.itern)
        self.run_test(self.minmem, self.freemem // self.minmem, self.itern)

        if self.fails:
            self.fail("The following test(s) failed: %s" % self.fails)


if __name__ == "__main__":
    main()
