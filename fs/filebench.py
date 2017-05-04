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
# Copyright: 2016 IBM
# Author:Praveen K Pandey <praveen@linux.vnet.ibm.com>
#


import os
import shutil

from avocado import Test
from avocado import main
from avocado.utils import process, archive, build
from avocado.utils.software_manager import SoftwareManager


class Filebench(Test):

    """
    Filebench - A Model Based File System Workload Generator
    """

    def setUp(self):
        '''
        Build FileBench
        Source:
        https://github.com/filebench/filebench/releases/download/1.5-alpha3/filebench-1.5-alpha3.tar.gz
        '''

        # Check for basic utilities
        smm = SoftwareManager()
        deps = ['libtool', 'automake', 'autoconf', 'bison', 'gcc', 'flex']

        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.error(package + ' is needed for the test to be run')

        self._testfile = self.params.get('testfile', default='fileserver.f')

        tarball = self.fetch_asset('https://github.com/filebench/'
                                   'filebench/releases/download/1.5-alpha3/'
                                   'filebench-1.5-alpha3.tar.gz')

        archive.extract(tarball, self.srcdir)
        version = os.path.basename(tarball.split('.tar.')[0])
        self.srcdir = os.path.join(self.srcdir, version)

        os.chdir(self.srcdir)

        process.run('./configure', shell=True, sudo=True)
        build.make(self.srcdir)
        build.make(self.srcdir, extra_args='install')

        # Setup test file
        t_dir = '/usr/local/share/filebench/workloads/'
        shutil.copyfile(os.path.join(t_dir, self._testfile),
                        os.path.join(self.srcdir, self._testfile))

    def test(self):

        cmd = '%s -f  %s  ' % (os.path.join(self.srcdir,
                                            'filebench'), self._testfile)

        out = process.system_output(cmd)

        self.log.info("result:" + out)

    def tearDown(self):
        # un install file bench
        build.make(self.srcdir, extra_args='uninstall')


if __name__ == "__main__":
    main()
