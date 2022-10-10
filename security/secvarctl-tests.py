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
# Copyright: 2022 IBM
# Author: Nageswara R Sastry <rnsastry@linux.vnet.ibm.com>

import os
from avocado import Test
from avocado.utils import archive, build
from avocado.utils.software_manager.manager import SoftwareManager


class secvarctl(Test):
    """
    secvarctl testsuite
    :avocado: tags=security,testsuite
    """
    def setUp(self):
        '''
        Install the basic packages to support secvarctl
        '''
        # Check for basic utilities
        smm = SoftwareManager()
        deps = ['gcc', 'make', 'openssl-devel']
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        run_type = self.params.get('type', default='upstream')
        if run_type == "upstream":
            def_url = ("https://github.com/open-power/secvarctl/archive/"
                       "refs/heads/main.zip")
            url = self.params.get('url', default=def_url)
            tarball = self.fetch_asset(url, expire='7d')
            archive.extract(tarball, self.workdir)
            self.srcdir = os.path.join(self.workdir, 'secvarctl-main/test')
        elif run_type == "distro":
            self.srcdir = os.path.join(self.workdir, "secvarctl-distro")
            if not os.path.exists(self.srcdir):
                os.makedirs(self.srcdir)
            self.srcdir = smm.get_source('secvarctl', self.srcdir)
            if not self.srcdir:
                self.fail("secvarctl source install failed.")
            self.srcdir = os.path.join(self.srcdir, 'test')
        os.chdir(self.srcdir)

    def test(self):
        '''
        Running tests from secvarctl
        '''
        count = 0
        output = build.run_make(self.srcdir, extra_args="OPENSSL=1",
                                process_kwargs={"ignore_status": True})
        if output.exit_status:
            self.fail("secvarctl 'make check' failed.")
        for line in output.stdout_text.splitlines():
            if 'FAIL:' in line and 'XFAIL:' not in line and \
               '# FAIL:' not in line:
                count += 1
                self.log.info(line)
        if count:
            self.fail("%s test(s) failed, please refer to the log" % count)
