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
#

import os
import shutil

from avocado import Test
from avocado import main
from avocado.utils import process,  build, memory
from avocado.utils.software_manager import SoftwareManager


class VATest(Test):
    """
    Performs Virtual address space validation

    :avocado: tags=memory, power
    """

    def setUp(self):
        '''
        Build VA Test
        '''

        # Check for basic utilities
        smm = SoftwareManager()
        self.scenario_arg = int(self.params.get('scenario_arg', default=1))
        dic = {2: 1024, 3: 1024, 4: 131072, 5: 1, 6: 1, 7: 2}
        if self.scenario_arg not in range(1, 7):
            self.cancel("Test need to skip as scenario will be 1-7")
        if self.scenario_arg in [2, 3, 4]:
            if memory.meminfo.Hugepagesize.mb != 16:
                self.cancel(
                    "Test need to skip as 16MB huge need to configured")
        elif self.scenario_arg in [5, 6, 7]:
            if memory.meminfo.Hugepagesize.gb != 16:
                self.cancel(
                    "Test need to skip as 16GB huge need to configured")
        if self.scenario_arg != 1:
            memory.set_num_huge_pages(dic[self.scenario_arg])

        for packages in ['gcc', 'make']:
            if not smm.check_installed(packages) and not smm.install(packages):
                self.cancle('%s is needed for the test to be run' % packages)

        shutil.copyfile(os.path.join(self.datadir, 'va_test.c'),
                        os.path.join(self.teststmpdir, 'va_test.c'))

        shutil.copyfile(os.path.join(self.datadir, 'Makefile'),
                        os.path.join(self.teststmpdir, 'Makefile'))

        build.make(self.teststmpdir)

    def test(self):
        '''
        Execute VA test
        '''
        os.chdir(self.teststmpdir)

        result = process.run('./va_test -s %s' %
                             self.scenario_arg, shell=True, ignore_status=True)
        for line in result.stdout.splitlines():
            if 'Problem' in line:
                self.fail("test failed, Please check debug log for failed"
                          "test cases")


if __name__ == "__main__":
    main()
