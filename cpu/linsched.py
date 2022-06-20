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
# Copyright: 2017 IBM
# Author:Praveen K Pandey <praveen@linux.vnet.ibm.com>
#


import os

from avocado import Test
from avocado.utils import process, archive, build
from avocado.utils.software_manager.manager import SoftwareManager


class Linsched(Test):

    """
    linux-scheduler-testing Testsuite

    :avocado: tags=cpu
    """

    def setUp(self):
        '''
        Build linsched  Test
        Source:
        https://github.com/thejinxters/linux-scheduler-testing
        '''

        # Check for basic utilities
        smm = SoftwareManager()
        for package in ['gcc', 'make', 'patch']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel(
                    "Fail to install %s required for this test." % package)
        self.args = self.params.get('args', default='pi 100')
        url = "https://github.com/thejinxters/linux-scheduler-testing/" \
              "archive/refs/heads/master.zip"
        tarball = self.fetch_asset("linsched.zip", locations=url, expire='7d')
        archive.extract(tarball, self.workdir)
        self.sourcedir = os.path.join(self.workdir, 'linux-scheduler-testing-master')

        os.chdir(self.sourcedir)
        fix_patch = 'patch -p1 < %s' % self.get_data('fix.patch')
        process.run(fix_patch, shell=True, ignore_status=True)

        build.make(self.sourcedir)

    def test(self):

        os.chdir(self.sourcedir)

        if process.system('./%s' % self.args, ignore_status=True, shell=True):
            self.fail('Test [%s] failed.' % self.args)
