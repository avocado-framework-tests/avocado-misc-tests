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
from avocado.utils import archive, build, process, distro, genio
from avocado.utils.software_manager.manager import SoftwareManager


class Perffuzzer(Test):

    """
    This test run the perf fuzzer, which fuzz's the Linux perf_event
    system call interface.
    Source: https://github.com/deater/perf_event_tests/fuzzer
    (http://web.eece.maine.edu/~vweaver/projects/perf_events/fuzzer/)
    This test might crash the kernel
    :avocado: tags=privileged,destructive,perf
    """

    @staticmethod
    def run_cmd_out(cmd):
        return process.system_output(cmd, shell=True, ignore_status=True,
                                     sudo=True)

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
        elif detected_distro.name in ['debian']:
            deps.extend(['linux-perf'])
        elif detected_distro.name in ['rhel', 'SuSE', 'fedora']:
            deps.extend(['perf'])
        else:
            self.cancel("Perf package installation not supported on %s"
                        % detected_distro.name)
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

        tarball = self.fetch_asset('perf-event.zip', locations=[
                                   'https://github.com/deater/'
                                   'perf_event_tests/archive/'
                                   'master.zip'], expire='7d')
        archive.extract(tarball, self.workdir)

    def build_perf_test(self):
        """
        Building the perf event test suite
        """
        self.sourcedir = os.path.join(self.workdir, 'perf_event_tests-master')
        if build.make(self.sourcedir, extra_args="-s -S") > 0:
            self.cancel("Building perf event test suite failed")

    def execute_perf_fuzzer(self):
        os.chdir(self.sourcedir)
        genio.write_one_line("/proc/sys/kernel/perf_event_paranoid", "-1")
        if "-1" not in genio.read_one_line("/proc/sys/kernel/"
                                           "perf_event_paranoid"):
            self.cancel("Unable to set perf_event_paranoid to -1 ")
        self.perf_fuzzer = os.path.join(self.sourcedir, "fuzzer/perf_fuzzer")
        if not os.path.exists(self.perf_fuzzer):
            self.cancel("fuzzer not found at %s" % self.perf_fuzzer)
        self.output = self.run_cmd_out(self.perf_fuzzer).decode("utf-8")

    def test(self):
        '''
        Execute the perf fuzzer
        '''
        self.build_perf_test()
        self.execute_perf_fuzzer()
