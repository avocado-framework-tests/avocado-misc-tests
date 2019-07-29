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
import tempfile
from avocado import Test
from avocado import main
from avocado.utils import distro, process
from avocado.utils.software_manager import SoftwareManager


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
        elif self.distro_name in ['rhel', 'SuSE', 'fedora', 'centos']:
            deps.extend(['perf'])
        else:
            self.cancel("Install the package for perf supported \
                         by %s" % detected_distro.name)
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

        # Check for c2c is available in the system.
        output = process.run('perf mem record -e list')
        if 'ldlat-stores' in output.stderr or 'ldlat-loads' in output.stderr:
            self.log.info("perf c2c is available")
        else:
            self.cancel('perf c2c is not available')

        # Creating temporary file to collect the perf.data
        self.temp_file = tempfile.NamedTemporaryFile().name

        # Getting the parameters from yaml file
        self.record = self.params.get('record_method', default='')
        self.report = self.params.get('report_method', default='')

        # Clear the dmesg, by that we can capture the delta at the end of the test.
        process.run("dmesg -C", sudo=True)

    def verify_dmesg(self):
        self.whiteboard = process.system_output("dmesg")
        pattern = ['WARNING: CPU:', 'Oops',
                   'Segfault', 'soft lockup', 'Unable to handle']
        for fail_pattern in pattern:
            if fail_pattern in self.whiteboard:
                self.fail("Test Failed : %s in dmesg" % fail_pattern)

    def run_cmd(self, cmd):
        try:
            process.run(cmd, ignore_status=False, sudo=True)
        except process.CmdError as details:
            self.fail("Command %s failed: %s" % (cmd, details))

    def test_c2c(self):
        # When input is used for report, then need to pass the file argument
        # to the same file, record should log the data. So altering record,
        # report options to have the proper arguments.
        if self.report == "-i":
            self.report = "-i %s" % self.temp_file
            self.record = self.record + " -o %s" % self.temp_file
        elif self.report == "--input":
            self.report = "--input=%s" % self.temp_file
            self.record = self.record + " -o %s" % self.temp_file

        # Record command
        record_cmd = "perf c2c record %s -- ls" % self.record
        self.run_cmd(record_cmd)
        # Report command
        report_cmd = "perf c2c report %s" % self.report
        self.run_cmd(report_cmd)
        # Verify dmesg
        self.verify_dmesg()

    def tearDown(self):
        # Delete the temporary file
        if os.path.isfile(self.temp_file):
            process.run('rm -f %s' % self.temp_file)


if __name__ == "__main__":
    main()
