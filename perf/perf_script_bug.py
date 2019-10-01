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
from avocado import Test
from avocado import main
from avocado.utils import build, distro, process
from avocado.utils.software_manager import SoftwareManager


class PerfProbe(Test):

    def setUp(self):
        '''
        Install the basic packages to support PerfProbe test
        '''
        # Check for basic utilities
        smm = SoftwareManager()
        detected_distro = distro.detect()
        self.distro_name = detected_distro.name
        deps = ['gcc', 'make']
        if self.distro_name in ['rhel', 'SuSE']:
            deps.extend(['perf'])
        else:
            self.cancel("Install the package perf\
                      for %s" % detected_distro.name)
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

        shutil.copyfile(self.get_data('perf_test.c'),
                        os.path.join(self.teststmpdir, 'perf_test.c'))
        shutil.copyfile(self.get_data('Makefile'),
                        os.path.join(self.teststmpdir, 'Makefile'))
        build.make(self.teststmpdir)
        os.chdir(self.teststmpdir)

    def test_probe(self):
        # Creating temporary file to collect the perf.data
        self.temp_file = tempfile.NamedTemporaryFile().name
        probe = "perf probe -x perf_test 'perf_test.c:4'"
        output = process.run(probe, sudo=True, shell=True)
        record = "perf record -e \'{cpu/cpu-cycles,period=10000/,probe_perf_test:main}:S\' -o %s ./perf_test" % self.temp_file
        output = process.run(record, sudo=True, shell=True)
        output = process.run("perf script -i %s" % self.temp_file, ignore_status=True, sudo=True, shell=True)
        probe_del = "perf probe -d probe_perf_test:main"
        process.run(probe_del)
        if output.exit_status == -11:
            self.fail("perf script command segfaulted")


if __name__ == "__main__":
    main()
