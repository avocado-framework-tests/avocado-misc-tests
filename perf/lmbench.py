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
# Author: Praveen K Pandey <praveen@linux.vnet.ibm.com>
#
# Based on code by Martin Bligh <mbligh@google.com>
#   copyright: 2008 Google
#   https://github.com/autotest/autotest-client-tests/tree/master/lmbench

import os
import tempfile

from avocado import Test
from avocado import main
from avocado.utils import archive
from avocado.utils import process
from avocado.utils import build
from avocado.utils.software_manager import SoftwareManager


class Lmbench(Test):

    """
    lmbench is a series of micro benchmarks intended to measure basic
    operating system and hardware system metrics. The benchmarks fall
    into three general classes: bandwidth, latency, and ``other''.
    """

    def setUp(self):
        '''
        Build lmbench
        Source:
        http://www.bitmover.com/lmbench/lmbench3.tar.gz
        '''
        fsdir = self.params.get('fsdir', default=None)
        temp_file = self.params.get('temp_file', default=None)
        self.tmpdir = tempfile.mkdtemp(prefix='avocado_' + __name__)
        smm = SoftwareManager()
        if not smm.check_installed("gcc") and not smm.install("gcc"):
            self.error("Gcc is needed for the test to be run")
        tarball = self.fetch_asset('http://www.bitmover.com'
                                   '/lmbench/lmbench3.tar.gz')
        data_dir = os.path.abspath(self.datadir)
        archive.extract(tarball, self.srcdir)
        version = os.path.basename(tarball.split('.tar.')[0])
        self.srcdir = os.path.join(self.srcdir, version)

        # Patch for lmbench

        os.chdir(self.srcdir)

        makefile_patch = 'patch -p1 < %s' % (
            os.path.join(data_dir, 'makefile.patch'))
        build_patch = 'patch -p1 < %s' % (os.path.join(
            data_dir, '0001-Fix-build-issues-with-lmbench.patch'))
        lmbench_fix_patch = 'patch -p1 < %s' % (os.path.join(
            data_dir, '0002-Changing-shebangs-on-lmbench-scripts.patch'))
        ostype_fix_patch = 'patch -p1 < %s' % (
            os.path.join(data_dir, 'fix_add_os_type.patch'))

        process.run(makefile_patch, shell=True)
        process.run(build_patch, shell=True)
        process.run(lmbench_fix_patch, shell=True)
        process.run(ostype_fix_patch, shell=True)

        build.make(self.srcdir)

        # configure lmbench
        os.chdir(self.srcdir)

        os.system('yes "" | make config')

        # find the lmbench config file
        output = os.popen('ls -1 bin/*/CONFIG*').read()
        config_files = output.splitlines()
        if len(config_files) != 1:
            raise error.TestError('Config not found : % s' % config_files)
        config_file = config_files[0]
        if not fsdir:
            fsdir = self.tmpdir
        if not temp_file:
            temp_file = os.path.join(self.tmpdir, 'XXX')

        # patch the resulted config to use the proper temporary directory and
        # file locations
        tmp_config_file = config_file + '.tmp'
        process.system('touch ' + tmp_config_file)
        process.system("sed 's!^FSDIR=.*$!FSDIR=%s!' '%s'  '%s' " %
                       (fsdir, config_file, tmp_config_file))
        process.system("sed 's!^FILE=.*$!FILE=%s!' '%s'  '%s'" %
                       (temp_file, tmp_config_file, config_file))

    def test(self):

        os.chdir(self.srcdir)
        build.make(self.srcdir, extra_args='rerun')

if __name__ == "__main__":
    main()
