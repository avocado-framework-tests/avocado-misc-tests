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
# Copyright: 2016 IBM.
# Author: Jayarama<jsomalra@linux.vnet.ibm.com>

# Based on code by
#   Author: Abdul Haleem <abdhalee@linux.vnet.ibm.com>

import os
import fnmatch

from avocado import Test
from avocado import main

from avocado.utils import archive
from avocado.utils import build
from avocado.utils import process
from avocado.utils import distro

from avocado.utils.software_manager import SoftwareManager


class Binutils(Test):
    """
    This testcase make use of testsuite provided by the
    source package, performs functional test for all binary tools
    source file is downloaded and compiled.
    """

    def check_install(self, package):
        if not self.sm.check_installed(package) \
                and not self.sm.install(package):
            self.needed_deps.append(package)

    def setUp(self):
        # Check for basic utilities
        ditected_distro = distro.detect()
        self.sm = SoftwareManager()

        # Install required tools and resolve dependencies
        self.needed_deps = []

        self.check_install('rpmbuild')
        self.check_install('elfutils')
        self.check_install('build')
        self.check_install('autoconf')
        self.check_install('automake')
        self.check_install('binutils-devel')
        self.check_install('djangu')
        self.check_install('libtool')
        self.check_install('glibc-static')
        self.check_install('zlib-static')

        if len(self.needed_deps) > 0:
            self.log.warn('Please install these dependencies %s'
                          % self.needed_deps)

        # Extract - binutils
        # Source: https://ftp.gnu.org/gnu/binutils/binutils-2.26.tar.bz2
        source = 'https://ftp.gnu.org/gnu/binutils/binutils-2.26.tar.bz2'
        tarball = self.fetch_asset(source)
        archive.extract(tarball, self.srcdir)

        bintools_version = os.path.basename(tarball.split('.tar.')[0])
        self.src_dir = os.path.join(self.srcdir, bintools_version)

    def test(self):
        os.chdir(self.src_dir)

        process.run('./configure')
        build.make(self.src_dir)
        build.make(self.src_dir, extra_args='check')

        for root, dirnames, filenames in os.walk('.'):
            for filename in fnmatch.filter(filenames, '*.log'):
                filename = os.path.join(root, filename)
                logfile = filename[:-4] + ".log"
                os.system('cp ' + logfile + ' ' + self.logdir)
                with open(logfile) as result:
                    for line in result.readlines():
                        if line.startswith('FAIL'):
                            self.log.error(line)

if __name__ == "__main__":
    main()
