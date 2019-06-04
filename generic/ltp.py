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
from avocado.utils import build, distro
from avocado.utils import process, archive
import os
import re

from avocado.utils.software_manager import SoftwareManager


class ltp(Test):

    """
    LTP (Linux Test Project) testsuite
    :param args: Extra arguments ("runltp" can use with
                 "-f $test")
    """
    failed_tests = list()

    def setUp(self):
        sm = SoftwareManager()
        dist = distro.detect()

        deps = ['gcc', 'make', 'automake', 'autoconf']
        if dist.name == "Ubuntu":
            deps.extend(['libnuma-dev'])
        elif dist.name in ["centos", "rhel", "fedora"]:
            deps.extend(['numactl-devel'])
        elif dist.name == "SuSE":
            deps.extend(['libnuma-devel'])

        for package in deps:
            if not sm.check_installed(package) and not sm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
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
        # Walk the ltp.log and try detect failed tests from lines like these:
        # msgctl04                                           FAIL       2
        with open(logfile, 'r') as fp:
            lines = fp.readlines()
            for line in lines:
                if 'FAIL' in line:
                    value = re.split(r'\s+', line)
                    self.failed_tests.append(value[0])

        if self.failed_tests:
            self.fail("LTP tests failed: %s" % self.failed_tests)


if __name__ == "__main__":
    main()
