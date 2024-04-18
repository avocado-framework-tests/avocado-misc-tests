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
from avocado.utils import build, distro, git, process
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
        self.distro_version = distro.detect()
        smm = SoftwareManager()
        deps = ['gcc', 'make', 'cmake']
        if self.distro_version.name in ['rhel', 'redhat']:
            deps.extend(['openssl-devel'])
        if self.distro_version.name in ['SuSE']:
            deps.extend(['libopenssl-devel'])
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        self.srcdir = ""
        run_type = self.params.get('type', default='upstream')
        if run_type == "upstream":
            url = "https://github.com/open-power/secvarctl"
            git.get_repo(url, destination_dir=self.workdir, submodule=True, branch="main")
            self.srcdir = self.workdir
        elif run_type == "distro":
            self.srcdir = os.path.join(self.workdir, "secvarctl-distro")
            if not os.path.exists(self.srcdir):
                os.makedirs(self.srcdir)
            self.srcdir = smm.get_source('secvarctl', self.srcdir)
            if not self.srcdir:
                self.fail("secvarctl source install failed.")
        self.build_dir = os.path.join(self.srcdir, "build")
        os.mkdir(self.build_dir)
        os.chdir(self.build_dir)
        rc = process.system("cmake ../")
        if rc:
            self.cancel("secvarctl:'cmake' command failed, cancelling the test.")

    def test(self):
        '''
        Running tests from secvarctl
        '''
        count = 0
        output = build.run_make(self.build_dir,
                                process_kwargs={"ignore_status": True})
        if output.exit_status:
            self.cancel("secvarctl:'make' command failed, cancelling the test.")
        output = build.run_make(self.srcdir, extra_args="check",
                                process_kwargs={"ignore_status": True})
        if output.exit_status:
            self.fail("secvarctl:'make check' command failed. Check the logs.")
        for line in output.stdout_text.splitlines():
            if 'FAIL:' in line and 'XFAIL:' not in line and \
               '# FAIL:' not in line:
                count += 1
                self.log.info(line)
        if count:
            self.fail("%s test(s) failed, please refer to the log" % count)
