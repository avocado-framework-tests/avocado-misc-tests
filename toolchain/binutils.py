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
        """
        Appends package to `self._needed_deps` when not able to install it
        """
        if (not self._sm.check_installed(package) and
                not self._sm.install(package)):
            self.cancel('Please install %s for the test to run' % self.package)

    def setUp(self):
        # Check for basic utilities
        self._sm = SoftwareManager()

        # Install required tools and resolve dependencies
        needed_deps = ['make', 'gcc', 'dejagnu',
                       'elfutils', 'autoconf', 'automake']
        dist = distro.detect()
        if dist.name.lower() == 'ubuntu':
            needed_deps.extend(['build-essential'])
        for pkg in needed_deps:
            self.check_install(pkg)
        run_type = self.params.get("type", default="upstream")
        # Extract - binutils
        # Source: https://ftp.gnu.org/gnu/binutils/binutils-2.26.tar.bz2
        if run_type == "upstream":
            version = self.params.get('binutils_version', default='2.27')
            locations = [
                "https://www.mirrorservice.org/sites/sourceware.org"
                "/pub/binutils/releases/binutils-%s.tar.bz2" % version]
            tarball = self.fetch_asset("binutils-%s.tar.bz2" % version,
                                       locations=locations)
            archive.extract(tarball, self.workdir)
            self.sourcedir = os.path.join(
                self.workdir, os.path.basename(tarball.split('.tar.')[0]))
        elif run_type == "distro":
            self.sourcedir = os.path.join(self.workdir, "binutils-distro")
            if not os.path.exists(self.sourcedir):
                self.sourcedir = self._sm.get_source("binutils", self.sourcedir)

        # Compile the binutils
        os.chdir(self.sourcedir)
        process.run('./configure')
        build.make(self.sourcedir)

    def test(self):
        """
        Runs the binutils `make check`
        """
        ret = build.make(self.sourcedir, extra_args='check', ignore_status=True)

        errors = 0
        for root, _, filenames in os.walk(self.sourcedir):
            for filename in fnmatch.filter(filenames, '*.log'):
                filename = os.path.join(root, filename)
                logfile = filename[:-4] + ".log"
                shutil.copy(logfile, self.logdir)
                with open(logfile) as result:
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
