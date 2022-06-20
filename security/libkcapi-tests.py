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
from avocado.utils import archive, build, process
from avocado.utils.software_manager.manager import SoftwareManager


class LibKCAPI(Test):
    """
    libkcapi-testsuite
    :avocado: tags=security,testsuite
    """

    def setUp(self):
        '''
        Install the basic packages to support libkcapi
        '''
        # Check for basic utilities
        smm = SoftwareManager()
        deps = ['gcc', 'make', 'autoconf']
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        url = "https://github.com/smuellerDD/libkcapi/archive/master.zip"
        tarball = self.fetch_asset(url, expire='7d')
        archive.extract(tarball, self.workdir)
        self.sourcedir = os.path.join(self.workdir, 'libkcapi-master')
        os.chdir(self.sourcedir)
        process.run("autoreconf -i")
        process.run("./configure --enable-kcapi-test --enable-kcapi-speed \
                    --enable-kcapi-hasher --enable-kcapi-rngapp \
                    --enable-kcapi-encapp --enable-kcapi-dgstapp")
        build.make(self.sourcedir)
        self.test_dir = os.path.join(self.sourcedir, 'test')
        os.chdir(self.test_dir)
        self.test_name = "bash %s" % self.params.get('test_name',
                                                     default='test.sh')

    def run_cmd(self, cmd):
        count = 0
        output = process.system_output(cmd, ignore_status=True).decode()
        for line in output.splitlines():
            if 'FAILED:' in line:
                count += 1
                self.log.info(line)
        if count:
            self.fail("%s test(s) failed, please refer to the log" % count)

    def test(self):
        self.run_cmd(self.test_name)
