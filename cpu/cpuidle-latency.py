#!/usr/bin/env python

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
# Author: Abhishek Goel<huntbag@linux.vnet.ibm.com>
#
# Based on code by Pratik Sampat<psampat@linux.ibm.com>

import os
import shutil

from avocado import Test
from avocado.utils import process
from avocado.utils import build, git
from avocado.utils.software_manager import SoftwareManager


class Cpuidle_latency(Test):

    '''
    Cpuidle latency is a kernel module based userspace driver to estimate the
    wakeup latency for cpus that are in idle stop states.

    :avocado: tags=cpu
    '''

    def setUp(self):
        '''
        Build cpuidle-latency
        Source:
        https://github.com/pratiksampat/cpuidle-latency-measurements.git
        '''
        sm = SoftwareManager()
        for package in ['gcc', 'make']:
            if not sm.check_installed(package) and not sm.install(package):
                self.cancel("%s is needed for the test to be run" % package)
        url = 'https://github.com/pratiksampat/cpuidle-latency-measurements.git'
        ipi_url = self.params.get("ipi_url", default=url)
        git.get_repo(ipi_url, branch='main', destination_dir=self.workdir)
        os.chdir(self.workdir)
        build.make(self.workdir)
        if not os.path.isfile("test-cpuidle_latency.ko"):
            self.cancel("Module build failed. Please check the build log")

    def test(self):

        perfstat = self.params.get('perfstat', default='')
        if perfstat:
            perfstat = 'perf stat ' + perfstat
        verbose = self.params.get('verbose', default=False)
        cmd = '%s %s/cpuidle.sh' % (perfstat, self.workdir)

        if verbose:
            cmd += ' -v'

        if process.system(cmd, ignore_status=True, shell=True):
            self.fail("The test failed. Failed command is %s" % cmd)

        logfile = "%s/cpuidle.log" % self.workdir
        shutil.copy(logfile, self.logdir)
