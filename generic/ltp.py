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
# Author: Santhosh G <santhog4@linux.vnet.ibm.com>
#
# Based on code by Martin Bligh <mbligh@google.com>
# copyright 2006 Google, Inc.
# https://github.com/autotest/autotest-client-tests/tree/master/ltp


import os
import multiprocessing
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils import build
from avocado.utils import git
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import distro


class ltp(Test):
    def setUp(self):
        sm = SoftwareManager()
        detected_distro = distro.detect()
        deps = ['gcc', 'git', 'make', 'automake', 'autoconf']
        for package in deps:
            if package == 'git' and detected_distro.name == "SuSE":
                package = 'git-core'
            if not sm.check_installed(package) and not sm.install(package):
                self.error(package + ' is needed for the test to be run')
        git.get_repo('https://github.com/linux-test-project/ltp.git',
                     destination_dir=self.srcdir)
        os.chdir(self.srcdir)
        build.make(self.srcdir, extra_args='autotools')
        ltpbin_dir = os.path.join(self.srcdir, 'bin')
        os.mkdir(ltpbin_dir)
        process.system('./configure --prefix=%s' % ltpbin_dir)
        build.make(self.srcdir, extra_args='-j %d' %
                   multiprocessing.cpu_count())
        build.make(self.srcdir, extra_args='install')

    def test(self):
        script = self.params.get('script', default='runltplite.sh')
        args = self.params.get('args', default=' ')
        if script == 'runltp':
            logfile = os.path.join(self.logdir, 'ltp.log')
            failcmdfile = os.path.join(self.logdir, 'failcmdfile')
            skipfile = os.path.join(self.datadir, 'skipfile')
            args2 = '-q -p -l %s -C %s -d %s -S %s' % (
                logfile, failcmdfile, self.srcdir, skipfile)
            args = args + ' ' + args2
        ltpbin_dir = os.path.join(self.srcdir, 'bin')
        cmd = os.path.join(ltpbin_dir, script) + ' ' + args
        result = process.run(cmd, ignore_status=True)
        failed_tests = []
        for line in result.stdout.splitlines():
            if set(('TFAIL', 'TBROK', 'TWARN')).intersection(line.split()):
                test_name = line.strip().split(' ')[0]
                if test_name not in failed_tests:
                    failed_tests.append(test_name)

        if failed_tests:
            self.error("LTP tests failed: %s" % failed_tests)

if __name__ == "__main__":
    main()
