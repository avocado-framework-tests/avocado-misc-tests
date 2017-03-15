#!/usr/bin/env python
#
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
# Author:Praveen K Pandey <praveen@linux.vnet.ibm.com>
#


import os

from avocado import Test
from avocado import main
from avocado.utils import archive, build
from avocado.utils.software_manager import SoftwareManager


class Perftool(Test):

    """
    perftool-testsuite
    """

    def setUp(self):
        '''
        Build perftool Test
        Source:
        https://github.com/rfmvh/perftool-testsuite
        Run perf test
        Execute perf tests
        Source : https://github.com/deater/perf_event_tests

        '''

        # Check for basic utilities
        smm = SoftwareManager()
        for package in ['gcc', 'make']:
            if not smm.check_installed(package) and not smm.install(package):
                self.error('%s is needed for the test to be run' % package)
        if SoftwareManager().check_installed("linux-tools-common") is False:
            if SoftwareManager().install("linux-tools-common") is False:
                self.skip("linux-tools-common is not installing")
        if SoftwareManager().install("linux-tools-$(uname-r)") is False:
            self.skip("linux-tools-$(uname-r) is not installing")

        locations = ["https://github.com/rfmvh/perftool-testsuite/archive/"
                     "master.zip"]
        tarball = self.fetch_asset("perftool.zip", locations=locations,
                                   expire='7d')
        archive.extract(tarball, self.srcdir)
        self.srcdir = os.path.join(self.srcdir, 'perftool-testsuite-master')

    def test(self):
        self.count = 0
        for line in build.run_make(self.srcdir, extra_args='check',
                                   ignore_status=True).stdout.splitlines():
            if '-- [ FAIL ] --' in line:
                self.count += 1
                self.log.info(line)
        if self.count > 0:
            self.fail("%s Test failed" % self.count)

        process.system_output("perf test")
        tarball = self.fetch_asset('https://github.com/deater/'
                                   'perf_event_tests/archive/'
                                   'master.zip', expire='7d')
        archive.extract(tarball, self.srcdir)
        self.srcdir = os.path.join(self.srcdir, 'perf_event_tests-master')
        build.make(self.srcdir)
        os.chdir(self.srcdir)
        process.system_output("echo -1 >/proc/sys/kernel/"
                              "perf_event_paranoid")
        process.system_output("./run_tests.sh")


if __name__ == "__main__":
    main()
