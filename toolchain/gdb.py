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
# Author: Pavithra <pavrampu@linux.vnet.ibm.com>

import os
import re
from avocado import Test
from avocado import main
from avocado.utils import archive
from avocado.utils import build
from avocado.utils import distro
from avocado.utils import process
from avocado.utils.software_manager import SoftwareManager


class GDB(Test):

    def setUp(self):
        sm = SoftwareManager()
        dist = distro.detect()
        packages = ['gcc', 'dejagnu', 'flex', 'bison', 'texinfo']
        if dist.name == 'Ubuntu':
            packages.extend(['g++', 'binutils-dev'])
        # FIXME: "redhat" as the distro name for RHEL is deprecated
        # on Avocado versions >= 50.0.  This is a temporary compatibility
        # enabler for older runners, but should be removed soon
        elif dist.name in ['rhel', 'fedora', 'redhat']:
            packages.extend(['gcc-c++', 'binutils-devel', 'texi2html'])
        elif dist.name == 'SuSE':
            packages.extend(['gcc-c++', 'binutils-devel'])

        else:
            self.fail('no packages list for your distro.')
        for package in packages:
            if not sm.check_installed(package) and not sm.install(package):
                self.cancel("Fail to install %s required for this test." %
                            package)
        test_type = self.params.get('type', default='upstream')
        if test_type == 'upstream':
            gdb_version = self.params.get('gdb_version', default='7.10')
            tarball = self.fetch_asset(
                "http://ftp.gnu.org/gnu/gdb/gdb-%s.tar.gz" % gdb_version)
            archive.extract(tarball, self.workdir)
            sourcedir = os.path.join(
                self.workdir, os.path.basename(tarball.split('.tar')[0]))
        elif test_type == 'distro':
            sourcedir = os.path.join(self.workdir, 'gdb-distro')
            if not os.path.exists(sourcedir):
                os.makedirs(sourcedir)
            sourcedir = sm.get_source("gdb", sourcedir)
        os.chdir(sourcedir)
        process.run('./configure', ignore_status=True, sudo=True)
        build.make(sourcedir)

    def test(self):
        process.run("make check-gdb", ignore_status=True, sudo=True)
        logfile = os.path.join(self.logdir, "stdout")
        with open(logfile, 'r') as f:
            for line in f.readlines():
                for match in re.finditer("of unexpected failures[1-9]", line):
                    self.log.info(line)
                    self.fail("Few gdb tests have failed")


if __name__ == "__main__":
    main()
