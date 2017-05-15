#! /usr/bin/env python

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
# Author: Harish <harisrir@linux.vnet.ibm.com>
#
# Based on code by Martin J. Bligh <mbligh@google.com>
#   copyright 2006 Google, Inc.
#   https://github.com/autotest/autotest-client-tests/tree/master/dbench

import os
import re
import multiprocessing
import json

from avocado import Test
from avocado import main
from avocado.utils import archive
from avocado.utils import process
from avocado.utils import build
from avocado.utils.software_manager import SoftwareManager


class Dbench(Test):

    """
    Dbench is a tool to generate I/O workloads to either a filesystem or to a
    networked CIFS or NFS server.
    Dbench is a utility to benchmark a system based on client workload
    profiles.
    """

    def setUp(self):
        '''
        Build Dbench
        Source:
        http://samba.org/ftp/tridge/dbench/dbench-3.04.tar.gz
        '''
        sm = SoftwareManager()
        if not sm.check_installed("gcc") and not sm.install("gcc"):
            self.error('Gcc is needed for the test to be run')

        self.results = []
        data_dir = os.path.abspath(self.datadir)
        tarball = self.fetch_asset(
            'http://samba.org/ftp/tridge/dbench/dbench-3.04.tar.gz')
        archive.extract(tarball, self.srcdir)
        cb_version = os.path.basename(tarball.split('.tar.')[0])
        self.srcdir = os.path.join(self.srcdir, cb_version)
        os.chdir(self.srcdir)
        patch = self.params.get('patch', default='dbench_startup.patch')
        process.run('patch -p1 < %s' % data_dir + '/' + patch, shell=True)
        process.run('./configure')
        build.make(self.srcdir)

    def test(self):
        '''
        Test Execution with necessary args
        '''
        dir = self.params.get('dir', default='.')
        nprocs = self.params.get('nprocs', default=None)
        seconds = self.params.get('seconds', default=60)
        args = self.params.get('args', default='')
        if not nprocs:
            nprocs = multiprocessing.cpu_count()
        loadfile = os.path.join(self.srcdir, 'client.txt')
        cmd = '%s/dbench %s %s -D %s -c %s -t %d' % (self.srcdir, nprocs, args,
                                                     dir, loadfile, seconds)
        process.run(cmd)

        self.results = process.system_output(cmd)
        pattern = re.compile(r"Throughput (.*?) MB/sec (.*?) procs")
        (throughput, procs) = pattern.findall(self.results)[0]
        self.whiteboard = json.dumps({'throughput': throughput,
                                      'procs': procs})


if __name__ == "__main__":
    main()
