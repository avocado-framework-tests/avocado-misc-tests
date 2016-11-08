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
# Copyright: 2016 IBM
# Author:Praveen K Pandey <praveen@linux.vnet.ibm.com>
#


import os

from avocado import Test
from avocado import main
from avocado.utils import archive, build
from avocado.utils.software_manager import SoftwareManager


class Perftool(Test):

    """
    perftool-testsuite
    """

    def setUp(self):
        '''
        Build perftool Test
        Source:
        https://github.com/rfmvh/perftool-testsuite
        '''

        # Check for basic utilities
        smm = SoftwareManager()
        for package in ['gcc', 'make', 'perf']:
            if not smm.check_installed(package) and not smm.install(package):
                self.error('%s is needed for the test to be run' % package)

        locations = ["https://github.com/rfmvh/perftool-testsuite/archive/"
                     "master.zip"]
        tarball = self.fetch_asset("perftool.zip", locations=locations,
                                   expire='7d')
        archive.extract(tarball, self.srcdir)
        self.srcdir = os.path.join(self.srcdir, 'perftool-testsuite-master')

    def test(self):
        self.count = 0
        for line in build.run_make(self.srcdir, extra_args='check',
                                   ignore_status=True).stdout.splitlines():
            if '-- [ FAIL ] --' in line:
                self.count += 1
                self.log.info(line)

        if self.count > 0:
            self.fail("%s Test failed" % self.count)


if __name__ == "__main__":
    main()
