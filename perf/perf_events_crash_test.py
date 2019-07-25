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
# Copyright: 2018 IBM
# Author:Kamalesh Babulal <kamalesh@linux.vnet.ibm.com>
#

import platform
import os
from avocado import Test
from avocado import main
from avocado.utils import archive, build, process, distro
from avocado.utils.software_manager import SoftwareManager


class Perf_crashevent(Test):

    """
    This series of test is meant to kernel against known issues,
    which might crash the unpatched kernels.
    :avocado: tags=destructive,perf
    """

    @staticmethod
    def run_cmd_out(cmd):
        return process.system_output(cmd, shell=True, ignore_status=True, sudo=True)

    def setUp(self):
        '''
        Install the packages
        '''
        # Check for basic utilities
        smm = SoftwareManager()
        detected_distro = distro.detect()
        deps = ['gcc', 'make']
        if 'Ubuntu' in detected_distro.name:
            kernel_ver = platform.uname()[2]
            deps.extend(['linux-tools-common', 'linux-tools-%s'
                         % kernel_ver])
        # FIXME: "redhat" as the distro name for RHEL is deprecated
        # on Avocado versions >= 50.0.  This is a temporary compatibility
        # enabler for older runners, but should be removed soon
        elif detected_distro.name in ['rhel', 'SuSE', 'fedora', 'redhat']:
            deps.extend(['perf'])
        else:
            self.cancel("Install the package for perf supported by %s"
                        % detected_distro.name)
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

    def build_perf_test(self):
        """
        Building the perf event test suite
        Source : https://github.com/deater/perf_event_tests
        """
        tarball = self.fetch_asset('perf-event.zip', locations=[
                                   'https://github.com/deater/'
                                   'perf_event_tests/archive/'
                                   'master.zip'], expire='7d')
        archive.extract(tarball, self.workdir)
        self.sourcedir = os.path.join(self.workdir, 'perf_event_tests-master')
        if build.make(self.sourcedir, extra_args="-s -S") > 0:
            self.fail("Building perf even test suite failed")

    def execute_perf_test(self):
        self.run_cmd_out("sync")
        self.run_cmd_out("sync")
        self.run_cmd_out("sleep 180")
        os.chdir(self.sourcedir)
        self.run_cmd_out("echo -1 >/proc/sys/kernel/perf_event_paranoid")
        if "-1" not in self.run_cmd_out("cat /proc/sys/kernel/perf_event_paranoid"):
            self.error("Unable to set perf_event_paranoid to -1 ")
        self.output = self.run_cmd_out("./run_crash_tests.sh")

    def test(self):
        '''
        Execute the perf crash tests
        '''
        self.build_perf_test()
        self.execute_perf_test()


if __name__ == "__main__":
    main()
