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
# Author: Rajashree Rajendran<rajashr7@linux.vnet.ibm.com>
# Based on code by Yao Fei Zhu <walkinair@cn.ibm.com>
#   Copyright: 2006 IBM
#   https://github.com/autotest/autotest-client-tests/tree/master/tiobench

"""
This program runs a multi-threaded I/O benchmark test
to measure file system performance.
"""

import os

from avocado import Test
from avocado import main
from avocado.utils import archive
from avocado.utils import build
from avocado.utils import process, distro
from avocado.utils.software_manager import SoftwareManager
from avocado.utils.partition import Partition


class Tiobench(Test):
    """
    Avocado test for tiobench.
    """
    def setUp(self):
        """
        Build tiobench.
        Source:
        https://github.com/mkuoppal/tiobench.git
        """
        self.fstype = self.params.get('fs', default='ext4')
        smm = SoftwareManager()
        packages = ['gcc']
        if self.fstype == 'btrfs':
            if distro.detect().name == 'Ubuntu':
                packages.extend(['btrfs-tools'])
        for package in packages:
            if not smm.check_installed(package) and not smm.install(package):
                self.skip("%s package required for this test." % package)
        locations = ["https://github.com/mkuoppal/tiobench/archive/master.zip"]
        tarball = self.fetch_asset("tiobench.zip", locations=locations)
        archive.extract(tarball, self.srcdir)
        os.chdir(os.path.join(self.srcdir, "tiobench-master"))
        build.make(".")

    def test(self):
        """
        Test execution with necessary arguments.
        :params dir: The directory in which to test.
                     Defaults to ., the current directory.
        :params blocks: The blocksize in Bytes to use. Defaults to 4096.
        :params threads: The number of concurrent test threads.
        :params size: The total size in MBytes of the files may use together.
        :params num_runs: This number specifies over how many runs
                          each test should be averaged.
        """
        self.target = self.params.get('dir', default=self.srcdir)
        self.disk = self.params.get('disk', default=None)
        blocks = self.params.get('blocks', default=4096)
        threads = self.params.get('threads', default=10)
        size = self.params.get('size', default=1024)
        num_runs = self.params.get('numruns', default=2)

        if self.disk is not None:
            self.part_obj = Partition(self.disk, mountpoint=self.target)
            self.log.info("Unmounting disk/dir before creating file system")
            self.part_obj.unmount()
            self.log.info("creating %s file system", self.fstype)
            self.part_obj.mkfs(self.fstype)
            self.log.info("Mounting disk %s on directory %s", self.disk,
                          self.target)
            self.part_obj.mount()

        self.log.info("Test will run on %s" % self.target)
        self.whiteboard = process.system_output('perl ./tiobench.pl '
                                                '--target {} --block={} '
                                                '--threads={} --size={} '
                                                '--numruns={}'
                                                .format(self.target, blocks,
                                                        threads, size,
                                                        num_runs))

    def tearDown(self):
        '''
        Cleanup of disk used to perform this test
        '''
        if self.disk is not None:
            self.log.info("Unmounting disk %s on directory %s", self.disk,
                          self.target)
            self.part_obj.unmount()


if __name__ == "__main__":
    main()
