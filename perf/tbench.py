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

    """
    tbench produces only the TCP and process load. It does the same socket
    calls that smbd would do under a netbench load. It does no filesystem
    calls. The idea behind tbench is to eliminate smbd from the netbench
    test, as though the smbd code could be made infinately fast. The
    throughput results of tbench tell us how fast a netbench run could go
    if we eliminated all filesystem IO and SMB packet processing.tbench
    is built as part of the dbench package.
    """

    def setUp(self):
        sm = SoftwareManager()
        for package in ['gcc', 'make']:
            if not sm.check_installed(package) and not sm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        tarball = self.fetch_asset(
                  "https://www.samba.org/ftp/tridge/dbench/dbench-3.04.tar.gz",
                  expire='7d')
        archive.extract(tarball, self.workdir)
        version = os.path.basename(tarball.split('.tar.')[0])
        self.sourcedir = os.path.join(self.workdir, version)
        os.chdir(self.sourcedir)
        process.run('./configure', ignore_status=True, sudo=True)
        build.make(self.sourcedir)

    def test(self):
        # only supports combined server+client model at the moment
        # should support separate I suppose, but nobody uses it
        nprocs = self.params.get('nprocs', default=commands.getoutput("nproc"))
        args = self.params.get('args',  default=None)
        args = '%s %s' % (args, nprocs)
        pid = os.fork()
        if pid:                         # parent
            client = os.path.join(self.sourcedir, 'client.txt')
            args = '-c %s %s' % (client, args)
            cmd = os.path.join(self.sourcedir, "tbench") + " " + args
            # Standard output is verbose and merely makes our debug logs huge
            # so we don't retain it.  It gets parsed for the results.
            self.results = process.system_output(cmd, shell=True)
            os.kill(pid, signal.SIGTERM)    # clean up the server
        else:                           # child
            server = os.path.join(self.sourcedir, 'tbench_srv')
            os.execlp(server, server)
        pattern = re.compile(r"Throughput (.*?) MB/sec (.*?) procs")
        (throughput, procs) = pattern.findall(self.results)[0]
        self.log.info({'throughput': throughput, 'procs': procs})


if __name__ == "__main__":
    main()
