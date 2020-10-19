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
from avocado.utils import (archive, build, disk, distro, lv_utils, process,
                           softwareraid)
from avocado.utils.partition import Partition, PartitionError
from avocado.utils.software_manager import SoftwareManager


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
        self.fstype = self.params.get('fs', default='')
        self.fs_create = False
        lv_needed = self.params.get('lv', default=False)
        self.lv_create = False
        raid_needed = self.params.get('raid', default=False)
        self.raid_create = False
        smm = SoftwareManager()
        packages = ['gcc']
        if self.fstype == 'btrfs':
            ver = int(distro.detect().version)
            rel = int(distro.detect().release)
            if distro.detect().name == 'rhel':
                if (ver == 7 and rel >= 4) or ver > 7:
                    self.cancel("btrfs is not supported with RHEL 7.4 onwards")
            if distro.detect().name == 'Ubuntu':
                packages.extend(['btrfs-tools'])
        if raid_needed:
            packages.append('mdadm')
        for package in packages:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel("%s package required for this test." % package)
        locations = ["https://github.com/mkuoppal/tiobench/archive/master.zip"]
        tarball = self.fetch_asset("tiobench.zip", locations=locations)
        archive.extract(tarball, self.teststmpdir)
        os.chdir(os.path.join(self.teststmpdir, "tiobench-master"))
        build.make(".")
        self.disk = self.params.get('disk', default=None)
        self.target = self.disk
        if self.disk is not None:
            if self.disk in disk.get_disks():
                if raid_needed:
                    raid_name = '/dev/md/mdsraid'
                    self.create_raid(self.disk, raid_name)
                    self.raid_create = True
                    self.disk = raid_name
                    self.target = self.disk

                if lv_needed:
                    self.disk = self.create_lv(self.disk)
                    self.lv_create = True
                    self.target = self.disk

                if self.fstype:
                    self.target = self.workdir
                    self.create_fs(self.disk, self.target, self.fstype)
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
            self.fail("Failed to delete filesystem on %s" % l_disk)

    def test(self):
        """
        Test execution with necessary arguments.
        :params blocks: The blocksize in Bytes to use. Defaults to 4096.
        :params threads: The number of concurrent test threads.
        :params size: The total size in MBytes of the files may use together.
        :params num_runs: This number specifies over how many runs
                          each test should be averaged.
        """
        blocks = self.params.get('blocks', default=4096)
        threads = self.params.get('threads', default=10)
        size = self.params.get('size', default=1024)
        num_runs = self.params.get('numruns', default=2)

        self.log.info("Test will run on %s", self.target)
        self.whiteboard = process.system_output('perl ./tiobench.pl '
                                                '--target {} --block={} '
                                                '--threads={} --numruns={} '
                                                '-size={}'
                                                .format(self.target, blocks,
                                                        threads, num_runs,
                                                        size)).decode("utf-8")

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
