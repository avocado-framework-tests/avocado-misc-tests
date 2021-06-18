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
        deps = ['gcc', 'make']
        if detected_distro.name in ['rhel', 'SuSE', 'fedora', 'centos',
                                    'redhat']:
            deps.extend(["autoconf", "automake", "gettext", "gettext-devel",
                         "libtool", "device-mapper", "device-mapper-devel",
                         "device-mapper-libs", "popt-devel", "json-c",
                         "json-c-devel", "libblkid-devel", "libssh-devel"])
        else:
            self.cancel("Unsupported distro %s for cryptsetup package"
                        % detected_distro.name)
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        url = "https://gitlab.com/cryptsetup/cryptsetup/"
        git.get_repo(url, destination_dir=self.workdir)
        os.chdir(self.workdir)
        process.run("./autogen.sh")
        process.run("./configure")
        build.make(self.workdir)

    def test(self):
        '''
        Running tests from cryptsetup
        '''
        count = 0
        output = build.run_make(self.workdir, extra_args="check",
                                process_kwargs={"ignore_status": True})
        for line in output.stdout_text.splitlines():
            if 'FAIL:' in line:
                count += 1
                self.log.info(line)
        if count:
            self.fail("%s test(s) failed, please refer to the log" % count)
