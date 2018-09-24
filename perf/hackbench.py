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
#
# Copyright: 2016 IBM
# Author: Praveen K Pandey <praveen@linux.vnet.ibm.com>
#
# Based on code by Nikhil Rao <ncrao@google.com>
#   copyright: 2008 Google
#   https://github.com/autotest/autotest-client-tests/tree/master/hackbench

import os
import shutil
import json

from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils.software_manager import SoftwareManager


class Hackbench(Test):

    """
    This module will run the hackbench benchmark. Hackbench is a benchmark for
    measuring the performance, overhead and scalability of the Linux scheduler.
    The C program was pick from Ingo Molnar's page.
    """

    def setUp(self):
        '''
        Build Hackbench
        Source:
        http://people.redhat.com/~mingo/cfs-scheduler/tools/hackbench.c
        '''
        self._threshold_time = self.params.get('time_val', default=None)
        self._num_groups = self.params.get('num_groups', default=90)
        self._iterations = self.params.get('iterations', default=1)
        self.results = None
        sm = SoftwareManager()
        if not sm.check_installed("gcc") and not sm.install("gcc"):
            self.cancel("Gcc is needed for the test to be run")
        hackbench = self.fetch_asset('http://people.redhat.com'
                                     '/~mingo/cfs-scheduler/'
                                     'tools/hackbench.c')
        shutil.copyfile(hackbench, os.path.join(self.workdir, 'hackbench.c'))

        os.chdir(self.workdir)

        if 'CC' in os.environ:
            cc = '$CC'
        else:
            cc = 'cc'
        process.system('%s  hackbench.c -o hackbench -lpthread' % cc)

    def test(self):

        hackbench_bin = os.path.join(self.workdir, 'hackbench')
        cmd = '%s %s' % (hackbench_bin, self._num_groups)
        time_spent = 0
        perf_json = {}
        for run in range(self._iterations):
            self.log.info("Iteration " + str(run+1))
            self.results = process.system_output(cmd, shell=True)
            for line in self.results.split('\n'):
                if line.startswith('Time:'):
                    time_spent += float(line.split()[1])
                    break
        perf_json = {'time': time_spent}
        self.whiteboard = json.dumps(perf_json)
        self.log.info("Time Taken:" + str(time_spent))
        if self._threshold_time:
            if self._threshold_time <= time_spent:
                self.error("Test failed: Time Taken "
                           "greater or equal to threshold")


if __name__ == "__main__":
    main()
