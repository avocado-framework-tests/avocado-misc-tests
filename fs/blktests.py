#!/usr/bin/env python
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
# Copyright: 2018 IBM
# Author: Praveen K Pandey <praveen@linux.vnet.ibm.com>
#

import os
import re

from avocado import Test
from avocado.utils import process, build, archive, genio, distro
from avocado.utils.software_manager.manager import SoftwareManager


class Blktests(Test):
    '''
    Blktests blktests is a test framework for the Linux kernel block layer
    and storage stack. It is inspired by the xfstests filesystem testing framework.

    :avocado: tags=fs
    '''

    def setUp(self):
        '''
        Setup Blktests
        '''
        self.disk = self.params.get('disk', default='')
        self.dev_type = self.params.get('type', default='')
        smm = SoftwareManager()
        dist = distro.detect()
        if dist.name in ['Ubuntu', 'debian']:
            packages = ['gcc', 'make', 'util-linux', 'fio', 'libdevmapper-dev', 'g++']
        else:
            packages = ['gcc', 'make', 'util-linux', 'fio', 'device-mapper', 'gcc-c++']

        for package in packages:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel(package + ' is needed for the test to be run')

        locations = ["https://github.com/osandov/blktests/archive/"
                     "master.zip"]
        tarball = self.fetch_asset("blktests.zip", locations=locations,
                                   expire='7d')
        archive.extract(tarball, self.workdir)
        self.sourcedir = os.path.join(self.workdir, 'blktests-master')

        build.make(self.sourcedir)

    def test(self):

        self.clear_dmesg()
        os.chdir(self.sourcedir)

        genio.write_one_line("/proc/sys/kernel/hung_task_timeout_secs", "0")
        if self.disk:
            os.environ['TEST_DEVS'] = self.disk
        cmd = './check %s' % self.dev_type
        result = process.run(cmd, ignore_status=True, verbose=True)
        if result.exit_status != 0:
            self.fail("test failed")
        dmesg = process.system_output('dmesg')
        match = re.search(br'Call Trace:', dmesg, re.M | re.I)
        if match:
            self.fail("some call traces seen please check")

    def clear_dmesg(self):
        process.run("dmesg -c ", sudo=True)
