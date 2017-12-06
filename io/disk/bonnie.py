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
# Copyright: 2016 Red Hat, Inc.
# Author: Amador Pahim <apahim@redhat.com>
#
# Based on code by Martin J. Bligh <mbligh@google.com>
#   copyright 2006 Google
#   https://github.com/autotest/autotest-client-tests/tree/master/bonnie

"""
Bonnie test
"""

import os
import getpass
from avocado import Test
from avocado import main
from avocado.utils import archive
from avocado.utils import build
from avocado.utils import process, distro
from avocado.utils.partition import Partition
from avocado.utils.software_manager import SoftwareManager


class Bonnie(Test):

    """
    Bonnie++ is a benchmark suite that is aimed at performing a number
    of simple tests of hard drive and file system performance.
    """

    def setUp(self):
        """
        Build bonnie++
        Source:
         http://www.coker.com.au/bonnie++/experimental/bonnie++-1.03e.tgz
        """

        fstype = self.params.get('fs', default='ext4')

        if process.system("which bonnie++", ignore_status=True):
            smm = SoftwareManager()
            if not smm.check_installed('bonnie++') \
                    and not smm.check_installed('bonnie++'):
                '''Install the package from upstream'''
                deps = ['gcc', 'make']
                if distro.detect().name == 'Ubuntu':
                    deps.extend(['g++'])
                else:
                    deps.extend(['gcc-c++'])
                if fstype == 'btrfs':
                    if distro.detect().name == 'Ubuntu':
                        deps.extend(['btrfs-tools'])

            for package in deps:
                if not smm.check_installed(package) \
                        and not smm.install(package):
                    self.cancel("Fail to install/check %s, which is needed for"
                                "Bonnie test to run" % package)

            tarball = self.fetch_asset('http://www.coker.com.au/bonnie++/'
                                       'bonnie++-1.03e.tgz', expire='7d')
            archive.extract(tarball, self.teststmpdir)
            self.source = os.path.join(self.teststmpdir,
                                       os.path.basename(
                                           tarball.split('.tgz')[0]))
            os.chdir(self.source)
            process.run('./configure')
            build.make(self.source)
            build.make(self.source, extra_args='install')

        self.disk = self.params.get('disk', default=None)
        self.scratch_dir = self.params.get('dir', default=self.srcdir)
        self.uid_to_use = self.params.get('uid-to-use',
                                          default=getpass.getuser())
        self.number_to_stat = self.params.get('number-to-stat', default=2048)
        self.data_size = self.params.get('data_size_to_pass', default=0)

        if self.disk is not None:
            self.part_obj = Partition(self.disk, mountpoint=self.scratch_dir)
            self.log.info("Test will run on %s", self.scratch_dir)
            self.log.info("Unmounting disk/dir before creating file system")
            self.part_obj.unmount()
            self.log.info("creating %s file system on %s disk",
                          fstype, self.disk)
            self.part_obj.mkfs(fstype)
            self.log.info("Mounting disk %s on directory %s",
                          self.disk, self.scratch_dir)
            self.part_obj.mount()

    def test(self):
        """
        Run 'bonnie' with its arguments
        """
        args = []
        args.append('-d %s' % self.scratch_dir)
        args.append('-n %s' % self.number_to_stat)
        args.append('-s %s' % self.data_size)
        args.append('-u %s' % self.uid_to_use)
        cmd = ('bonnie++ %s' % " ".join(args))
        if process.system(cmd, shell=True, ignore_status=True):
            self.fail("test failed")

    def tearDown(self):
        '''
        Cleanup of disk used to perform this test
        '''
        if os.listdir(self.source):
            build.make(self.source, extra_args='clean')
        if self.disk is not None:
            self.log.info("Unmounting disk %s on directory %s", self.disk,
                          self.scratch_dir)
            self.part_obj.unmount()


if __name__ == "__main__":
    main()
