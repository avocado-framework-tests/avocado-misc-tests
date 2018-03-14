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

    :avocado: tags=cpu,privileged
    """

    def setUp(self):
        '''
        Build Pmqa Test
        Source:
        git://git.linaro.org/power/pm-qa.git
        '''
        if not os.path.exists('/sys/devices/system/cpu/cpu0/cpufreq'):
            self.cancel('sysfs directory for cpufreq is unavailable.')
        # Check for basic utilities
        smm = SoftwareManager()
        for package in ['gcc', 'make']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel(
                    "Fail to install %s required for this test." % package)

        git.get_repo('git://git.linaro.org/power/pm-qa.git',
                     destination_dir=self.workdir)
        self.test_type = self.params.get('run_arg', default='cpufreq')

    def test(self):

        os.chdir(self.workdir)
        log = os.path.join(self.logdir, 'stdout')

        ext_opt = ''
        if self.test_type == 'cpuhotplug':
            ext_opt = 'hotplug_allow_cpu0=0'

        cmd = '%s %s run_tests' % (self.test_type, ext_opt)

        ret = process.run('make -C %s' %
                          cmd, ignore_status=True, shell=True, sudo=True)
        if ret.exit_status:
            self.fail('Test failed with %s' % ret.stderr)

        result = process.run("grep -wF 'fail' %s" % log, ignore_status=True)

        if not result.stdout == '':
            self.log.info(result.stdout)
            self.fail("few tests cases failed please check log")


if __name__ == "__main__":
    main()
