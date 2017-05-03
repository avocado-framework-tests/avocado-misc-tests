#!/usr/bin/env python
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
# Copyright: 2016 IBM
# Author: Abdul Haleem <abdhalee@linux.vnet.ibm.com>

import os
import re

from avocado import Test
from avocado import main
from avocado.utils import build
from avocado.utils import distro
from avocado.utils import archive
from avocado.utils.software_manager import SoftwareManager


class kselftest(Test):

    """
    Linux Kernel Selftest available as a part of kernel source code.
    run the selftest available at tools/testing/selftest

    :see: https://www.kernel.org/doc/Documentation/kselftest.txt
    :source: https://github.com/torvalds/linux/archive/master.zip
    """

    testdir = 'tools/testing/selftests'

    def setUp(self):
        """
        Resolve the packages dependencies and download the source.
        """
        smg = SoftwareManager()
        detected_distro = distro.detect()
        deps = ['gcc', 'make', 'automake', 'autoconf']

        if 'Ubuntu' in detected_distro.name:
            deps.extend(['libpopt0', 'libc6', 'libc6-dev',
                        'libpopt-dev', 'libcap-ng0', 'libcap-ng-dev'])
        elif 'SuSE' in detected_distro.name:
            deps.extend(['popt', 'glibc', 'glibc-devel',
                         'popt-devel', 'libcap1', 'libcap1-devel',
                         'libcap-ng', 'libcap-ng-devel'])
        # FIXME: "redhat" as the distro name for RHEL is deprecated
        # on Avocado versions >= 50.0.  This is a temporary compatibility
        # enabler for older runners, but should be removed soon
        elif detected_distro.name in ['centos', 'fedora', 'rhel', 'redhat']:
            deps.extend(['popt', 'glibc', 'glibc-devel', 'glibc-static',
                         'libcap-ng', 'libcap', 'libcap-devel'])

        for package in deps:
            if not smg.check_installed(package) and not smg.install(package):
                self.error(
                    '%s is needed for the test to be run !!' % (package))

        location = ["https://github.com/torvalds/linux/archive/master.zip"]
        tarball = self.fetch_asset("kselftest.zip", locations=location,
                                   expire='1d')
        archive.extract(tarball, self.srcdir)
        self.buldir = os.path.join(self.srcdir, 'linux-master')
        self.srcdir = os.path.join(self.buldir, self.testdir)
        result = build.run_make(self.srcdir)
        for line in str(result).splitlines():
            if 'ERROR' in line:
                self.fail("Compilation failed, Please check the build logs !!")

    def test(self):
        """
        Execute the kernel selftest
        """
        error = False
        result = build.make(self.srcdir, extra_args='run_tests')
        for line in str(result).splitlines():
            if '[FAIL]' in line:
                error = True
                self.log.info("Testcase failed. Log from build: %s" % line)
        for line in open(os.path.join(self.logdir, 'debug.log')).readlines():
            match = re.search(r'selftests:\s+\w+\s+\[FAIL]', line)
            if match:
                error = True
                self.log.info("Testcase failed. Log from debug: %s" %
                              match.group(0))

        if error:
            self.fail("Testcase failed during selftests")


if __name__ == "__main__":
    main()
