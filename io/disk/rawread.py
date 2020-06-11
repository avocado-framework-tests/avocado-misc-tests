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
# Copyright: 2019 IBM.
# Author: Naresh Bannoth <nbannoth@in.ibm.com>

"""
Rawread test
"""

import os
from avocado import Test
from avocado.utils import archive
from avocado.utils import build
from avocado.utils import process, distro
from avocado.utils.software_manager import SoftwareManager


class Rawread(Test):

    """
    Rawread is a benchmark suite that is aimed at performing a number
    of simple tests of hard drive like write and read
    """

    def setUp(self):
        """
        checking install of required packages and extract and
        compile of rawread suit.
        """
        smm = SoftwareManager()
        deps = ['gcc', 'make', 'libaio-devel']
        if distro.detect().name == 'Ubuntu':
            deps.extend(['g++'])
        else:
            deps.extend(['gcc-c++'])

        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel("Fail to install Package: %s" % package)

        tarball = self.get_data('rawread.tar')
        archive.extract(tarball, self.teststmpdir)
        self.source = os.path.join(self.teststmpdir,
                                   os.path.basename(
                                       tarball.split('.tar')[0]))
        os.chdir(self.source)
        build.make(self.source)

        self.disk = self.params.get('disk', default=None)

    def test(self):
        """
        Run 'rawread' with its arguments
        """
        err_val = []
        for val in range(24):
            cmd = "./rawread -t %s %s " % (val, self.disk)
            if process.system(cmd, shell=True, ignore_status=True):
                err_val.append(str(val))

        if err_val:
            self.fail("test failed for values : %s" % " ".join(err_val))
