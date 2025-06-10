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
from avocado.utils import process, build, archive, dmesg
from avocado.utils.software_manager.manager import SoftwareManager


class Flail(Test):
    '''
    Flail is system call fuzzer

    :avocado: tags=fs
    '''

    def setUp(self):
        '''
        Setup Flail
        '''
        smm = SoftwareManager()
        for package in ['gcc', 'make']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel(package + ' is needed for the test to be run')
        self.args = self.params.get('args', default='')

        archive.extract(self.get_data("flail-0.2.0.tar.gz"), self.workdir)
        self.build_dir = os.path.join(self.workdir, 'flail-0.2.0')
        os.chdir(self.build_dir)
        build.make(self.build_dir)

    def test(self):
        '''
        Runs flail with the appropriate parameters.

        :param fstype: Filesystem type there user want to run flail
        '''
        dmesg.clear_dmesg()
        os.chdir(self.build_dir)
        process.system('./flail %s' % self.args, ignore_status=True)
        dmesg1 = process.system_output('dmesg')
        match = re.search(br'Call Trace:', dmesg1, re.M | re.I)
        if match:
            self.fail("some call traces seen please check")
