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
from avocado.utils import archive, process
from avocado.utils.software_manager.manager import SoftwareManager


class EvmCtl(Test):
    """
    evmctl-testsuite
    :avocado: tags=security,testsuite
    """
    def setUp(self):
        '''
        Install the basic packages to support evmctl
        '''
        # Check for basic utilities
        smm = SoftwareManager()
        deps = ['gcc', 'make']
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        run_type = self.params.get('type', default='upstream')
        if run_type == "upstream":
            default_url = ("https://sourceforge.net/projects/linux-ima/"
                           "files/latest/download")
            url = self.params.get('url', default=default_url)
            tarball = self.fetch_asset(name="download.tar.gz",
                                       locations=url, expire='7d')
            archive.extract(tarball, self.workdir)
            self.srcdir = os.path.join(self.workdir, os.listdir(self.workdir)[0])
            self.log.info("sourcedir - %s" % self.srcdir)
            os.chdir(self.srcdir)
            output = process.run('./autogen.sh', ignore_status=True)
            if output.exit_status:
                self.fail("evmctl-tests.py: 'autogen.sh' failed.")
        elif run_type == "distro":
            self.srcdir = os.path.join(self.workdir, "evmctl-distro")
            if not os.path.exists(self.srcdir):
                os.makedirs(self.srcdir)
            self.srcdir = smm.get_source("ima-evm-utils", self.srcdir)
        os.chdir(self.srcdir)

    def test(self):
        '''
        Running tests from evmctl
        '''
        count = 0
        output = process.system_output('./build.sh', ignore_status=True).decode()
        for line in reversed(output.splitlines()):
            if '# FAIL' in line:
                count = int(line.split(":")[1].strip())
                self.log.info(line)
                break
        # If the fail count is more than 0 then there are some failed tests
        if count:
            self.fail("%s test(s) failed, please refer to the log" % count)
