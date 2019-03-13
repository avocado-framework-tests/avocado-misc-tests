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


from avocado import Test
from avocado import main
from avocado.utils import build
from avocado.utils import process, archive
import os

from avocado.utils.software_manager import SoftwareManager


class ltp(Test):

    """
    LTP (Linux Test Project) testsuite
    :param args: Extra arguments ("runltp" can use with
                 "-f $test")
    """

    def setUp(self):
        sm = SoftwareManager()
        deps = ['gcc', 'make', 'automake', 'autoconf']
        for package in deps:
            if not sm.check_installed(package) and not sm.install(package):
                self.cancel(package + ' is needed for the test to be run')
        url = "https://github.com/linux-test-project/ltp/archive/master.zip"
        tarball = self.fetch_asset("ltp-master.zip", locations=[url])
        archive.extract(tarball, self.workdir)
        ltp_dir = os.path.join(self.workdir, "ltp-master")
        os.chdir(ltp_dir)
        build.make(ltp_dir, extra_args='autotools')
        ltpbin_dir = os.path.join(ltp_dir, 'bin')
        os.mkdir(ltpbin_dir)
        process.system('./configure --prefix=%s' % ltpbin_dir)
        build.make(ltp_dir)
        build.make(ltp_dir, extra_args='install')

    def test(self):
        args = self.params.get('args', default='')
        logfile = os.path.join(self.logdir, 'ltp.log')
        failcmdfile = os.path.join(self.logdir, 'failcmdfile')

        args += (" -q -p -l %s -C %s -d %s -S %s"
                 % (logfile, failcmdfile, self.workdir,
                    self.get_data('skipfile')))
        ltpbin_dir = os.path.join(self.workdir, "ltp-master", 'bin')
        cmd = os.path.join(ltpbin_dir, 'runltp') + ' ' + args
        result = process.run(cmd, ignore_status=True)
        # Walk the stdout and try detect failed tests from lines like these:
        # aio01       5  TPASS  :  Test 5: 10 reads and writes in  0.000022 sec
        # vhangup02    1  TFAIL  :  vhangup02.c:88: vhangup() failed, errno:1
        # and check for fail_statuses The first part contain test name
        fail_statuses = ['TFAIL', 'TBROK', 'TWARN']
        split_lines = (line.split(None, 3)
                       for line in result.stdout.splitlines())
        failed_tests = [items[0] for items in split_lines
                        if len(items) == 4 and
                        items[2].strip(":") in fail_statuses]

        if failed_tests:
            self.fail("LTP tests failed: %s" % ", ".join(failed_tests))
        elif result.exit_status != 0:
            self.fail("No test failures detected, but LTP finished with %s"
                      % (result.exit_status))


if __name__ == "__main__":
    main()
