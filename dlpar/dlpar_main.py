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
# Copyright: 2021 IBM
# Author: Kalpana Shetty <kalshett@in.ibm.com>
#

import os

from avocado import Test
from avocado.utils import process
from avocado import skipUnless

IS_POWER_VM = 'pSeries' in open('/proc/cpuinfo', 'r').read()

class DlparTests(Test):

    """
    Dlpar CPU/MEMORY  tests - ADD/REMOVE/MOVE
    """
    @skipUnless(IS_POWER_VM,
                "DLPAR test is supported only on PowerVM platform")
    def setUp(self):
        self.lpar_mode = self.params.get('mode', default='dedicated')

    def test_dlpar(self):
        '''
        Execute dlpar dedicated/shared and memory tests
        '''
        if self.lpar_mode == 'dedicated':
           self.log.info("Dedicated Lpar....")
           self.test_case = self.params.get('test_case', default='cpu')
           self.log.info("TestCase: %s" % self.test_case)
           if self.test_case == 'cpu':
              self.log.info("DED: Calling dedicated_cpu.py")
              test_cmd = './dedicated_cpu.py'
           elif self.test_case  == 'mem':
              self.log.info("DED: Calling memory.py")
              test_cmd = './memory.py'
        elif self.lpar_mode == 'shared':
           self.log.info("Shared Lpar.....")
           self.test_case = self.params.get('test_case', default='cpu')
           self.log.info("TestCase: %s" % self.test_case)
           if self.test_case == 'cpu':
              self.log.info("SHR: Calling cpu_unit.py")
              test_cmd = './cpu_unit.py'
           elif self.test_case  == 'mem':
              self.log.info("SHR: Calling memory.py")
              test_cmd = './memory.py'

        os.chmod(test_cmd, 0o755)
        result = process.run(test_cmd, shell=True)
        errors = 0
        warns = 0
        for line in result.stdout.decode().splitlines():
            if 'FAILED' in line:
                self.log.info(line)
                errors += 1
            elif 'WARNING' in line:
                self.log.info(line)
                warns += 1

        if errors == 0 and warns > 0:
            self.warn('number of warnings is %s', warns)

        elif errors > 0:
            self.log.warn('number of warnings is %s', warns)
            self.fail("number of errors is %s" % errors)
