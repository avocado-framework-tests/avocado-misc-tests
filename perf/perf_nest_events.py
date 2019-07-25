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

import platform
from avocado import Test
from avocado import main
from avocado.utils import cpu, distro, genio, process
from avocado.utils.software_manager import SoftwareManager


class nestEvents(Test):

    """
    Tests nest events
    Collects all the available events from 'perf list' and
    executes them using 'perf stat' command
    :avocado: tags=perf,nest,events
    """
    # Initializing fail command list
    fail_cmd = list()

    def setUp(self):
        '''
        Install the basic packages to support perf
        '''

        # Check for basic utilities
        smm = SoftwareManager()
        detected_distro = distro.detect()
        distro_name = detected_distro.name

        if detected_distro.arch != 'ppc64le':
            self.cancel('This test is not supported on %s architecture'
                        % detected_distro.arch)

        if cpu.get_cpu_arch().lower() == 'power8':
            self.cancel('This test not applies to Power8')

        if 'PowerNV' not in genio.read_file('/proc/cpuinfo').rstrip('\t\r\n\0'):
            self.cancel('This test applies only to PowerNV')

        deps = ['gcc', 'make']
        if 'Ubuntu' in distro_name:
            deps.extend(['linux-tools-common', 'linux-tools-%s' %
                         platform.uname()[2]])
        elif distro_name in ['rhel', 'SuSE', 'fedora', 'centos']:
            deps.extend(['perf'])
        else:
            self.cancel("Install the package for perf supported \
                         by %s" % detected_distro.name)
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

        # Collect nest events
        self.list_of_nest_events = []
        for line in process.get_perf_events('nest_'):
            line = line.split(' ')[2]
            if 'pm_nest' in line:
                continue
            self.list_of_nest_events.append(line)

        # Clear the dmesg, by that we can capture the delta at the end of the test.
        process.run("dmesg -c", sudo=True)

    def error_check(self):
        if len(self.fail_cmd) > 0:
            for cmd in range(len(self.fail_cmd)):
                self.log.info("Failed command: %s" % self.fail_cmd[cmd])
            self.fail("perf_raw_events: some of the events failed, refer to log")

    def run_cmd(self, cmd):
        if process.system(cmd, shell=True, ignore_status=True):
            self.fail_cmd.append(cmd)

    def test_nest_events(self):
        perf_stat = "perf stat -e"
        perf_flags = '-a -A sleep 1'

        for line in self.list_of_nest_events:
            cmd = "%s %s %s" % (perf_stat, line, perf_flags)
            self.run_cmd(cmd)

        self.error_check()

    def tearDown(self):
        # Collect the dmesg
        process.run("dmesg -T")


if __name__ == "__main__":
    main()
