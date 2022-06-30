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
from avocado import skipUnless
from avocado.utils import process, build, memory, genio
from avocado.utils.software_manager.manager import SoftwareManager


class HugepageSanity(Test):
    """
    Test allocates given number of hugepages of given size and mmap's
    using MAP_HUGETLB with corresponding hugepage sizes

    :avocado: tags=memory,hugepage
    """

    def copyutil(self, file_name):
        shutil.copyfile(self.get_data(file_name),
                        os.path.join(self.teststmpdir, file_name))

    @skipUnless('Hugepagesize' in dict(memory.meminfo),
                "Hugepagesize not defined in kernel.")
    def setUp(self):
        smm = SoftwareManager()
        self.hpagesize = int(self.params.get(
            'hpagesize', default=memory.get_huge_page_size()/1024))
        cpu_info = genio.read_file("/proc/cpuinfo")
        if 'Radix' in cpu_info and self.hpagesize == 16:
            self.cancel("This hugepage size is not supported.")
        if 'Hash' in cpu_info and self.hpagesize != 16:
            self.cancel("This hugepage size is not supported.")
        self.num_huge = int(self.params.get('num_pages', default='1'))

        for package in ['gcc', 'make']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        for file_name in ['hugepage_sanity.c', 'Makefile']:
            self.copyutil(file_name)

        build.make(self.teststmpdir)

    def test(self):
        os.chdir(self.teststmpdir)
        if process.system('./hugepage_sanity %s %s'
                          % (self.hpagesize, self.num_huge),
                          shell=True, ignore_status=True):
            self.fail("Please Check the log for failures")
