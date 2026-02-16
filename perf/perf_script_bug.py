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
# Copyright: 2019 IBM
# Author: Shirisha <shiganta@in.ibm.com>

import os
import tempfile
import shutil
import configparser
from avocado import Test
from avocado.utils import build, process, distro
from avocado.utils.software_manager.distro_packages import ensure_tool


class PerfScript(Test):

    def setUp(self):
        '''
        Install the basic packages to support PerfProbe test
        '''
        # Check for basic utilities
        perf_path = self.params.get('perf_bin', default='')
        parser = configparser.ConfigParser()
        parser.read(self.get_data('probe.cfg'))
        # self.perf_probe = parser.get(detected_distro.name, 'probepoint')
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
        dist_name = distro.detect().name
        if parser.has_section(dist_name):
            self.perf_probe = parser.get(dist_name, 'probepoint')
        else:
            self.perf_probe = parser.get('Ubuntu', 'probepoint')
        shutil.copyfile(self.get_data('perf_test.c'),
                        os.path.join(self.teststmpdir, 'perf_test.c'))
        shutil.copyfile(self.get_data('Makefile'),
                        os.path.join(self.teststmpdir, 'Makefile'))
        build.make(self.teststmpdir)
        os.chdir(self.teststmpdir)

    def test_script_probe(self):
        # Creating temporary file to collect the perf.data
        self.temp_file = tempfile.NamedTemporaryFile().name
        probe = "perf probe -x perf_test 'perf_test.c:%s'" % self.perf_probe
        process.run(probe, sudo=True, shell=True)
        record = "perf record -e \'{cpu/cpu-cycles,period=10000/,probe_perf_test:main}:S\' -o %s ./perf_test" % self.temp_file
        process.run(record, sudo=True, shell=True)
        output = process.run("perf script -i %s" % self.temp_file,
                             ignore_status=True, sudo=True, shell=True)
        probe_del = "perf probe -d probe_perf_test:main"
        process.run(probe_del)
        if output.exit_status == -11:
            self.fail("perf script command segfaulted")
