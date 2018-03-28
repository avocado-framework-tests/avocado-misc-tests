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
# Copyright: 2017 IBM.
# Author: Ramya BS <ramya@linux.vnet.ibm.com>
# Author: Harish S <harish@linux.vnet.ibm.com>

import os

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
        smm = SoftwareManager()
        dist = distro.detect()
        packages = ['gcc', 'dejagnu', 'flex', 'bison', 'sharutils']

        if dist.name == 'Ubuntu':
            packages.extend(['libmpfr-dev', 'libgmp-dev', 'libmpc-dev',
                             'texinfo', 'zip', 'libc6-dev', 'libelf1',
                             'elfutils', 'gnat', 'autogen'])
        elif dist.name == 'SuSE':
            packages.extend(['glibc-devel-static', 'zlib-devel', 'elfutils',
                             'libelf-devel', 'gcc-c++', 'isl-devel',
                             'gmp-devel', 'glibc-devel', 'mpfr-devel',
                             'makeinfo', 'texinfo', 'mpc-devel'])
        else:
            packages.extend(['glibc-static', 'autogen', 'guile',
                             'guile-devel', 'libgo', 'libgo-devel',
                             'libgo-static', 'elfutils-devel',
                             'texinfo-tex', 'texinfo', 'elfutils-libelf-devel',
                             'gmp-devel', 'mpfr-devel', 'libmpc-devel',
                             'gcc-gnat', 'libgnat', 'zlib-devel',
                             'gettext', 'libgcc', 'libgomp'])

        for package in packages:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel(
                    "Failed to install %s required for this test." % package)
        tarball = self.fetch_asset('gcc.zip', locations=[
                                   'https://github.com/gcc-mirror/gcc/archive'
                                   '/master.zip'], expire='7d')
        archive.extract(tarball, self.workdir)
        self.sourcedir = os.path.join(self.workdir, 'gcc-master')

        os.chdir(self.sourcedir)
        process.run('./configure', ignore_status=True, sudo=True)
        build.make(self.sourcedir, ignore_status=True)

    def get_summary(self, index):
        with open(os.path.join(self.outputdir, 'gcc_summary'), 'a') as f_obj:
            while self.summary[index].startswith('#'):
                f_obj.write('%s\n' % self.summary[index])
                index += 1
            f_obj.write('\n')

    def test(self):
        """
        Runs the gcc `make check`
        """
        ret = build.run_make(
            self.sourcedir, extra_args='check',
            process_kwargs={'ignore_status': True})
        self.summary = ret.stdout.splitlines()
        for index, line in enumerate(self.summary):
            if "=== gcc Summary ===" in line:
                self.get_summary(index + 2)

        if ret.exit_status:
            self.fail("Few gcc tests failed,refer the log file")


if __name__ == "__main__":
    main()
