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
#
# Ported to avocado by Kalpana S Shetty <kalshett@in.ibm.com>
# Written by Ric Wheeler <ric@emc.com>
#   http://prdownloads.sourceforge.net/fsmark/fs_mark-3.3.tar.gz

"""
fs_mark: Benchmark synchronous/async file creation
"""

import os
from avocado import Test
from avocado import main
from avocado.utils import archive
from avocado.utils import build
from avocado.utils import process, distro
from avocado.utils.partition import Partition
from avocado.utils.software_manager import SoftwareManager
from avocado.utils.partition import PartitionError


class FSMark(Test):

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
        tarball = self.fetch_asset('https://github.com/josefbacik/fs_mark/'
                                   'archive/master.zip')
        archive.extract(tarball, self.teststmpdir)
        self.sourcedir = os.path.join(self.teststmpdir, 'fs_mark-master')
        os.chdir(self.sourcedir)
        process.run('make')
        build.make(self.sourcedir)
        self.disk = self.params.get('disk', default=None)
        self.num = self.params.get('num_files', default='1024')
        self.size = self.params.get('size', default='1000')
        self.dirs = self.params.get('dir', default=self.workdir)
        self.fstype = self.params.get('fs', default='ext4')

        if self.fstype == 'btrfs':
            if distro.detect().name == 'Ubuntu':
                if not smm.check_installed("btrfs-tools") and not \
                        smm.install("btrfs-tools"):
                    self.cancel('btrfs-tools is needed for the test to be run')

        if self.disk is not None:
            self.part_obj = Partition(self.disk, mountpoint=self.dirs)
            self.log.info("Test will run on %s", self.dirs)
            self.log.info("Unmounting the disk before creating file system")
            self.part_obj.unmount()
            self.log.info("creating file system")
            self.part_obj.mkfs(self.fstype)
            self.log.info("Mounting disk %s on dir %s", self.disk, self.dirs)
            try:
                self.part_obj.mount()
            except PartitionError:
                self.fail("Mounting disk %s on directory %s failed"
                          % (self.disk, self.dirs))
            self.link = "/tmp/link"
            os.symlink(self.dirs, self.link)

    def test(self):
        """
        Run fs_mark
        """
        os.chdir(self.sourcedir)
        cmd = "./fs_mark -d %s -s %s -n %s" % (self.link, self.size, self.num)
        process.run(cmd)

    def tearDown(self):
        '''
        Cleanup of disk used to perform this test
        '''
        if self.link:
            os.unlink(self.link)
        if self.disk is not None:
            self.log.info("Unmounting disk %s on directory %s",
                          self.disk, self.dirs)
            self.part_obj.unmount()
        self.log.info("Removing the filesystem created on %s", self.disk)
        delete_fs = "dd if=/dev/zero bs=512 count=512 of=%s" % self.disk
        if process.system(delete_fs, shell=True, ignore_status=True):
            self.fail("Failed to delete filesystem on %s", self.disk)


if __name__ == "__main__":
    main()
