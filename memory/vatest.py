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
# Copyright: 2017 IBM
# Author:Praveen K Pandey<praveen@linux.vnet.ibm.com>
#        Harish <harish@linux.vnet.ibm.com>
#

import os
import shutil

from avocado import Test
from avocado import main
from avocado.utils import process, build, memory, genio, distro
from avocado.utils.software_manager import SoftwareManager


class VATest(Test):
    """
    Performs Virtual address space validation

    :avocado: tags=memory,power
    """

    def setUp(self):
        '''
        Build VA Test
        '''

        # Check for basic utilities
        smm = SoftwareManager()
        self.scenario_arg = int(self.params.get('scenario_arg', default=1))
        self.n_chunks = nr_pages = self.n_chunks2 = self.def_chunks = 0
        self.hsizes = [1024, 2]
        self.hp_file = '/sys/kernel/mm/hugepages/hugepages-%skB/nr_hugepages'
        page_chunker = memory.meminfo.Hugepagesize.m
        if distro.detect().arch in ['ppc64', 'ppc64le']:
            mmu_detect = genio.read_file(
                '/proc/cpuinfo').strip().splitlines()[-1]
            # Check for "Radix" as this MMU will be explicit in POWER
            if 'Radix' not in mmu_detect:
                self.hsizes = [16]
                # For now, 16G hugepages are possible only when it is default.
                # So check and add to the possible pagesize list
                if page_chunker == 16384:
                    self.hsizes.extend([16384])

        if self.scenario_arg not in range(1, 13):
            self.cancel("Test need to skip as scenario will be 1-12")
        elif self.scenario_arg in [7, 8, 9]:
            self.log.info("Using alternate hugepages")
            if len(self.hsizes) == 1:
                self.cancel('Scenario is not applicable')
            if memory.meminfo.Hugepagesize.m == self.hsizes[0]:
                page_chunker = self.hsizes[1]
            else:
                page_chunker = self.hsizes[0]

        self.exist_pages = memory.get_num_huge_pages()
        if self.scenario_arg in [10, 11, 12]:
            self.log.info("Using Multiple hugepages")
            if len(self.hsizes) == 1:
                self.cancel('Scenario is not applicable')
            if memory.meminfo.Hugepagesize.m != self.hsizes[0]:
                self.hsizes.reverse()

            # Leaving half size for default pagesize
            total_mem = (0.9 * memory.meminfo.MemFree.m) / 2
            self.def_chunks = int(total_mem / 16384)
            for hp_size in self.hsizes:
                nr_pgs = int((total_mem / 2) / hp_size)
                genio.write_file(self.hp_file %
                                 str(hp_size * 1024), str(nr_pgs))
            n_pages = genio.read_file(self.hp_file % str(
                self.hsizes[0] * 1024)).rstrip("\n")
            n_pages2 = genio.read_file(self.hp_file % str(
                self.hsizes[1] * 1024)).rstrip("\n")
            self.n_chunks = (int(n_pages) * self.hsizes[0]) / 16384
            self.n_chunks2 = (int(n_pages2) * self.hsizes[1]) / 16384
        if self.scenario_arg not in [1, 2, 10, 11, 12]:
            max_hpages = int((0.9 * memory.meminfo.MemFree.m) / page_chunker)
            if self.scenario_arg in [3, 4, 5, 6]:
                memory.set_num_huge_pages(max_hpages)
                nr_pages = memory.get_num_huge_pages()
            else:
                genio.write_file(self.hp_file % str(
                    page_chunker * 1024), str(max_hpages))
                nr_pages = genio.read_file(self.hp_file % str(
                    page_chunker * 1024)).rstrip("\n")
            self.n_chunks = (int(nr_pages) * page_chunker) / 16384

        for packages in ['gcc', 'make']:
            if not smm.check_installed(packages) and not smm.install(packages):
                self.cancel('%s is needed for the test to be run' % packages)

        shutil.copyfile(self.get_data('va_test.c'),
                        os.path.join(self.teststmpdir, 'va_test.c'))

        shutil.copyfile(self.get_data('Makefile'),
                        os.path.join(self.teststmpdir, 'Makefile'))

        build.make(self.teststmpdir)

    def test(self):
        '''
        Execute VA test
        '''
        os.chdir(self.teststmpdir)
        args = "-s %s -n %s -h %s -d %s" % (self.scenario_arg, self.n_chunks,
                                            self.n_chunks2, self.def_chunks)
        result = process.run('./va_test %s' %
                             args, shell=True, ignore_status=True)
        for line in result.stdout.splitlines():
            if b'failed' in line:
                self.fail("test failed, Please check debug log for failed"
                          "test cases")

    def tearDown(self):
        if self.scenario_arg in [7, 8, 9, 10, 11, 12]:
            for hp_size in self.hsizes:
                genio.write_file(self.hp_file % str(hp_size * 1024), str(0))
        if self.scenario_arg not in [1, 2]:
            memory.set_num_huge_pages(self.exist_pages)


if __name__ == "__main__":
    main()
