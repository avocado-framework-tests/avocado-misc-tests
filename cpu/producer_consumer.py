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

import json
import os
import platform
import re

from avocado import Test
from avocado.utils import process
from avocado.utils import build, distro, git
from avocado.utils.software_manager import SoftwareManager


class Producer_Consumer(Test):

    '''
    Producer-consumer is a cache affinity scheduler wakeup benchmark.

    :avocado: tags=cpu
    '''

    def setUp(self):
        '''
        Build schbench
        Source:
        https://github.com/gautshen/misc.git
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
        url = 'https://github.com/gautshen/misc.git'
        pc_url = self.params.get("pc_url", default=url)
        git.get_repo(pc_url, destination_dir=self.workdir)
        self.sourcedir = os.path.join(self.workdir, 'producer_consumer')
        os.chdir(self.sourcedir)
        build.make(self.sourcedir)

    def test(self):

        perfstat = self.params.get('perfstat', default='')
        if perfstat:
            perfstat = 'perf stat ' + perfstat
        pcpu = self.params.get('pcpu', default='0')
        ccpu = self.params.get('ccpu', default='1')
        random_seed = self.params.get('random_seed', default=6407741)
        runtime = self.params.get('runtime', default=5)
        verbose = self.params.get('verbose', default=False)
        precompute_random = self.params.get('precompute_random', default=False)
        intermediate_stats = self.params.get(
            'intermediate_stats', default=False)

        cache_size = self.params.get('cache_size')
        if not cache_size:
            iteration_length = self.params.get('iteration_length', default=1024)
            args = '-p %s -c %s -r %s -l %s -t %s' % (pcpu, ccpu, random_seed,
                                                      iteration_length, runtime)
        else:
            args = '-p %s -c %s -r %s -s %s -t %s' % (pcpu, ccpu, random_seed,
                                                      cache_size, runtime)
        if verbose:
            args += ' --verbose'
        if precompute_random:
            args += ' --precompute-random'
        if intermediate_stats:
            args += ' --intermediate-stats'

        cmd = '%s %s/producer_consumer %s' % (perfstat, self.sourcedir, args)
        res = process.run(cmd, ignore_status=True, shell=True)

        if res.exit_status:
            self.fail("The test failed. Failed command is %s" % cmd)
        lines = res.stdout.decode().splitlines()
        for line in lines:
            if line.startswith('Consumer(0) :'):
                print(line)
                pattern = re.compile(r":    (.*?) iterations")
                iteration = pattern.findall(line)[0]
                pattern = re.compile(r"time/iteration: (.*?) ns")
                time_iter = pattern.findall(line)[0]
                pattern = re.compile(r"time/access:  (.*?) ns")
                time_acc = pattern.findall(line)[0]

                json_object = json.dumps({'iterations': iteration,
                                          'iter_time': time_iter,
                                          'access_time': time_acc})
                break

        logfile = os.path.join(self.logdir, "time_log.json")
        with open(logfile, "w") as outfile:
            outfile.write(json_object)
