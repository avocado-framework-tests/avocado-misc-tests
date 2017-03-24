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
# Author:Shriya Kulkarni <shriyak@linux.vnet.ibm.com>
#

import platform
import os
from avocado import Test
from avocado import main
from avocado.utils import archive, build, process, distro
from avocado.utils.software_manager import SoftwareManager


class Perf_subsystem(Test):

    """
    This series of test is meant to validate
    that the perf_event subsystem is working
    """

    def setUp(self):
        '''
        Install the packages
        '''

        # Check for basic utilities
        smm = SoftwareManager()
        detected_distro = distro.detect()
        kernel_ver = platform.uname()[2]
        if 'Ubuntu' in detected_distro.name:
            deps = ['gcc', 'make', 'linux-tools-common',
                    'linux-tools-' + kernel_ver + '']
        else:
            deps = ['gcc', 'make', 'perf']
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.error('%s is needed for the test to be run' % package)

    def test(self):
        '''
        Execute the perf tests
        Source : https://github.com/deater/perf_event_tests
        '''
        tarball = self.fetch_asset('https://github.com/deater/'
                                   'perf_event_tests/archive/'
                                   'master.zip', expire='7d')
        archive.extract(tarball, self.srcdir)
        self.srcdir = os.path.join(self.srcdir, 'perf_event_tests-master')
        build.make(self.srcdir)
        os.chdir(self.srcdir)
        process.system_output("echo -1 >/proc/sys/kernel/perf_event_paranoid",
                              shell=True)
        cmd = "cat /proc/sys/kernel/perf_event_paranoid"
        if process.system_output(cmd, shell=True) != '-1':
            self.log.info("Unable to set perf_event_paranoid to -1 ")
        out = process.system_output("./run_tests.sh", ignore_status=True)
        if 'FAILED' in out:
            print 'Test cases have failed'


if __name__ == "__main__":
    main()
