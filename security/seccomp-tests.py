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
from avocado.utils import archive, build, distro, process
from avocado.utils.software_manager.manager import SoftwareManager


class SecComp(Test):

    """
    seccomp-testsuite
    :avocado: tags=security,testsuite
    """

    def setUp(self):
        '''
        Install the basic packages to support seccomp
        '''
        # Check for basic utilities
        smm = SoftwareManager()
        detected_distro = distro.detect()
        deps = ['gcc', 'make']
        if detected_distro.name in ['rhel', 'SuSE', 'fedora', 'centos',
                                    'redhat']:
            deps.extend(['gperf'])
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        run_type = self.params.get('type', default='upstream')
        if run_type == "upstream":
            def_url = ("https://github.com/seccomp/libseccomp/archive/refs/"
                       "heads/main.zip")
            url = self.params.get('url', default=def_url)
            tarball = self.fetch_asset(url, expire='7d')
            archive.extract(tarball, self.workdir)
            self.srcdir = os.path.join(self.workdir, 'libseccomp-main')
            os.chdir(self.srcdir)
            output = process.run("./autogen.sh")
            if output.exit_status:
                self.fail("seccomp-tests.py: 'autogen.sh' failed.")
            output = process.run("./configure")
            if output.exit_status:
                self.fail("seccomp-tests.py: 'configure' failed.")
        elif run_type == "distro":
            self.srcdir = os.path.join(self.workdir, "seccomp-distro")
            if not os.path.exists(self.srcdir):
                os.makedirs(self.srcdir)
            self.srcdir = smm.get_source('libseccomp', self.srcdir)
            if not self.srcdir:
                self.fail("libseccomp source install failed.")

    def test(self):
        '''
        Running tests from seccomp
        '''
        count = 0
        output = build.run_make(self.srcdir, extra_args="check",
                                process_kwargs={"ignore_status": True})
        if output.exit_status:
            self.fail("seccomp-tests.py: 'make check' failed.")
        for line in output.stdout_text.splitlines():
            if 'FAIL:' in line:
                count += 1
                self.log.info(line)
        if count:
            self.fail("%s test(s) failed, please refer to the log" % count)
