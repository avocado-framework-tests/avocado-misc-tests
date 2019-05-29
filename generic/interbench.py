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
# Based on code by Brandon Philips
#   copyright: 2006 IBM
#   https://github.com/autotest/autotest-client-tests/tree/master/interbench

import os

from avocado import Test
from avocado import main
from avocado.utils import archive
from avocado.utils import process
from avocado.utils import build, disk, memory
from avocado.utils.software_manager import SoftwareManager


class Interbench(Test):

    """
    Interbench is designed to measure the effect of changes in Linux kernel
    design or system configuration changes such as cpu, I/O scheduler and
    filesystem changes and options. With careful benchmarking, different
    hardware can be compared
    """

    def setUp(self):
        '''
        Build interbench
        Source:
        http://ck.kolivas.org/apps/interbench/interbench-0.31.tar.bz2
        '''
        sm_manager = SoftwareManager()
        for pkg in ['gcc', 'patch']:
            if (not sm_manager.check_installed(pkg) and not
                    sm_manager.install(pkg)):
                self.cancel("%s is needed for the test to be run" % pkg)

        disk_free_b = disk.freespace(self.teststmpdir)
        if memory.meminfo.MemTotal.b > disk_free_b:
            self.cancel('Disk space is less than total memory. Skipping test')

        tarball = self.fetch_asset('http://slackware.cs.utah.edu/pub/kernel'
                                   '.org/pub/linux/kernel/people/ck/apps/'
                                   'interbench/interbench-0.31.tar.gz')
        archive.extract(tarball, self.workdir)
        version = os.path.basename(tarball.split('.tar.')[0])
        self.sourcedir = os.path.join(self.workdir, version)

        # Patch for make file
        os.chdir(self.sourcedir)
        makefile_patch = 'patch -p1 < %s ' % self.get_data('makefile_fix.patch')
        process.run(makefile_patch, shell=True)

        build.make(self.sourcedir)

    def test(self):
        args = self.params.get('arg', default='')
        args += ' c'
        process.system("%s ' run ' %s" % (os.path.join(
            self.sourcedir, 'interbench'), args), sudo=True)


if __name__ == "__main__":
    main()
