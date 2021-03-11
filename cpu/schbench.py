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

import os
import platform

from avocado import Test
from avocado.utils import process
from avocado.utils import build, distro, git
from avocado.utils.software_manager import SoftwareManager


class Schbench(Test):

    '''
    schbench is designed to provide detailed latency distributions for scheduler
    wakeups.

    :avocado: tags=cpu
    '''

    def setUp(self):
        '''
        Build schbench
        Source:
        https://git.kernel.org/pub/scm/linux/kernel/git/mason/schbench.git
        '''
        sm = SoftwareManager()
        distro_name = distro.detect().name
        deps = ['gcc', 'make']
        if 'Ubuntu' in distro_name:
            deps.extend(['linux-tools-common', 'linux-tools-%s' %
                         platform.uname()[2]])
        elif distro_name in ['rhel', 'SuSE', 'fedora', 'centos']:
            deps.extend(['perf'])
        else:
            self.cancel("Install the package for perf supported \
                         by %s" % distro_name)

        for package in deps:
            if not sm.check_installed(package) and not sm.install(package):
                self.cancel("%s is needed for the test to be run" % package)
        url = 'https://git.kernel.org/pub/scm/linux/kernel/git/mason/schbench.git'
        schbench_url = self.params.get("schbench_url", default=url)
        git.get_repo(schbench_url, destination_dir=self.workdir)

        os.chdir(self.workdir)
        build.make(self.workdir)

    def test(self):

        perfstat = self.params.get('perfstat', default='')
        if perfstat:
            perfstat = 'perf stat ' + perfstat
        taskset = self.params.get('taskset', default='')
        if taskset:
            taskset = 'taskset -c ' + taskset
        num_threads = self.params.get('num_threads', default=10)
        num_workers = self.params.get('num_workers', default=10)
        bytes = self.params.get('bytes', default=1000)
        runtime = self.params.get('runtime', default=100)
        cputime = self.params.get('cputime', default=10000)
        autobench = self.params.get('autobench', default=False)
        args = '-m %s -t %s -p %s -r %s -s %s ' % (num_threads, num_workers,
                                                   bytes, runtime, cputime)

        if autobench:
            args += '-a'

        cmd = "%s %s %s/schbench %s" % (perfstat, taskset, self.workdir, args)
        if process.system(cmd, ignore_status=True, shell=True):
            self.fail("The test failed. Failed command is %s" % cmd)
