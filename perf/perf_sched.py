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
# Copyright: 2022 IBM
# Author: Disha Goel <disgoel@linux.vnet.ibm.com>

import os
import platform
import tempfile
from avocado import Test
from avocado.utils import distro, process, dmesg
from avocado.utils.software_manager.manager import SoftwareManager


class perf_sched(Test):

    """
    Tests perf sched and it's options with all
    possible flags with the help of yaml file
    :avocado: tags=perf,sched
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

        # Creating temporary file to collect the perf.data
        self.temp_file = tempfile.NamedTemporaryFile().name

        # Getting the parameters from yaml file
        self.optname = self.params.get('name', default='')
        self.option = self.params.get('option', default='')

        # Clear the dmesg by that we can capture delta at the end of the test
        dmesg.clear_dmesg()

    def run_cmd(self, cmd):
        try:
            process.run(cmd, ignore_status=False, sudo=True)
        except process.CmdError as details:
            self.fail("Command %s failed: %s" % (cmd, details))

    def test_sched(self):
        if self.optname == "timehist":
            if self.option in ["-k", "--vmlinux", "--kallsyms"]:
                if 'rhel' in self.distro_name:
                    self.option = self.option + " /boot/vmlinuz-" + platform.uname()[2]
                elif 'SuSE' in self.distro_name:
                    self.option = self.option + " /boot/vmlinux-" + platform.uname()[2]

        record_cmd = "perf sched record -o %s ls" % self.temp_file
        self.run_cmd(record_cmd)
        report_cmd = "perf sched -i %s %s %s" % (self.temp_file, self.optname,
                                                 self.option)
        self.run_cmd(report_cmd)
        dmesg.collect_errors_dmesg(['WARNING: CPU:', 'Oops', 'Segfault',
                                    'soft lockup', 'Unable to handle'])

    def tearDown(self):
        # Delete the temporary file
        if os.path.isfile(self.temp_file):
            process.run('rm -f %s' % self.temp_file)
