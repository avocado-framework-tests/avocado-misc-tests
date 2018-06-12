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

        smm = SoftwareManager()
        dist = distro.detect()
        dist_name = dist.name.lower()

        packages = ['gcc', 'wget', 'autoconf', 'automake',
                    'dejagnu', 'binutils', 'patch']

        if dist_name == 'suse':
            packages.extend(['libdw-devel', 'libelf-devel', 'git-core',
                             'elfutils', 'binutils-devel', 'libtool', 'gcc-c++'])

        # FIXME: "redhat" as the distro name for RHEL is deprecated
        # on Avocado versions >= 50.0.  This is a temporary compatibility
        # enabler for older runners, but should be removed soon
        elif dist_name in ("rhel", "fedora", "redhat"):
            packages.extend(['elfutils-devel', 'elfutils-libelf-devel', 'git',
                             'elfutils-libelf', 'elfutils-libs', 'libtool-ltdl'])

        elif dist_name == 'ubuntu':
            packages.extend(['elfutils', 'libelf-dev', 'libtool', 'git',
                             'libelf1', 'librpmbuild3', 'binutils-dev'])
        else:
            self.cancel("Unsupported OS!")

        for package in packages:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel("Fail to install %s required for this test." %
                            package)
        run_type = self.params.get("type", default="upstream")
        if run_type == "upstream":
            source = self.params.get('url', default="git://git.debian.org/git/"
                                     "collab-maint/ltrace.git")
            git.get_repo(source, destination_dir=os.path.join(
                self.workdir, 'ltrace'))

            self.src_lt = os.path.join(self.workdir, "ltrace")
            os.chdir(self.src_lt)
            process.run('patch -p1 < %s' % self.get_data('ltrace.patch'), shell=True)
        elif run_type == "distro":
            self.src_lt = os.path.join(self.workdir, "ltrace-distro")
            if not os.path.exists(self.src_lt):
                self.src_lt = smm.get_source("ltrace", self.src_lt)
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
