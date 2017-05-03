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
import shutil

from avocado import Test
from avocado import main

from avocado.utils import build
from avocado.utils import process
from avocado.utils import git
from avocado.utils import distro

from avocado.utils.software_manager import SoftwareManager


class Ltrace(Test):

    def setUp(self):
        """
        Install  all the required dependencies
        Building source tarball requires packages specific to os
        that needs to be installed, if not installed test will stop.
        """

        backend = SoftwareManager()
        dist = distro.detect()
        dist_name = dist.name.lower()
        if not backend.check_installed("gcc") and not backend.install("gcc"):
            self.error("gcc is needed for the test to be run")

        pkgs = ['git', 'wget', 'autoconf', 'automake',
                'dejagnu', 'binutils']

        if dist_name == 'suse':
            sles_deps = ['build', 'libdw-devel', 'libelf-devel',
                         'elfutils', 'binutils-devel', 'libtool', 'gcc-c++']
            pkgs += sles_deps

        # FIXME: "redhat" as the distro name for RHEL is deprecated
        # on Avocado versions >= 50.0.  This is a temporary compatibility
        # enabler for older runners, but should be removed soon
        elif dist_name in ("rhel", "fedora", "redhat"):
            rhel_deps = ['elfutils-devel', 'elfutils-libelf-devel',
                         'elfutils-libelf', 'elfutils-libs', 'libtool-ltdl']
            pkgs += rhel_deps

        elif dist_name == 'ubuntu':
            ubuntu_deps = ['elfutils', 'libelf-dev', 'libtool',
                           'libelf1', 'librpmbuild3', 'binutils-dev']
            pkgs += ubuntu_deps
        else:
            self.log.warn("Unsupported OS!")

        for pkg in pkgs:
            if not backend.check_installed(pkg):
                if backend.install(pkg):
                    self.log.warn("%s installed successfully", pkg)
                else:
                    self.error("Fail to install package- %s required for "
                               "this test" % pkg)

        # Source: git clone git://git.debian.org/git/collab-maint/ltrace.git
        git.get_repo('git://git.debian.org/git/collab-maint/ltrace.git',
                     destination_dir=os.path.join(self.srcdir, 'ltrace'))

        self.src_lt = os.path.join(self.srcdir, "ltrace")
        os.chdir(self.src_lt)
        process.run('./autogen.sh')
        process.run('./configure')
        build.make(self.src_lt)

    def test(self):
        """
        Run the `make check` on ltrace
        """
        ret = build.make(self.src_lt, extra_args='check', ignore_status=True)

        errors = 0
        for root, _, filenames in os.walk('.'):
            for filename in fnmatch.filter(filenames, '*.log'):
                filename = os.path.join(root, filename)
                shutil.copy(filename, self.logdir)
                with open(filename) as result:
                    for line in result.readlines():
                        if line.startswith('FAIL'):
                            errors += 1
                            self.log.error(line)

        if errors:
            self.fail("%s test(s) failed, check the log for details." % errors)
        elif ret:
            self.fail("'make check' finished with %s, but no FAIL lines were "
                      "found." % ret)


if __name__ == "__main__":
    main()
