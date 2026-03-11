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

import os
from avocado import Test
from avocado.utils import archive, build, process
from avocado.utils.software_manager.distro_packages import ensure_tool


class Perf_crashevent(Test):

    """
    This series of test is meant to kernel against known issues,
    which might crash the unpatched kernels.
    :avocado: tags=destructive,perf
    """

    @staticmethod
    def run_cmd_out(cmd):
        return process.system_output(cmd, shell=True, ignore_status=True,
                                     sudo=True).decode("utf-8")

    def setUp(self):
        '''
        Install the packages
        '''
        # Check for basic utilities
        perf_path = self.params.get('perf_bin', default='')
        distro_pkg_map = {
            "Ubuntu": [f"linux-tools-{os.uname()[2]}", "linux-tools-common", "gcc", "make"],
            "debian": ["linux-perf", "gcc", "make"],
            "centos": ["perf", "gcc", "make", "gcc-c++"],
            "fedora": ["perf", "gcc", "make", "gcc-c++"],
            "rhel": ["perf", "gcc", "make", "gcc-c++"],
            "SuSE": ["perf", "gcc", "make", "gcc-c++"],
        }
        try:
            perf_version = ensure_tool("perf", custom_path=perf_path, distro_pkg_map=distro_pkg_map)
            self.log.info(f"Perf version: {perf_version}")
            self.perf_bin = perf_path if perf_path else "perf"
        except RuntimeError as e:
            self.cancel(str(e))

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
        if build.make(self.sourcedir, extra_args="-s -S"):
            self.fail("Building perf even test suite failed")

    def execute_perf_test(self):
        self.run_cmd_out("sync")
        self.run_cmd_out("sync")
        self.run_cmd_out("sleep 180")
        os.chdir(self.sourcedir)
        self.run_cmd_out("echo -1 >/proc/sys/kernel/perf_event_paranoid")
        if "-1" not in self.run_cmd_out("cat /proc/sys/kernel/"
                                        "perf_event_paranoid"):
            self.error("Unable to set perf_event_paranoid to -1 ")
        self.run_cmd_out("./run_crash_tests.sh")

    def test(self):
        '''
        Execute the perf crash tests
        '''
        self.build_perf_test()
        self.execute_perf_test()
