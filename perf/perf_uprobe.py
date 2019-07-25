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
# Author: Nageswara R Sastry <rnsastry@linux.vnet.ibm.com>

import os
import platform
import shutil
import tempfile
from avocado import Test
from avocado import main
from avocado.utils import build, distro, process, genio
from avocado.utils.software_manager import SoftwareManager


class perfUprobe(Test):

    """
    Uprobe related test cases run through perf commands
    with the help a 'c' program.
    :avocado: tags=perf,uprobe,probe
    """

    def setUp(self):
        '''
        Install the basic packages to support perf
        '''

        # Check for basic utilities
        smm = SoftwareManager()
        detected_distro = distro.detect()
        self.distro_name = detected_distro.name
        deps = ['gcc', 'make']
        if 'Ubuntu' in self.distro_name:
            deps.extend(['linux-tools-common', 'linux-tools-%s' %
                         platform.uname()[2]])
        elif self.distro_name in ['rhel', 'SuSE', 'fedora', 'centos']:
            deps.extend(['perf'])
        else:
            self.cancel("Install the package for perf supported\
                      by %s" % detected_distro.name)
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

        shutil.copyfile(self.get_data('uprobe.c'),
                        os.path.join(self.teststmpdir, 'uprobe.c'))

        shutil.copyfile(self.get_data('Makefile'),
                        os.path.join(self.teststmpdir, 'Makefile'))

        build.make(self.teststmpdir)
        os.chdir(self.teststmpdir)
        self.temp_file = tempfile.NamedTemporaryFile().name
        self.cmdProbe = "perf probe -x"
        self.recProbe = "perf record -o %s -e probe_uprobe_test:doit" % self.temp_file
        self.report = "perf report --input=%s" % self.temp_file

    def cmd_verify(self, cmd):
        return process.run(cmd, shell=True)

    def test_uprobe(self):
        output = self.cmd_verify('%s /usr/bin/perf main' % self.cmdProbe)
        if 'Added new event' not in output.stderr:
            self.fail("perf: probe of perf main failed")
        output = self.cmd_verify('perf probe -l')
        if 'probe_perf:main' not in output.stdout:
            self.fail("perf: probe of 'perf main' not found in list")
        sysfsfile = '/sys/kernel/debug/tracing/uprobe_events'
        if 'probe_perf' not in genio.read_file(
                               '/sys/kernel/debug/tracing/uprobe_events'
                               ).rstrip('\t\r\n\0'):
            self.fail("perf: sysfs file didn't reflect uprobe events")
        output = self.cmd_verify('perf record -o %s -e probe_perf:main -- '
                                 'perf list' % self.temp_file)
        if 'samples' not in output.stderr:
            self.fail("perf: perf.data file not created")
        output = self.cmd_verify(self.report)

    def test_uprobe_return(self):
        output = self.cmd_verify('%s ./uprobe_test doit%%return'
                                 % self.cmdProbe)
        if 'Added new event' not in output.stderr:
            self.fail("perf: probe of uprobe return failed")
        # RHEL
        if self.distro_name == "rhel":
            output = self.cmd_verify('%s__return -- ./uprobe_test'
                                     % self.recProbe)
        else:
            output = self.cmd_verify('%s -aR ./uprobe_test' % self.recProbe)
        if 'samples' not in output.stderr:
            self.fail("perf: perf.data file not created")
        output = self.cmd_verify(self.report)

    def test_uprobe_variable(self):
        output = self.cmd_verify('%s ./uprobe_test "doit i"' % self.cmdProbe)
        if 'Added new event' not in output.stderr:
            self.fail("perf: probe of uprobe variable failed")
        if self.distro_name == "rhel":
            output = self.cmd_verify('%s -- ./uprobe_test' % self.recProbe)
        else:
            output = self.cmd_verify('%s -aR ./uprobe_test' % self.recProbe)
        if 'samples' not in output.stderr:
            self.fail("perf: perf.data file not created")
        output = self.cmd_verify(self.report)

    def tearDown(self):
        output = self.cmd_verify('perf probe -d \\*')
        if os.path.isfile(self.temp_file):
            process.run('rm -f %s' % self.temp_file)


if __name__ == "__main__":
    main()
