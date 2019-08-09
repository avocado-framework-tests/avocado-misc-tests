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
# Copyright: 2018 IBM
# Author:Praveen K Pandey <praveen@linux.vnet.ibm.com>
#


import os

from avocado import Test
from avocado import main
from avocado.utils import process, archive, build
from avocado.utils.software_manager import SoftwareManager


class Pjdfstest(Test):

    """
    pjdfstest: pjdfstest is a test suite that helps
    exercise POSIX system calls
    """

    def setUp(self):
        '''
        Build pjdfstest
        Source:
        https://github.com/pjd/pjdfstest
        '''

        # Check for basic utilities
        smm = SoftwareManager()

        for package in ['autoconf', 'automake', 'gcc', 'make', 'perl', 'openssl']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        locations = ['https://github.com/pjd/pjdfstest/archive/master.zip']

        tarball = self.fetch_asset(
            "pjdfstest.zip", locations=locations, expire='7d')
        archive.extract(tarball, self.workdir)
        self.build_dir = os.path.join(self.workdir, 'pjdfstest-master')
        os.chdir(self.build_dir)
        process.run('autoreconf -ifs ', shell=True)
        process.run('./configure ', shell=True)

        build.make(self.build_dir, extra_args='pjdfstest')

    def test(self):

        os.chdir(self.build_dir)
        try:
            for string in process.run('prove -rv tests',
                                      ignore_status=False,
                                      sudo=True).stderr.splitlines():
                if 'FAIL' in str(string.splitlines()):
                    self.log.info("Test case failed is %s"
                                  % str(string.splitlines()))
        except process.CmdError as details:
            self.fail("failed: %s" % details)


if __name__ == "__main__":
    main()
