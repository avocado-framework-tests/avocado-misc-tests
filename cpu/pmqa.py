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
# Copyright: 2016 IBM
# Author:Praveen K Pandey <praveen@linux.vnet.ibm.com>
#


import os

from avocado import Test
from avocado import main
from avocado.utils import process, git
from avocado.utils.software_manager import SoftwareManager


class Pmqa(Test):

    """
    pmqa Testsuite these cpu test
    cpufreq, cpuhotplug, cputopology
    cpuidlee, thermal
    """

    def setUp(self):
        '''
        Build Pmqa Test
        Source:
        git://git.linaro.org/power/pm-qa.git
        '''
        self.failtest = 0

        # Check for basic utilities
        smm = SoftwareManager()
        if not smm.check_installed("gcc") and not smm.install("gcc"):
            self.error('Gcc is needed for the test to be run')

        git.get_repo('git://git.linaro.org/power/pm-qa.git',
                     destination_dir=self.srcdir)

    def _run_one(self, testcase):

        os.chdir(self.srcdir)
        log = os.path.join(self.logdir, 'stdout')

        ext_opt = ''
        if testcase == 'cpuhotplug':
            ext_opt = 'hotplug_allow_cpu0=0'

        cmd = '%s %s run_tests' % (testcase, ext_opt)

        process.system('make -C %s' % cmd, ignore_status=True, shell=True)

        result = process.run("grep -wF 'fail' %s" % log, ignore_status=True)

        if not result.stdout == '':
            self.log.info(result.stdout)
            return True

        return False

    def test(self):
        error = False

        self.test_type = self.params.get('run_arg', default='cpufreq')

        error = self._run_one(self.test_type)

        if error:
            self.fail("few tests failed")

if __name__ == "__main__":
    main()
