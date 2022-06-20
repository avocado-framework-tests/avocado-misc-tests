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
# Author: Nageswara R Sastry <rnsastry@linux.ibm.com>

import os
from avocado import Test
from avocado.utils import archive, build, distro, process
from avocado.utils.software_manager.manager import SoftwareManager


class Nettle(Test):

    """
    nettle-testsuite
    :avocado: tags=security,testsuite,crypto
    """

    def setUp(self):
        '''
        Install the basic packages to support Nettle
        '''

        # Check for basic utilities
        smm = SoftwareManager()
        det_dist = distro.detect()
        deps = ['gcc', 'make', 'm4', 'libtool', 'automake', 'autoconf']
        if det_dist.name in ['rhel', 'SuSE', 'fedora', 'centos']:
            deps.extend(["gmp-devel", "gettext-devel"])
            if det_dist.name == "rhel" and int(det_dist.version) >= 9:
                # RHEL9 package name is libkcapi-fipscheck, texinfo-tex
                deps.extend(["libkcapi-fipscheck", "texinfo-tex"])
            elif det_dist.name == "SuSE":
                # SLES package name is texinfo
                deps.extend(["fipscheck", "texinfo"])
            else:
                # RHEL8/7 package name is fipscheck, texinfo-tex
                deps.extend(["fipscheck", "texinfo-tex"])
        else:
            self.cancel("Install the package for Nettle supported\
                      by %s" % det_dist.name)
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        url = ("https://github.com/gnutls/nettle/archive/refs/heads/master.zip")
        tarball = self.fetch_asset(url, expire='7d')
        archive.extract(tarball, self.workdir)
        self.sourcedir = os.path.join(self.workdir, 'nettle-master')
        os.chdir(self.sourcedir)
        process.run('autoreconf -ifv', ignore_status=True)
        process.run('./configure', ignore_status=True)
        if build.make(self.sourcedir):
            self.cancel("Building audit test suite failed")

    def test(self):
        '''
        Running tests from audit-testsuite
        '''
        count = 0
        output = build.run_make(self.sourcedir, extra_args="check",
                                process_kwargs={"ignore_status": True})
        for line in output.stdout_text.splitlines():
            if 'FAIL:' in line:
                count += 1
                self.log.info(line)
        if count:
            self.fail("%s test(s) failed, refer to the log file" % count)
