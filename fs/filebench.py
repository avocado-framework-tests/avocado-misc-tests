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

from avocado import Test
from avocado import main
from avocado.utils import process, archive, build
from avocado.utils.software_manager import SoftwareManager


class Filebench(Test):

    """
    Filebench - A Model Based File System Workload Generator

    :avocado: tags=fs
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
                self.cancel(package + ' is needed for the test to be run')

        name_version = 'filebench-1.5-alpha3'
        tarball = self.fetch_asset('https://github.com/filebench/'
                                   'filebench/releases/download/1.5-alpha3/'
                                   '%s.tar.gz' % name_version)

        archive.extract(tarball, self.workdir)
        self.install_prefix = os.path.join(self.workdir, 'install_prefix')
        build_dir = os.path.join(self.workdir, name_version)
        os.chdir(build_dir)
        process.run('./configure --prefix=%s' % self.install_prefix,
                    shell=True)
        build.make(build_dir)
        build.make(build_dir, extra_args='install')

    def test(self):
        binary_path = os.path.join(self.install_prefix, 'bin', 'filebench')
        testfile = self.params.get('testfile', default='fileserver.f')
        testfile_path = os.path.join(self.install_prefix, 'share', 'filebench',
                                     'workloads', testfile)
        cmd = '%s -f %s' % (binary_path, testfile_path)
        out = process.system_output(cmd)
        self.log.info(b"result:" + out)


if __name__ == "__main__":
    main()
