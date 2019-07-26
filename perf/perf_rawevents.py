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
from avocado import main
from avocado import skipUnless
from avocado.utils import cpu, distro, process, genio
from avocado.utils.software_manager import SoftwareManager

CPU_ARCH = cpu.get_cpu_arch().lower()
IS_POWER9 = 'power9' in CPU_ARCH
IS_POWER8 = 'power8' in CPU_ARCH


class PerfRawevents(Test):

    """
    Tests raw events on Power8 and Power9 along with
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
        if detected_distro.arch != 'ppc64le':
            self.cancel('This test is not supported on %s architecture'
                        % detected_distro.arch)
        deps = ['gcc', 'make']
        if 'Ubuntu' in self.distro_name:
            deps.extend(['linux-tools-common', 'linux-tools-%s' %
                         platform.uname()[2]])
        elif self.distro_name in ['rhel', 'SuSE', 'fedora', 'centos']:
            deps.extend(['perf'])
        else:
            self.cancel("Install the package for perf supported \
                         by %s" % detected_distro.name)
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

        for filename in ['name_events_p8', 'raw_codes_p8', 'raw_codes_p9']:
            self.copy_files(filename)

        os.chdir(self.teststmpdir)
        # Clear the dmesg, by that we can capture the delta at the end of the test.
        process.run("dmesg -c")

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
            self.fail("perf_raw_events: some of the events failed, refer to log")

    @skipUnless(IS_POWER8, 'Supported only on Power8')
    def test_raw_events_power8(self):
        self.run_event('raw_codes_p8', 'raw')
        self.error_check()

    @skipUnless(IS_POWER8, 'Supported only on Power8')
    def test_name_events_power8(self):
        self.run_event('name_events_p8', 'name')
        self.error_check()

    @skipUnless(IS_POWER9, 'Supported only on Power9')
    def test_raw_events_power9(self):
        self.run_event('raw_codes_p9', 'raw')
        self.error_check()

    def tearDown(self):
        # Collect the dmesg
        process.run("dmesg -T")


if __name__ == "__main__":
    main()
