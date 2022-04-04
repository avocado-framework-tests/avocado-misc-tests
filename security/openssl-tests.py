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
# Copyright: 2020 IBM
# Author: Nageswara R Sastry <rnsastry@linux.vnet.ibm.com>

import os
from avocado import Test
from avocado.utils import archive, process
from avocado.utils.software_manager import SoftwareManager


class OpenSSL(Test):
    """
    openssl-testsuite
    :avocado: tags=security,testsuite
    """
    def setUp(self):
        '''
        Install the basic packages to support openssl
        '''
        # Check for basic utilities
        smm = SoftwareManager()
        deps = ['gcc', 'make']
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        url = "https://github.com/openssl/openssl/archive/master.zip"
        tarball = self.fetch_asset(url, expire='7d')
        archive.extract(tarball, self.workdir)
        self.sourcedir = os.path.join(self.workdir, 'openssl-master')
        os.chdir(self.sourcedir)
        process.run('./Configure', ignore_status=True)

    def test(self):
        '''
        Running tests from openssl
        '''
        count = 0
        cmd = "make test"
        output = process.run(cmd, ignore_status=True)
        for line in output.stdout_text.splitlines():
            if 'not ok' in line:
                count += 1
                self.log.info(line)
        if count:
            self.fail("%s test(s) failed, please refer to the log" % count)
