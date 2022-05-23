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
from avocado.utils import distro, process, genio
from avocado.utils.software_manager.manager import SoftwareManager


class perf_hv_gpci(Test):

    """
    Tests hv_gpci events
    :avocado: tags=perf,hv_gpci,events
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
        self.distro_name = detected_distro.name

        if 'ppc64' not in detected_distro.arch:
            self.cancel('This test is not supported on %s architecture'
                        % detected_distro.arch)
        if 'PowerNV' in genio.read_file('/proc/cpuinfo'):
            self.cancel('This test is only supported on LPAR')

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

        # Collect all hv_gpci events
        self.list_of_hv_gpci_events = []
        for line in process.get_command_output_matching('perf list', 'hv_gpci'):
            line = line.split(',')[0].split('/')[1]
            self.list_of_hv_gpci_events.append(line)

        # Clear the dmesg, by that we can capture the delta at the end of
        # the test.
        process.run("dmesg -c")

    def error_check(self):
        if len(self.fail_cmd) > 0:
            for cmd in range(len(self.fail_cmd)):
                self.log.info("Failed command: %s" % self.fail_cmd[cmd])
            self.fail("perf_raw_events: some of the events failed,"
                      "refer to log")

    def run_cmd(self, cmd):
        output = process.run(cmd, shell=True, ignore_status=True)
        if output.exit_status != 0:
            self.fail_cmd.append(cmd)

    def test_gpci_events(self):
        perf_stat = "perf stat"
        perf_flags = '-C 1 -v -e'

        for line in self.list_of_hv_gpci_events:
            evt = "hv_gpci/%s,hw_chip_id=12/" % line
            cmd = "%s %s %s sleep 1" % (perf_stat, perf_flags, evt)
            self.run_cmd(cmd)
            cmd = "%s --per-core -a -e %s sleep 1" % (perf_stat, evt)
            self.run_cmd(cmd)
            cmd = "%s --per-socket -a -e %s sleep 1" % (perf_stat, evt)
            self.run_cmd(cmd)

        self.error_check()

    def tearDown(self):
        # Collect the dmesg
        process.run("dmesg -T")
