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
# Copyright: 2024 IBM
# Author: Shaik Abdulla <abdulla1@linux.vnet.ibm.com>

import os
import platform
from avocado import Test
from avocado.utils import distro, process, dmesg
from avocado.utils.software_manager.manager import SoftwareManager


class perf_lock(Test):

    """
    Tests perf lock and it's options namely record, report, info, script
    contention with all possible flags with the help of yaml file
    :avocado: tags=perf
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
        if self.distro_name in ['rhel', 'SuSE', 'fedora', 'centos']:
            deps.extend(['perf'])
        else:
            self.cancel("Install the package for perf supported \
                         by %s" % detected_distro.name)
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

        # output file to capture perf events
        self.output_file = "perf.data"

        # Check perf lock is available in the system.
        output = process.getoutput('perf list', shell=True)
        if 'lock:contention_begin' in output or \
           'lock:contention_end' in output:
            self.log.info("perf lock is available")
        else:
            self.cancel('perf lock is not available')

        # Getting the parameters from yaml file
        self.report = self.params.get('name', default='report')
        self.option = self.params.get('option', default='')

        # Clear the dmesg, by that we can capture the delta at
        # the end of the test.
        dmesg.clear_dmesg()

    def run_cmd(self, cmd):
        try:
            process.run(cmd, ignore_status=False, sudo=True)
        except process.CmdError as details:
            self.fail("Command %s failed: %s" % (cmd, details))

    def test_lock(self):
        """
        'perf lock record' records lock events and this command produces the
        file "perf.data" which contains tracing results of lock events. The
        perf.data file is then used as input for report and other commands.
        """
        # test perf lock with normal user
        if self.report == 'normal_user_test':
            # create temporary user
            if process.system('useradd test', sudo=True, ignore_status=True):
                self.log.warn('test useradd failed')
            cmd = 'perf lock record -o %s -a -v sleep 3' % self.output_file
            if not process.system('id test', ignore_status=True):
                if not process.system("su -c '%s' test" % cmd, shell=True,
                                      ignore_status=True):
                    self.fail("normal user has access to run perf lock")
                process.system('userdel -f test', sudo=True)
            else:
                self.log.warn('User test does not exist, skipping test')
        else:
            # Record command
            record_cmd = "perf lock record -o %s -- " \
                         "perf bench sched messaging" % self.output_file
            self.run_cmd(record_cmd)
            # Report command
            if "-i" in self.option:
                self.option += " " + self.output_file
            if "--vmlinux" in self.option or "--kallsyms" in self.option:
                if self.distro_name in ['rhel', 'fedora', 'centos']:
                    self.option += " /boot/vmlinuz-" + platform.uname()[2]
                elif self.distro_name in ['SuSE', 'Ubuntu']:
                    self.option += " /boot/vmlinux-" + platform.uname()[2]
            report_cmd = "perf lock %s %s" % (self.report, self.option)
            # Validate the output of perf lock record
            if os.path.exists(self.output_file):
                if not os.stat(self.output_file).st_size:
                    self.fail("%s sample not captured" % self.output_file)
                else:
                    self.run_cmd(report_cmd)

        # Verify dmesg
        dmesg.collect_errors_dmesg(['WARNING: CPU:', 'Oops', 'Segfault',
                                    'soft lockup', 'Unable to handle'])

    def tearDown(self):
        # Delete the perf.data file
        if os.path.isfile(self.output_file):
            process.run('rm -f %s' % self.output_file)
