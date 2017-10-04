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
            deps.extend(['libnuma-dev'])
        else:
            deps.extend(['libnuma-devel'])
        for packages in deps:
            if not smm.check_installed(packages) and not smm.install(packages):
                self.cancel('%s is needed for the test to be run' % packages)

        tarball = os.path.join(self.datadir, "Integritytests.tar")
        archive.extract(tarball, self.srcdir)
        self.build_dir = os.path.join(self.srcdir, 'Integritytests')
        build.make(self.build_dir)

    def test(self):
        '''
        Execute Integrity tests
        '''
        os.chdir(self.build_dir)
        scenario_arg = self.params.get('scenario_arg', default='1')
        if process.system('./mem_integrity_test -s %s' % scenario_arg,
                          shell=True, ignore_status=True) != 0:
            self.fail("Test failed")


if __name__ == "__main__":
    main()
