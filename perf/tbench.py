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
# Author:  Pooja B Surya <pooja@linux.vnet.ibm.com>
#
# Based on code by Martin Bligh <mbligh@google.com>
#   copyright: 2008 Google
# https://github.com/autotest/autotest-client-tests/tree/master/tbench

import os
import time
import signal
import commands
import re
from avocado import Test
from avocado import main
from avocado.utils import archive
from avocado.utils import process
from avocado.utils import build
from avocado.utils.software_manager import SoftwareManager


class tbench(Test):
    def setUp(self):
        sm = SoftwareManager()
        for package in ['gcc', 'make']:
            if not sm.check_installed(package) and not sm.install(package):
                self.error(package + ' is needed for the test to be run')
        tarball = self.fetch_asset(
                  "https://www.samba.org/ftp/tridge/dbench/dbench-3.04.tar.gz",
                  expire='7d')
        archive.extract(tarball, self.srcdir)
        version = os.path.basename(tarball.split('.tar.')[0])
        self.srcdir = os.path.join(self.srcdir, version)
        os.chdir(self.srcdir)
        process.run('./configure', ignore_status=True, sudo=True)
        build.make(self.srcdir)

    def test(self):
        # only supports combined server+client model at the moment
        # should support separate I suppose, but nobody uses it
        nprocs = self.params.get('nprocs', default=None)
        args = self.params.get('args',  default=None)
        if not nprocs:
            nprocs = commands.getoutput("nproc")
        args = args + ' %s' % nprocs

        pid = os.fork()
        if pid:                         # parent
            time.sleep(1)
            client = self.srcdir + '/client.txt'
            args = '-c ' + client + ' ' + '%s' % args
            cmd = os.path.join(self.srcdir, "tbench") + " " + args
            # Standard output is verbose and merely makes our debug logs huge
            # so we don't retain it.  It gets parsed for the results.
            self.results = process.system_output(cmd, shell=True)
            os.kill(pid, signal.SIGTERM)    # clean up the server
        else:                           # child
            server = self.srcdir + '/tbench_srv'
            os.execlp(server, server)
        pattern = re.compile(r"Throughput (.*?) MB/sec (.*?) procs")
        (throughput, procs) = pattern.findall(self.results)[0]
        self.log.info({'throughput': throughput, 'procs': procs})
