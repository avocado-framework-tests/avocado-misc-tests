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
# Copyright: 2021 IBM
# Author: Kalpana Shetty <kalshett@in.ibm.com>
#

import os

from avocado import Test
from avocado.utils import distro, process, archive, git
from avocado.utils.software_manager import SoftwareManager


class Linuxtrace(Test):

    """
    Linux Trace tests
    """

    failed_tests = list()
    @staticmethod
    def run_cmd_out(self, cmd):
        logfile = "/tmp/ftracetest.log"
        process.system_output(cmd, ignore_status=True)
        with open(logfile, 'r') as file_p:
            lines = file_p.readlines()
            for line in lines:
                if 'FAIL' in line:
                    self.failed_tests.append(line)

    def setUp(self):
        '''
        Install the pre-requisites packages and download kernel source
        '''
        self.testdir = "tools/testing/selftests/ftrace"
        smg = SoftwareManager()
        self.version = self.params.get('type', default='upstream')
        detected_distro = distro.detect()

        if self.version == 'distro':
            # Make sure kernel source repo is configured
            if detected_distro.name in ['rhel', 'centos']:
                self.buldir = smg.get_source("kernel", self.workdir)
                self.buldir = os.path.join(
                    self.buldir, os.listdir(self.buldir)[0])
            elif 'SuSE' in detected_distro.name:
                if not smg.check_installed("kernel-source") and not\
                        smg.install("kernel-source"):
                    self.cancel(
                        "Failed to install kernel-source for this test.")
                if not os.path.exists("/usr/src/linux"):
                    self.cancel("kernel source missing after install")
                self.buldir = "/usr/src/linux"
        else:
            location = self.params.get('location', default='https://github.c'
                                       'om/torvalds/linux/archive/master.zip')
            self.output = "linux-master"

            match = next(
                (ext for ext in [".zip", ".tar"] if ext in location), None)
            if match:
                tarball = self.fetch_asset("kselftest%s" % match,
                                           locations=[location], expire='1d')
                archive.extract(tarball, self.workdir)
            else:
                git.get_repo(location, destination_dir=self.workdir)
            self.buldir = os.path.join(self.workdir, self.output)
        os.chdir(os.path.join(self.buldir, self.testdir))

    def test_ftrace(self):
        '''
        Execute ftrace tests
        '''
        self.args = self.params.get('args', default='')
        self.log.info("ftrace tests...: %s" % self.args)
        self.run_cmd_out(self, "./ftracetest -l /tmp ./test.d/%s" % self.args)

        if self.failed_tests:
            self.fail("Failed Tests: %s" % self.failed_tests)
