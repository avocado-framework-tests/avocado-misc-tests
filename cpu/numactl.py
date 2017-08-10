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
from avocado.utils import archive, build, process
from avocado.utils.software_manager import SoftwareManager


class Numactl(Test):

    """
    Self test case of numactl
    """

    def setUp(self):
        '''
        Build Stutter Test
        Source:
        https://github.com/numactl/numactl
        '''

        # Check for basic utilities
        smm = SoftwareManager()
        for package in ['gcc', 'numactl', 'autoconf', 'automake', 'make']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel("Failed to install %s, which is needed for"
                            "the test to be run" % package)

        locations = ["https://github.com/numactl/numactl/archive/master.zip"]
        tarball = self.fetch_asset("numactl.zip", locations=locations,
                                   expire='7d')
        archive.extract(tarball, self.srcdir)
        self.sourcedir = os.path.join(self.srcdir, 'numactl-master')

        os.chdir(self.sourcedir)
        process.run('./autogen.sh', shell=True)

        process.run('./configure', shell=True)

        build.make(self.sourcedir)

    def test(self):

        if build.make(self.sourcedir, extra_args='test', ignore_status=True):
            self.fail('test failed, Please check debug log')


if __name__ == "__main__":
    main()
