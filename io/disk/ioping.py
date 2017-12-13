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
from avocado import main
from avocado.utils import process, archive, build
from avocado.utils.software_manager import SoftwareManager


class Ioping(Test):

    """
    Disk I/O latency monitoring tool
    """

    def setUp(self):
        '''
        Build Ioping  Test
        '''

        # Check for basic utilities
        smm = SoftwareManager()

        self.count = self.params.get('count', default='2')
        self.mode = self.params.get('mode', default='-C')
        self.deadline = self.params.get('deadline', default='10')
        self.period = self.params.get('period', default='10')
        self.interval = self.params.get('interval', default='1s')
        self.size = self.params.get('size', default='4k')
        self.wsize = self.params.get('wsize', default='10m')
        self.disk = self.params.get('disk', default='/home')

        for package in ['gcc', 'make']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel(
                    "Fail to install %s required for this test." % package)
        tarball = self.fetch_asset('https://storage.googleapis.com/'
                                   'google-code-archive-downloads/v2/'
                                   'code.google.com/ioping/'
                                   'ioping-0.8.tar.gz', expire='0d')
        archive.extract(tarball, self.teststmpdir)
        version = os.path.basename(tarball.split('.tar.')[0])
        self.sourcedir = os.path.join(self.teststmpdir, version)

        build.make(self.sourcedir)

    def test(self):

        os.chdir(self.sourcedir)

        cmd = '%s -c %s -w %s -p %s -i %s -s %s -S %s %s' % (
            self.mode, self.count, self.deadline, self.period, self.interval,
            self.size, self.wsize, self.disk)

        if process.system('./ioping %s' % cmd, ignore_status=True, shell=True):
            self.fail("test run fails of  %s" % cmd)


if __name__ == "__main__":
    main()
