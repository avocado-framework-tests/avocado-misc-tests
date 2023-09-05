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
from avocado import Test
from avocado.utils import distro, process, dmesg
from avocado.utils.software_manager.manager import SoftwareManager


class perf_c2c(Test):

    """
    Tests perf c2c and it's options namely
    record, report with all possible flags with
    the help of yaml file
    :avocado: tags=perf,c2c
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
        elif 'debian' in detected_distro.name:
            deps.extend(['linux-perf'])
        elif self.distro_name in ['rhel', 'SuSE', 'fedora', 'centos']:
            deps.extend(['perf'])
        else:
            self.cancel("Install the package for perf supported \
                         by %s" % detected_distro.name)
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

        # Check for c2c is available in the system.
        output = process.run('perf mem record -e list').stderr.decode("utf-8")
        if 'ldlat-stores' in output or 'ldlat-loads' in output:
            self.log.info("perf c2c is available")
        else:
            self.cancel('perf c2c is not available')

        # Getting the parameters from yaml file
        self.record = self.params.get('record_method', default='')
        self.report = self.params.get('report_method', default='')

        # Clear the dmesg, by that we can capture the delta at the end of the
        # test.
        dmesg.clear_dmesg()

    def run_cmd(self, cmd):
        try:
            process.run(cmd, ignore_status=False, sudo=True)
        except process.CmdError as details:
            self.fail("Command %s failed: %s" % (cmd, details))

    def test_c2c(self):
        # When input is used for report, then need to pass the file argument
        # to the same file, record should log the data. So altering record,
        # report options to have the proper arguments.
        output_file = "perf.data"
        if self.report == "-i":
            self.report = "-i %s" % output_file
        elif self.report == "--input":
            self.report = "--input=%s" % output_file
        elif self.report in ['-k', '--vmlinux']:
            if self.distro_name in ['rhel', 'fedora', 'centos']:
                self.report = self.report + \
                    " /boot/vmlinuz-" + platform.uname()[2]
            elif self.distro_name in ['SuSE', 'Ubuntu']:
                self.report = self.report + \
                    " /boot/vmlinux-" + platform.uname()[2]

        # Record command
        record_cmd = "perf c2c record -o %s %s -- ls" % (
            output_file, self.record)
        self.run_cmd(record_cmd)
        # Report command
        report_cmd = "perf c2c report %s" % self.report
        # Validate the output of perf c2c
        if os.path.exists(output_file):
            if not os.stat(output_file).st_size:
                self.fail("%s sample not captured" % output_file)
            else:
                self.run_cmd(report_cmd)
        # Verify dmesg
        dmesg.collect_errors_dmesg(['WARNING: CPU:', 'Oops', 'Segfault',
                                    'soft lockup', 'Unable to handle'])

    def tearDown(self):
        # Delete the temporary file
        if os.path.isfile("perf.data"):
            process.run('rm -f perf.data')
        if os.path.isfile("perf.data.old"):
            process.run('rm -f perf.data.old')
