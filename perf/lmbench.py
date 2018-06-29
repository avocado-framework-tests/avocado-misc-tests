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
        memory_size_mb = self.params.get('MB', default=125)
        self.tmpdir = tempfile.mkdtemp(prefix='avocado_' + __name__)
        smm = SoftwareManager()
        for package in ['gcc', 'make', 'patch']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel("%s is needed for the test to be run" % package)
        tarball = self.fetch_asset('http://www.bitmover.com'
                                   '/lmbench/lmbench3.tar.gz')
        archive.extract(tarball, self.workdir)
        version = os.path.basename(tarball.split('.tar.')[0])
        self.sourcedir = os.path.join(self.workdir, version)

        # Patch for lmbench

        os.chdir(self.sourcedir)

        makefile_patch = 'patch -p1 < %s' % self.get_data('makefile.patch')
        build_patch = 'patch -p1 < %s' % self.get_data(
            '0001-Fix-build-issues-with-lmbench.patch')
        lmbench_fix_patch = 'patch -p1 < %s' % self.get_data(
            '0002-Changing-shebangs-on-lmbench-scripts.patch')
        ostype_fix_patch = 'patch -p1 < %s' % self.get_data(
            'fix_add_os_type.patch')

        process.run(makefile_patch, shell=True)
        process.run(build_patch, shell=True)
        process.run(lmbench_fix_patch, shell=True)
        process.run(ostype_fix_patch, shell=True)

        build.make(self.sourcedir)

        # configure lmbench
        os.chdir(self.sourcedir)

        process.system('yes "" | make config', shell=True, ignore_status=True)

        # find the lmbench config file
        output = os.popen('ls -1 bin/*/CONFIG*').read()
        config_files = output.splitlines()
        if len(config_files) != 1:
            self.error('Config not found : % s' % config_files)
        config_file = config_files[0]
        if not fsdir:
            fsdir = self.tmpdir
        if not temp_file:
            temp_file = os.path.join(self.tmpdir, 'XXX')

        # patch the resulted config to use the proper temporary directory and
        # file locations
        with open(config_file, "r+") as cfg_file:
            lines = cfg_file.readlines()
            cfg_file.seek(0)
            cfg_file.truncate()
            for line in lines:
                if line.startswith("FSDIR="):
                    cfg_file.write("FSDIR=%s\n" % fsdir)
                elif line.startswith("FILE="):
                    cfg_file.write("FILE=%s\n" % temp_file)
                elif line.startswith("MB="):
                    cfg_file.write("MB=%s\n" % memory_size_mb)
                else:
                    cfg_file.write(line)
            # Printing the config file
            cfg_file.seek(0)
            for line in cfg_file.readlines():
                print(line)

    def test(self):

        os.chdir(self.sourcedir)
        build.make(self.sourcedir, extra_args='rerun')
        build.make(self.sourcedir, extra_args='rerun')
        build.make(self.sourcedir, extra_args='see')


if __name__ == "__main__":
    main()
