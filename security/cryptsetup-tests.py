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
from avocado.utils.software_manager.manager import SoftwareManager


class CryptSetup(Test):

    """
    cryptsetup-testsuite
    :avocado: tags=security,testsuite
    """

    def setUp(self):
        '''
        Install the basic packages to support cryptsetup
        '''
        # Check for basic utilities
        smm = SoftwareManager()
        detected_distro = distro.detect()
        deps = ["gcc", "make", "autoconf", "automake", "gettext",
                "gettext-devel", "libtool", "device-mapper", "popt-devel",
                "device-mapper-devel", "libblkid-devel", "libssh-devel"]
        if detected_distro.name in ['rhel', 'fedora', 'centos', 'redhat']:
            deps.extend(["device-mapper-libs", "json-c", "json-c-devel"])
        elif 'SuSE' in detected_distro.name:
            deps.extend(["libjson-c-devel", "libjson-c3", "libuuid-devel"])
        else:
            self.cancel("Unsupported distro %s for cryptsetup package"
                        % detected_distro.name)
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        run_type = self.params.get('type', default='upstream')
        if run_type == "upstream":
            default_url = "https://gitlab.com/cryptsetup/cryptsetup/"
            url = self.params.get('url', default=default_url)
            git.get_repo(url, destination_dir=self.workdir)
            os.chdir(self.workdir)
            self.srcdir = self.workdir
            output = process.run("./autogen.sh", ignore_status=True)
            if output.exit_status:
                self.fail("cryptsetup-tests.py: 'autogen.sh' failed.")
            output = process.run("./configure --disable-asciidoc",
                                 ignore_status=True)
            if output.exit_status:
                self.fail("cryptsetup-tests.py: 'configure' failed.")
            if build.make(self.workdir):
                self.fail("'make' failed.")
        elif run_type == "distro":
            self.srcdir = os.path.join(self.workdir, "cryptsetup-distro")
            if not os.path.exists(self.srcdir):
                os.makedirs(self.srcdir)
            self.srcdir = smm.get_source("cryptsetup", self.srcdir)
            if not self.srcdir:
                self.fail("cryptsetup source install failed.")
        os.chdir(self.srcdir)

    def test(self):
        '''
        Running tests from cryptsetup
        '''
        count = 0
        output = build.run_make(self.srcdir, extra_args="check",
                                process_kwargs={"ignore_status": True})
        if output.exit_status:
            self.fail("'make check' failed.")
        for line in output.stdout_text.splitlines():
            if 'FAIL:' in line:
                count += 1
                self.log.info(line)
        if count:
            self.fail("%s test(s) failed, please refer to the log" % count)
