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
# Author: Ramya BS <ramya@linux.vnet.ibm.com>

import os
import re
from avocado import Test
from avocado import main
from avocado.utils import archive
from avocado.utils import build
from avocado.utils import distro
from avocado.utils import process
from avocado.utils.software_manager import SoftwareManager


class GCC(Test):
    """
    This testcase make use of testsuite provided by the
    source package.
    """

    def setUp(self):
        """
        Install all the dependency packages required for building
        source tarball specific to os,if not tests will stop.
        """
        sm = SoftwareManager()
        dist = distro.detect()
        packages = ['gcc', 'dejagnu', 'flex', 'bison', 'sharutils']

        if dist.name == 'Ubuntu':
            packages.extend(['libmpfr-dev', 'libgmp-dev', 'libmpc-dev',
                             'texinfo', 'zip', 'libc6-dev', 'libelf1',
                             'elfutils', 'gnat', 'autogen'])
        elif dist.name == 'SuSE':
            packages.extend(['glibc-devel-static',
                             'zlib-devel',
                             'elfutils',
                             'libelf-devel',
                             'gcc-c++',
                             'isl-devel',
                             'gmp-devel',
                             'glibc-devel',
                             'mpfr-devel',
                             'makeinfo',
                             'texinfo',
                             'mpc-devel'])
        elif dist.name == 'redhat':
            packages.extend(['glibc-static',
                             'autogen',
                             'guile',
                             'guile-devel',
                             'libgo',
                             'libgo-devel',
                             'libgo-static',
                             'elfutils-devel',
                             'texinfo-tex',
                             'texinfo',
                             'elfutils-libelf-devel',
                             'gmp-devel',
                             'mpfr-devel',
                             'libmpc-devel',
                             'gcc-gnat',
                             'libgnat'])
        else:
            self.log.warn("Unsupported OS!")

        for package in packages:
            if not sm.check_installed(package) and not sm.install(package):
                self.error(
                    "Failed to install %s required for this test." % package)
        if dist.name == 'SuSE':
            gcc_version = process.system_output("gcc --version")
            get_system_gcc_version = re.search(
                'gcc \(SUSE Linux\) (.*)\n',
                gcc_version).group(1).replace(
                ".",
                "_")
        else:
            get_system_gcc_version = process.system_output(
                "gcc -dumpversion").replace(".", "_").split("\n", 1)[0]
        tarball = self.fetch_asset(
            "https://github.com/gcc-mirror/gcc/archive/gcc-%s-release.zip" %
            get_system_gcc_version)
        archive.extract(tarball, self.srcdir)
        gcc_folder = 'gcc-' + os.path.basename(tarball.split('.zip')[0])
        self.srcdir = os.path.join(self.srcdir, gcc_folder)
        os.chdir(self.srcdir)
        process.run('./configure', ignore_status=True, sudo=True)
        build.make(self.srcdir)

    def test(self):
        """
        Runs the gcc `make check`
        """
        ret = process.run("make check", ignore_status=True, sudo=True)
        logfile_name = os.path.join(self.logdir, "stdout")
        logfile = open(logfile_name)
        for line in logfile:
            if line.startswith("\t\t==="):
                self.log.info(line)
            if line.startswith("#"):
                self.log.info(line)
        if ret.exit_status:
            self.fail("Few gcc tests failed,refer the log file")

if __name__ == "__main__":
    main()
