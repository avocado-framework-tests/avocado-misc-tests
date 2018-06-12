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
# Based on code by Mohammed Omar <mohd.omar@in.ibm.com>
#   copyright: 2008 IBM
#   https://github.com/autotest/autotest-client-tests/tree/master/posixtest

import os

from avocado import Test
from avocado import main
from avocado.utils import archive
from avocado.utils import process
from avocado.utils import build
from avocado.utils.software_manager import SoftwareManager


class Posixtest(Test):

    '''
    posix test  provides conformance, functional, and stress testing on
    Os Threads, Clocks & Timers, Signals, Message Queues, and Semaphores.

    :avocado: tags=kernel
    '''

    def setUp(self):
        '''
        Build posixtest
        Source:
            http://ufpr.dl.sourceforge.net/sourceforge/posixtest/posixtestsuite-1.5.2.tar.gz
        '''
        self.test_type = self.params.get('test_type', default='THR')
        sm = SoftwareManager()
        for package in ['gcc', 'make']:
            if not sm.check_installed(package) and not sm.install(package):
                self.cancel("%s is needed for the test to be run" % package)
        tarball = self.fetch_asset("http://ufpr.dl.sourceforge.net"
                                   "/sourceforge/posixtest"
                                   "/posixtestsuite-1.5.2.tar.gz")
        archive.extract(tarball, self.workdir)
        version = os.path.basename(tarball.split('-1.')[0])
        self.sourcedir = os.path.join(self.workdir, version)

        build.make(self.sourcedir)

    def test(self):

        os.chdir(self.sourcedir)
        result = process.system_output(
            './run_tests %s' % self.test_type, ignore_status=True)
        error = False
        for line in str(result).splitlines():
            if 'FAILED' in line:
                error = True
                self.log.info("Testcase failed. Log from test run: %s" % line)

        if error:
            self.fail("Testcase failed during test check the log")


if __name__ == "__main__":
    main()
