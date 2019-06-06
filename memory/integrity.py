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
import shutil

from avocado import Test
from avocado import main
from avocado.utils import process, build
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import distro


class Integrity(Test):
    """
    Performs Memory Integrity Tests

    :avocado: tags=memory,privileged,migration
    """

    def copyutil(self, file_name):
        shutil.copyfile(self.get_data(file_name),
                        os.path.join(self.teststmpdir, file_name))

    def setUp(self):
        '''
        Build Integrity Test
        '''

        # Check for basic utilities
        smm = SoftwareManager()
        self.scenario_arg = self.params.get('scenario_arg', default='1')
        if self.scenario_arg not in ['1', '2', '3']:
            self.cancel("Test need to skip as scenario needs to be 1-3")
        detected_distro = distro.detect()
        deps = ['gcc', 'make']
        if detected_distro.name == "Ubuntu":
            deps.extend(['libnuma-dev'])
        elif detected_distro.name in ["centos", "rhel", "fedora"]:
            deps.extend(['numactl-devel'])
        else:
            deps.extend(['libnuma-devel'])
        for packages in deps:
            if not smm.check_installed(packages) and not smm.install(packages):
                self.cancel('%s is needed for the test to be run' % packages)

        for file_name in ['mem_integrity_test.c', 'Makefile']:
            self.copyutil(file_name)

        build.make(self.teststmpdir)

    def test(self):
        '''
        Execute Integrity tests
        '''
        os.chdir(self.teststmpdir)
        status = process.system('./mem_integrity_test -s %s' %
                                self.scenario_arg, shell=True, ignore_status=True)
        if status != 0:
            if status == 255:
                self.cancel("System does not have numa/memory to run the test")
            self.fail("Test failed")


if __name__ == "__main__":
    main()
