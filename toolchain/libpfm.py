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
#
# Copyright: 2018 IBM.
# Author: Harish <harish@linux.vnet.ibm.com>


import os
from avocado.utils import process
from avocado import Test
from avocado import main
from avocado.utils import build, distro, archive
from avocado.utils.software_manager import SoftwareManager


class Libpfm(Test):

    '''
    This testcase make use of testsuite provided by the
    source package, source files are downloaded and compiled
    '''

    def setUp(self):
        softm = SoftwareManager()

        pkgs = ['gcc', 'make']
        if distro.detect().name in ['SuSE', 'Ubuntu']:
            pkgs.extend(['libpfm4'])
        else:
            pkgs.extend(['libpfm'])

        for pkg in pkgs:
            if not softm.check_installed(pkg) and not softm.install(pkg):
                self.cancel("%s is needed for the test to be run" % pkg)
        test_type = self.params.get('type', default='upstream')

        if test_type == 'upstream':
            tarball = self.fetch_asset(
                'https://netix.dl.sourceforge.net/project/perfmon2/'
                'libpfm4/libpfm-4.9.0.tar.gz', expire='1d')
            archive.extract(tarball, self.teststmpdir)
            version = os.path.basename(tarball.split('.tar.')[0])
            self.path = os.path.join(self.teststmpdir, version)
        elif test_type == 'distro':
            sourcedir = os.path.join(self.teststmpdir, 'libpfm-distro')
            if not os.path.exists(sourcedir):
                os.makedirs(sourcedir)
            if distro.detect().name == 'Ubuntu':
                self.path = softm.get_source('libpfm4', sourcedir)
            else:
                self.path = softm.get_source('libpfm', sourcedir)

        os.chdir(self.path)
        build.make(self.path)

    def test(self):
        # Runs the tests
        result = process.run('./tests/validate',
                             shell=True, ignore_status=True)
        fail = False
        # Display the failed tests
        for line in result.stdout.splitlines():
            if 'Failed' in line:
                self.log.error("Failed: %s", line)
                fail = True
        if fail:
            self.fail("Tests failed, Please check the logs")


if __name__ == "__main__":
    main()
