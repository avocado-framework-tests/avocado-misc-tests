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
# Author: Naveen kumar T <naveet89@in.ibm.com>

import os
import platform
import shutil
from avocado import Test
from avocado.utils import distro, process
from avocado.utils.software_manager import SoftwareManager


class PerfProbe(Test):

    def setUp(self):
        '''
        Install the basic packages to support perf and systemtap-sdt-devel
        '''
        # Check for basic utilities
        smm = SoftwareManager()
        detected_distro = distro.detect()
        self.distro_name = detected_distro.name
        deps = ['gcc']
        if 'Ubuntu' in self.distro_name:
            deps.extend(['linux-tools-common', 'linux-tools-%s' %
                         platform.uname()[2]])
        elif self.distro_name in ['rhel', 'SuSE']:
            deps.extend(['perf', 'systemtap-sdt-devel.ppc64le'])
        else:
            self.cancel("Install the package for perf supported\
                      by %s" % detected_distro.name)
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        shutil.copyfile(self.get_data('tick-dtrace.d'),
                        os.path.join(self.workdir, 'tick-dtrace.d'))
        shutil.copyfile(self.get_data('tick-main.c'),
                        os.path.join(self.workdir, 'tick-main.c'))
        os.chdir(self.workdir)
        process.run("dtrace -G -s tick-dtrace.d -o tick-dtrace.o")
        process.run("dtrace -h -s tick-dtrace.d -o tick-dtrace.h")
        process.run("gcc -c tick-main.c")
        process.run("gcc -o tick tick-main.o tick-dtrace.o")

    def test_probe(self):
        res = process.run("readelf -n tick")
        if 'NT_STAPSDT' not in res.stdout_text:
            self.fail("NT_STAPSDT not found in binary")
