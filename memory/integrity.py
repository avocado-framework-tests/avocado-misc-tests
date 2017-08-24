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
# Author:Santhosh G <santhog4@linux.vnet.ibm.com>
#


import os

from avocado import Test
from avocado import main
from avocado.utils import process, archive, build
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import distro


class Integrity(Test):
    """
    Performs Memory Integrity Tests

    :avocado: tags=memory,privileged
    """

    def setUp(self):
        '''
        Build Integrity Test
        '''

        # Check for basic utilities
        smm = SoftwareManager()
        detected_distro = distro.detect()
        deps = ['gcc', 'make']
        if detected_distro.name == "Ubuntu":
            deps += ['libnuma-dev']
        else:
            deps += ['libnuma-devel']
        for packages in deps:
            if not smm.check_installed(packages) and not smm.install(packages):
                self.error(packages + ' is needed for the test to be run')

        tarball = os.path.join(self.datadir, "Integritytests.tar")
        archive.extract(tarball, self.srcdir)
        self.srcdir = os.path.join(self.srcdir, 'Integritytests')
        build.make(self.srcdir)

    def test(self):
        '''
        Execute Integrity tests
        '''
        os.chdir(self.srcdir)
        for i in range(1, 4):
            if process.system('./mem_integrity_test -s ' + str(i), shell=True,
                              ignore_status=True) != 0:
                self.fail("Test failed")


if __name__ == "__main__":
    main()
