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
from avocado.utils import archive
from avocado.utils import build
from avocado.utils import disk
from avocado.utils import lv_utils
from avocado.utils import softwareraid
from avocado.utils import process, distro
from avocado.utils.partition import Partition
from avocado.utils.software_manager.manager import SoftwareManager
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
        lv_needed = self.params.get('lv', default=False)
        self.lv_create = False
        raid_needed = self.params.get('raid', default=False)
        self.raid_create = False
        smm = SoftwareManager()
        if raid_needed:
            if not smm.check_installed('mdadm') and not smm.install('mdadm'):
                self.cancel("mdadm is needed for the test to be run")
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
        self.fstype = self.params.get('fs', default='')
        self.fs_create = False

        if self.fstype == 'btrfs':
            ver = int(distro.detect().version)
            rel = int(distro.detect().release)
            if distro.detect().name == 'rhel':
                if (ver == 7 and rel >= 4) or ver > 7:
                    self.cancel("btrfs is not supported with \
                                RHEL 7.4 onwards")
            if distro.detect().name == 'Ubuntu':
                if not smm.check_installed("btrfs-tools") and not \
                        smm.install("btrfs-tools"):
                    self.cancel('btrfs-tools is needed for the test to be run')

        self.dirs = self.disk
        if self.disk is not None:
            if self.disk in disk.get_disks():
                if raid_needed:
                    raid_name = '/dev/md/mdsraid'
                    self.create_raid(self.disk, raid_name)
                    self.raid_create = True
                    self.disk = raid_name
                    self.dirs = self.disk

                if lv_needed:
                    self.disk = self.create_lv(self.disk)
                    self.lv_create = True
                    self.dirs = self.disk

                if self.fstype:
                    self.dirs = self.workdir
                    self.create_fs(self.disk, self.dirs, self.fstype)
                    self.fs_create = True
            self.link = "/tmp/link"
            os.symlink(self.dirs, self.link)

    def create_raid(self, l_disk, l_raid_name):
        self.sraid = softwareraid.SoftwareRaid(l_raid_name, '0',
                                               l_disk.split(), '1.2')
        self.sraid.create()

    def delete_raid(self):
        self.sraid.stop()
        self.sraid.clear_superblock()

    def create_lv(self, l_disk):
        vgname = 'avocado_vg'
        lvname = 'avocado_lv'
        lv_size = lv_utils.get_device_total_space(l_disk) / 2330168
        lv_utils.vg_create(vgname, l_disk)
        lv_utils.lv_create(vgname, lvname, lv_size)
        return '/dev/%s/%s' % (vgname, lvname)

    def delete_lv(self):
        vgname = 'avocado_vg'
        lvname = 'avocado_lv'
        lv_utils.lv_remove(vgname, lvname)
        lv_utils.vg_remove(vgname)

    def create_fs(self, l_disk, mountpoint, fstype):
        self.part_obj = Partition(l_disk, mountpoint=mountpoint)
        self.part_obj.unmount()
        self.part_obj.mkfs(fstype)
        try:
            self.part_obj.mount()
        except PartitionError:
            self.fail("Mounting disk %s on directory %s failed"
                      % (l_disk, mountpoint))

    def delete_fs(self, l_disk):
        self.part_obj.unmount()
        delete_fs = "dd if=/dev/zero bs=512 count=512 of=%s" % l_disk
        if process.system(delete_fs, shell=True, ignore_status=True):
            self.fail("Failed to delete filesystem on %s", l_disk)

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
            if self.fs_create:
                self.delete_fs(self.disk)
            if self.lv_create:
                self.delete_lv()
            if self.raid_create:
                self.delete_raid()
