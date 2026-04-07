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
# Author: Shirisha <shiganta@in..ibm.com>

import os
import platform
from avocado import Test
from avocado import skipIf
from avocado.utils import archive, linux_modules, linux
from avocado.utils import cpu, build, distro, process, genio
from avocado.utils.software_manager.manager import SoftwareManager

IS_POWER9 = 'power9' in cpu.get_family()


class PerfWatchPoint(Test):

    @skipIf(IS_POWER9, 'Watchpoint not supported on Power9')
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
            deps.extend(['perf', 'kernel-devel'])
        else:
            self.cancel("Install the package for perf supported \
                         by %s" % detected_distro.name)
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        if not linux.is_os_secureboot_enabled():
            self.cancel("Secure boot is enabled.")
        archive.extract(self.get_data("wptest-master.tar.gz"), self.workdir)
        self.build_dir = os.path.join(self.workdir, 'wptest-master')
        build.make(self.build_dir)
        os.chdir(self.build_dir)
        if os.path.exists('wptest.ko'):
            if not linux_modules.load_module("wptest"):
                process.run("insmod wptest.ko")

    def run_cmd(self):
        i = 1
        while i <= 4:
            lst = process.run("cat /dev/wptest")
            s = list(lst.stdout.decode('utf-8').strip().split(' '))
            val = ['10', '20']
            for result in s:
                if result not in val:
                    self.fail("wptest values are not correct")
            i = i+1

    def test_watch_point_check(self):
        if os.path.exists('/dev/wptest'):
            self.run_cmd()
            for line in genio.read_all_lines('/proc/kallsyms'):
                if 'arg1' in line:
                    value = line.split(' ')[0]
                    cmd = "perf record -e mem:0x%s &" % value
                    process.run(cmd, ignore_bg_processes=True,
                                ignore_status=True)
                    self.run_cmd()
        else:
            self.fail("unable to find the directory")

    def tearDown(self):
        process.system('pkill perf', ignore_status=True)
        if linux_modules.load_module("wptest"):
            process.run("rmmod wptest")
