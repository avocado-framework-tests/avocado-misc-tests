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
# Copyright (C) 2003-2004 EMC Corporation
#
# fs_mark: Benchmark synchronous/async file creation
#
# Ported to avocado by Kalpana S Shetty <kalshett@in.ibm.com>
# Written by Ric Wheeler <ric@emc.com>
#   http://prdownloads.sourceforge.net/fsmark/fs_mark-3.3.tar.gz

import os

from avocado import Test
from avocado import main
from avocado.utils import archive
from avocado.utils import build
from avocado.utils import process, distro
from avocado.utils.partition import Partition
from avocado.utils.software_manager import SoftwareManager


class fs_mark(Test):

    """
    The fs_mark program is meant to give a low level bashing to file
    systems. The write pattern that we concentrate on is heavily
    synchronous IO across mutiple directories, drives, etc.
    """

    def setUp(self):
        """
        fs_mark
        """

        smm = SoftwareManager()
        tarball = self.fetch_asset('http://prdownloads.source'
                                   'forge.net/fsmark/fs_mark-3.3.tar.gz')
        archive.extract(tarball, self.srcdir)
        fs_version = os.path.basename(tarball.split('.tar.')[0])
        self.srcdir = os.path.join(self.srcdir, fs_version)
        os.chdir(self.srcdir)
        process.run('make')
        build.make(self.srcdir)
        self.disk = self.params.get('disk', default=None)
        self.fstype = self.params.get('fs', default='ext4')

        if self.fstype == 'btrfs':
            if distro.detect().name == 'Ubuntu':
                if not smm.check_installed("btrfs-tools") and not \
                        smm.install("btrfs-tools"):
                    self.skip('btrfs-tools is needed for the test to be run')

    def test(self):
        """
        Run fs_mark
        """
        os.chdir(self.srcdir)

        # Just provide a sample run parameters
        num_files = self.params.get('num_files', default='1024')
        size = self.params.get('size', default='1000')
        self.dir = self.params.get('dir', default=self.teststmpdir)

        self.part_obj = Partition(self.disk, mountpoint=self.dir)
        self.log.info("Test will run on %s", self.dir)
        self.log.info("Unmounting the disk/dir before creating file system")
        self.part_obj.unmount()
        self.log.info("creating file system")
        self.part_obj.mkfs(self.fstype)
        self.log.info("Mounting disk %s on directory %s", self.disk, self.dir)
        self.part_obj.mount()

        cmd = ('./fs_mark -d %s -s %s -n %s' % (self.dir, size, num_files))
        process.run(cmd)

    def tearDown(self):

        '''
        Cleanup of disk used to perform this test
        '''
        self.log.info("Unmounting directory %s", self.dir)
        self.part_obj.unmount()


if __name__ == "__main__":
    main()
