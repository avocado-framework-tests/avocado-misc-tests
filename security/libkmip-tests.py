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
# Copyright: 2021 IBM
# Author: Nageswara R Sastry <rnsastry@linux.vnet.ibm.com>

import os
from avocado import Test
from avocado.utils import archive, build, process
from avocado.utils.software_manager.manager import SoftwareManager


class libkmip(Test):
    """
    libkmip-testsuite
    :avocado: tags=security,testsuite
    """
    def setUp(self):
        '''
        Install the basic packages to support libkmip
        '''
        # Check for basic utilities
        smm = SoftwareManager()
        for package in ['gcc', 'make', 'autoconf']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        url = "https://github.com/OpenKMIP/libkmip/archive/refs/heads/master.zip"
        tarball = self.fetch_asset(url, expire='7d')
        archive.extract(tarball, self.workdir)
        self.sourcedir = os.path.join(self.workdir, 'libkmip-master')
        if build.make(self.sourcedir):
            self.fail("Failed to compile libkmip")
        os.chdir(self.sourcedir)

    def test(self):
        '''
        Running tests from libkmip
        '''
        count = 0
        output = process.system_output("./tests", ignore_status=True,
                                       allow_output_check='combined').decode()
        for line in output.splitlines():
            if 'FAIL - ' in line:
                count += 1
                self.log.info(line)
        if count:
            self.fail("%s test(s) failed, please refer to the log" % count)
