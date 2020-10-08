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
from avocado.utils import build, distro, git, process
from avocado.utils.software_manager import SoftwareManager


class annobin(Test):
    """
    annobin-testsuite
    :avocado: tags=security,testsuite
    """
    def setUp(self):
        '''
        Install the basic packages to support annobin
        '''
        # Check for basic utilities
        smm = SoftwareManager()
        self.distro_name = distro.detect().name
        deps = ['gcc', 'make', 'autoconf', 'texinfo']
        # Ubuntu requires gcc-?-plugin-dev with different names aligned with
        # gcc versions like 5,6,7,8 skipping Ubuntu for this test.
        # In SLES 'gcc-plugin-devel' package not available, skipping.
        if self.distro_name in ['rhel', 'fedora', 'centos']:
            deps.extend(['gcc-plugin-devel', 'rpm-devel'])
        else:
            self.cancel("%s not supported for this test" % self.distro_name)
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        url = "https://sourceware.org/git/annobin.git"
        git.get_repo(url, destination_dir=self.workdir)
        os.chdir(self.workdir)
        process.run('autoreconf', ignore_status=True)
        process.run('./configure', ignore_status=True)

    def test(self):
        '''
        Running tests from annobin
        '''
        count = 0
        output = build.run_make(self.workdir, extra_args="check",
                                process_kwargs={"ignore_status": True})
        for line in output.stdout_text.splitlines():
            if 'FAIL:' in line and 'XFAIL:' not in line and \
               '# FAIL:' not in line:
                count += 1
                self.log.info(line)
        if count:
            self.fail("%s test(s) failed, please refer to the log" % count)
