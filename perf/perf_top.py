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

import sys
import time
import platform
import threading
import tempfile
import os
from avocado import Test
from avocado.utils import distro, dmesg, process, genio
from avocado.utils.software_manager.manager import SoftwareManager


class perf_top(Test):

    """
    Tests perf top and it's options with all
    possible flags with the help of yaml file
    :avocado: tags=perf,top
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
            deps.extend(['perf', 'python3-pexpect'])
        else:
            self.cancel("Install the package for perf supported \
                         by %s" % detected_distro.name)
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

        # Getting the parameters from yaml file
        self.option = self.params.get('option', default='')

        # Clear the dmesg by that we can capture delta at the end of the test
        dmesg.clear_dmesg()

        # Creating a temporary file
        self.temp_file = tempfile.NamedTemporaryFile().name

    def test_top(self):
        if self.option in ["-k", "--vmlinux", "--kallsyms"]:
            if self.distro_name in ['rhel', 'fedora', 'centos']:
                self.option = self.option + " /boot/vmlinuz-" + \
                        platform.uname()[2]
            elif self.distro_name in ['SuSE', 'Ubuntu']:
                self.option = self.option + " /boot/vmlinux-" + \
                        platform.uname()[2]

        cmd = f"perf top {self.option}"
        self.log.info(f"Running command: {cmd}")

        proc = process.SubProcess(cmd)
        proc.start()
        time.sleep(10)  # let perf top run for a short while

        # Try to stop gracefully (like pressing 'q')
        if proc.poll() is None:
            process.run(f"pkill -SIGINT -f '{cmd}'", ignore_status=True)
            time.sleep(1)

        proc.wait()

        # Check for dmesg errors
        dmesg.collect_errors_dmesg([
            'WARNING: CPU:', 'Oops', 'Segfault',
            'soft lockup', 'Unable to handle'
        ])

        # Check exit code and stderr for issues
        if proc.result.exit_status != 0:
            self.fail(f"perf top failed with option {self.option}: "
                      f"{proc.result.stderr.decode('utf-8', 'ignore')}")

        dmesg.collect_errors_dmesg(['WARNING: CPU:', 'Oops', 'Segfault',
                                    'soft lockup', 'Unable to handle'])

    def test_workload_output(self):
        process.getoutput("perf top -a > %s " % self.temp_file, timeout=10)
        perf_top_output = genio.read_file(self.temp_file).splitlines()
        flag = False
        for lines in perf_top_output:
            if "ebizzy" in lines:
                flag = True
                break
        if flag is False:
            self.fail("ebizzy workload not captured in perf top")

    def tearDown(self):
        if os.path.isfile(self.temp_file):
            process.system('rm -f %s' % self.temp_file)
