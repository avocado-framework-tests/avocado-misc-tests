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
from avocado.utils import archive, build, distro, process
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
        detected_distro = distro.detect()
        for package in ['gcc', 'make', 'autoconf']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        run_type = self.params.get('type', default='upstream')
        if run_type == "upstream":
            default_url = ("https://github.com/OpenKMIP/libkmip/archive/"
                           "refs/heads/master.zip")
            url = self.params.get('url', default=default_url)
            tarball = self.fetch_asset(url, expire='7d')
            archive.extract(tarball, self.workdir)
            self.srcdir = os.path.join(self.workdir, 'libkmip-master')
            if build.make(self.srcdir):
                self.fail("Failed to compile libkmip")
        elif run_type == "distro":
            if detected_distro.name in ['rhel', 'fedora', 'centos']:
                self.cancel("For %s 'libkmip' package not available" %
                            detected_distro.name)
            self.srcdir = os.path.join(self.workdir, "libkmip-distro")
            if not os.path.exists(self.srcdir):
                os.makedirs(self.srcdir)
            self.srcdir = smm.get_source("libkmip", self.srcdir)
            if not self.srcdir:
                self.fail("libkmip source install failed.")
        os.chdir(self.srcdir)

    def test(self):
        '''
        Running tests from libkmip
        '''
        count = 0
        output = process.run("./bin/tests", ignore_status=True, shell=True)
        for line in output.stdout.decode().splitlines():
            if 'FAIL - ' in line:
                count += 1
                self.log.info(line)
        if count:
            self.fail("%s test(s) failed, please refer to the log" % count)
