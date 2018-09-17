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
# Copyright: 2017 IBM
# Author:Harish Sriram <harish@linux.vnet.ibm.com>
#


import os

from avocado import Test
from avocado import main
from avocado.utils import archive, build, process, distro
from avocado.utils.software_manager import SoftwareManager


class Bcc(Test):

    """
    Bcc is a compiler that understands traditional K&R C with just the
    restriction that bit fields are mapped to one of the other integer types.
    This is the self test of bcc package.
    """

    def setUp(self):
        '''
        Build Bcc Test
        Source:
        https://github.com/iovisor/bcc
        '''

        # Check for basic utilities
        detected_distro = distro.detect().name.lower()
        smm = SoftwareManager()
        # TODO: Add support for other distributions
        if not detected_distro == "ubuntu":
            self.cancel("Unsupported OS %s" % detected_distro)
        for package in ['bison', 'build-essential', 'cmake', 'flex',
                        'libedit-dev', 'libllvm3.8', 'llvm-3.8-dev',
                        'libclang-3.8-dev', 'python', 'zlib1g-dev',
                        'libelf-dev', 'clang-format-3.8', 'python-netaddr',
                        'python-pyroute2', 'arping', 'iperf', 'netperf',
                        'ethtool']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel("Failed to install %s, which is needed for"
                            "the test to be run" % package)

        locations = ["https://github.com/iovisor/bcc/archive/master.zip"]
        tarball = self.fetch_asset("bcc.zip", locations=locations,
                                   expire='7d')
        archive.extract(tarball, self.workdir)
        self.sourcedir = os.path.join(self.workdir, 'bcc-master')
        os.makedirs('%s/build' % self.sourcedir)
        self.builddir = '%s/build' % self.sourcedir
        os.chdir(self.builddir)
        process.run('cmake .. -DCMAKE_INSTALL_PREFIX=/usr', shell=True)

        build.make(self.builddir)

    def test(self):

        if build.make(self.builddir, extra_args='test', ignore_status=True):
            self.fail('test failed, Please check debug log')


if __name__ == "__main__":
    main()
