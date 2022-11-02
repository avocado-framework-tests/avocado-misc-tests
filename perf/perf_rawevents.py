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
from avocado import Test
from avocado.utils import cpu, distro, process, genio
from avocado.utils.software_manager.manager import SoftwareManager


class PerfRawevents(Test):

    """
    Tests raw events on Power8, Power9 and Power10 along with
    named events
    :avocado: tags=perf,rawevents,events
    """
    # Initializing fail command list
    fail_cmd = list()

    def copy_files(self, filename):
        shutil.copyfile(self.get_data(filename),
                        os.path.join(self.teststmpdir, filename))

    def setUp(self):
        '''
        Install the basic packages to support perf
        '''

        # Check for basic utilities
        smm = SoftwareManager()
        detected_distro = distro.detect()
        self.distro_name = detected_distro.name
        processor = genio.read_file("/proc/cpuinfo")
        for line in processor.splitlines():
            if 'revision' in line:
                self.rev = (line.split(':')[1].strip())
        if detected_distro.arch != 'ppc64le':
            self.cancel('This test is not supported on %s architecture'
                        % detected_distro.arch)
        deps = ['gcc', 'make']
        if self.distro_name in ['Ubuntu']:
            deps.extend(['linux-tools-common', 'linux-tools-%s' %
                         platform.uname()[2]])
        elif self.distro_name in ['debian']:
            deps.extend(['linux-tools-%s' % platform.uname()[2][3]])
        elif self.distro_name in ['rhel', 'SuSE', 'fedora', 'centos']:
            deps.extend(['perf'])
        else:
            self.cancel("Install the package for perf supported \
                         by %s" % detected_distro.name)
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

        for filename in ['name_events_p8', 'raw_codes_p8', 'name_events_p9',
                         'raw_codes_p9', 'name_events_p10', 'raw_codes_p10']:
            self.copy_files(filename)

        os.chdir(self.teststmpdir)
        # Clear the dmesg to capture the delta at the end of the test.
        process.run("dmesg -C")

    def run_event(self, filename, eventname):
        if eventname == 'raw':
            perf_flags = "perf stat -e r"
        elif eventname == 'name':
            perf_flags = "perf stat -e "
        for line in genio.read_all_lines(filename):
            cmd = "%s%s sleep 1" % (perf_flags, line)
            output = process.run(cmd, shell=True,
                                 ignore_status=True)
            if output.exit_status != 0:
                self.fail_cmd.append(cmd)

    def error_check(self):
        if self.fail_cmd:
            for cmd in range(len(self.fail_cmd)):
                self.log.info("Failed command: %s", self.fail_cmd[cmd])
            self.fail("perf_raw_events: refer log file for failed events")

    def test(self):
        if '004b' in self.rev:
            self.run_event('raw_codes_p8', 'raw')
            self.error_check()
            self.run_event('name_events_p8', 'name')
            self.error_check()
        if '004e' in self.rev:
            self.run_event('raw_codes_p9', 'raw')
            self.error_check()
            self.run_event('name_events_p9', 'name')
            self.error_check()
        if '0080' in self.rev:
            self.run_event('raw_codes_p10', 'raw')
            self.error_check()
            self.run_event('name_events_p10', 'name')
            self.error_check()
        else:
            self.cancel('This test is not supported on %s' % cpu_family)

    def tearDown(self):
        # Collect the dmesg
        process.run("dmesg -T")
