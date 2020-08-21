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
from avocado.utils import archive
from avocado.utils import build
from avocado.utils import disk
from avocado.utils import lv_utils
from avocado.utils import softwareraid
from avocado.utils import process, distro
from avocado.utils.partition import Partition
from avocado.utils.software_manager import SoftwareManager
from avocado.utils.partition import PartitionError


class Bonnie(Test):

    """
    Bonnie++ is a benchmark suite that is aimed at performing a number
    of simple tests of hard drive and file system performance.
    """

    def setUp(self):
        """
        Use distro provided  bonnie++ bin
        if not available Build bonnie++ from below
        Source:
        http://www.coker.com.au/bonnie++/experimental/bonnie++-1.03e.tgz
        """
        fstype = self.params.get('fs', default='')
        self.fs_create = False
        lv_needed = self.params.get('lv', default=False)
        self.lv_create = False
        raid_needed = self.params.get('raid', default=False)
        self.raid_create = False

        smm = SoftwareManager()
        # Install the package from web
        deps = ['gcc', 'make']
        if distro.detect().name == 'Ubuntu':
            deps.extend(['g++'])
        else:
            deps.extend(['gcc-c++'])
        if fstype == 'btrfs':
            ver = int(distro.detect().version)
            rel = int(distro.detect().release)
            if distro.detect().name == 'rhel':
                if (ver == 7 and rel >= 4) or ver > 7:
                    self.cancel("btrfs not supported with RHEL 7.4 onwards")
            elif distro.detect().name == 'Ubuntu':
                deps.extend(['btrfs-tools'])
        if raid_needed:
            deps.append('mdadm')

        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel("%s package required for this test" % package)

        if process.system("which bonnie++", ignore_status=True):
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
        self.uid_to_use = self.params.get('uid-to-use',
                                          default=getpass.getuser())
        self.number_to_stat = self.params.get('number-to-stat', default=2048)
        self.data_size = self.params.get('data_size_to_pass', default=0)

        self.scratch_dir = self.disk
        if self.disk is not None:
            if self.disk in disk.get_disks():
                if raid_needed:
                    raid_name = '/dev/md/mdsraid'
                    self.create_raid(self.disk, raid_name)
                    self.raid_create = True
                    self.disk = raid_name
                    self.scratch_dir = self.disk

                if lv_needed:
                    self.disk = self.create_lv(self.disk)
                    self.lv_create = True
                    self.scratch_dir = self.disk

                if fstype:
                    self.scratch_dir = self.workdir
                    self.create_fs(self.disk, self.scratch_dir, fstype)
                    self.fs_create = True

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
        self.part_obj = Partition(l_disk,
                                  mountpoint=mountpoint)
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
        if self.disk is not None:
            if self.fs_create:
                self.delete_fs(self.disk)
            if self.lv_create:
                self.delete_lv()
            if self.raid_create:
                self.delete_raid()
