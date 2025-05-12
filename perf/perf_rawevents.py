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
from avocado.utils import distro, process, genio, cpu, dmesg
from avocado.utils.software_manager.manager import SoftwareManager


class PerfRawevents(Test):

    """
    Tests raw events on different Power platforms along with
    named events
    :avocado: tags=perf,rawevents,events
    """
    # Initializing fail command list
    fail_cmd = list()

    def copy_files(self, filename):
        src = self.get_data(filename)
        if src is None or not os.path.isfile(src):
            self.cancel(f'File {filename} not found.')
        else:
            shutil.copyfile(src, os.path.join(self.teststmpdir, filename))

    def setUp(self):
        '''
        Install the basic packages to support perf
        '''

        # Check for basic utilities
        smm = SoftwareManager()
        detected_distro = distro.detect()
        self.distro_name = detected_distro.name
        self.rev = cpu.get_revision()
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

        # Equivalent Python code for bash command
        # "perf list --raw-dump pmu|grep pm_*"
        output = process.get_command_output_matching("perf list --raw-dump pmu", "pm_")
        if not output:
            self.cancel("No PMU events found. Skipping the test")

        revisions_to_test = ['004b', '004e', '0080', '0082']
        for rev in revisions_to_test:
            for filename in [f'name_events_{rev}', f'raw_codes_{rev}']:
                if rev == '0082':
                    # Use Power10 files for Power11
                    filename = filename.replace('0082', '0080')
                self.copy_files(filename)

        os.chdir(self.teststmpdir)
        # Clear the dmesg to capture the delta at the end of the test.
        dmesg.clear_dmesg()

    def run_event(self, filename, perf_flags):
        for line in genio.read_all_lines(filename):
            cmd = "%s%s sleep 1" % (perf_flags, line)
            result = process.run(cmd, shell=True, ignore_status=True)
            output = (result.stdout + result.stderr).decode()
            if result.exit_status != 0 or ("not counted" in output) or\
                    ("not supported" in output):
                self.fail_cmd.append(cmd)

    def error_check(self):
        if self.fail_cmd:
            for cmd in range(len(self.fail_cmd)):
                self.log.info("Failed command: %s", self.fail_cmd[cmd])
            self.fail("perf_raw_events: refer log file for failed events")

    def test_raw_code(self):
        file_name = 'raw_codes_' + (self.rev if self.rev != '0082' else '0080')
        perf_flags = "perf stat -e r"
        self.run_event(file_name, perf_flags)
        self.error_check()

    def test_name_event(self):
        file_name = 'name_events_' + (self.rev if self.rev != '0082' else '0080')
        perf_flags = "perf stat -e "
        self.run_event(file_name, perf_flags)
        self.error_check()

    def tearDown(self):
        # Collect the dmesg
        process.run("dmesg -T")
