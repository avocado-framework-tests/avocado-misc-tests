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
# Based on code by Gautham Shenoy <ego@linux.vnet.ibm.com>

import os
import multiprocessing

from avocado import Test
from avocado.utils import process
from avocado.utils import build, git
from avocado.utils.software_manager import SoftwareManager


class Idle_ipi_latency(Test):

    '''
    Idle-ipi-latency is a benchmark to measure the impact of platform
    idle-states latency and the IPI latency on the scheduler wakeups.

    :avocado: tags=cpu
    '''

    def setUp(self):
        '''
        Build schbench
        Source:
        https://github.com/gautshen/misc.git
        '''
        sm = SoftwareManager()
        for package in ['gcc', 'make']:
            if not sm.check_installed(package) and not sm.install(package):
                self.cancel("%s is needed for the test to be run" % package)
        url = 'https://github.com/gautshen/misc.git'
        ipi_url = self.params.get("ipi_url", default=url)
        git.get_repo(ipi_url, destination_dir=self.workdir)
        self.sourcedir = os.path.join(
            self.workdir, 'idle-ipi-scheduler-latency')
        os.chdir(self.sourcedir)
        build.make(self.sourcedir)

    def test(self):

        lastcpu_nr = int(multiprocessing.cpu_count()) - 1
        perfstat = self.params.get('perfstat', default='')
        if perfstat:
            perfstat = 'perf stat ' + perfstat
        cpua = self.params.get('cpua', default=0)
        runtime = self.params.get('runtime', default=10)
        logdir = self.params.get('logdir', default='/tmp/logs')
        lastcpu = self.params.get('lastcpu', default=lastcpu_nr)
        summarydir = self.params.get('summarydir', default='summary')

        args1 = '-a %s -t %s -l %s -z %s' % (cpua, runtime, logdir, lastcpu)
        args2 = '-l %s -o %s' % (logdir, summarydir)

        cmd1 = '%s %s/idle_ipi_scheduler_latency.sh %s' % (perfstat,
                                                           self.sourcedir, args1)
        if process.system(cmd1, ignore_status=True, shell=True):
            self.fail("The test failed. Failed command is %s" % cmd1)

        cmd2 = '%s/postprocess_data.sh %s' % (self.sourcedir, args2)
        if process.system(cmd2, ignore_status=True, shell=True):
            self.fail("The test failed. Failed command is %s" % cmd1)
