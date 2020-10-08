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
from avocado.utils.software_manager import SoftwareManager


class XMLSec(Test):
    """
    xmlsec-testsuite
    :avocado: tags=security,testsuite
    """
    def setUp(self):
        '''
        Install the basic packages to support xmlsec
        '''
        # Check for basic utilities
        smm = SoftwareManager()
        self.distro_name = distro.detect().name
        deps = ['gcc', 'make', 'autoconf']
        if 'Ubuntu' in self.distro_name:
            deps.extend(['libxml2-dev', 'libltdl-dev', 'libtool-bin'])
        elif self.distro_name in ['rhel', 'SuSE', 'fedora', 'centos']:
            deps.extend(['libxml2-devel', 'libtool-ltdl-devel'])
        else:
            self.cancel("%s not supported for this test"
                        % self.distro_name)
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        url = "https://github.com/lsh123/xmlsec/archive/master.zip"
        tarball = self.fetch_asset(url, expire='7d')
        archive.extract(tarball, self.workdir)
        self.sourcedir = os.path.join(self.workdir, 'xmlsec-master')
        os.chdir(self.sourcedir)
        process.run('./autogen.sh', ignore_status=True)
        build.make(self.sourcedir)

    def test(self):
        '''
        Running tests from xmlsec
        '''
        count = 0
        output = build.run_make(self.sourcedir, extra_args="check",
                                process_kwargs={"ignore_status": True})
        for line in output.stdout_text.splitlines():
            if 'Fail' in line:
                count += 1
                self.log.info(line)
        if count:
            self.fail("%s test(s) failed, please refer to the log" % count)
