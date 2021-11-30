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
# Author: Harish <harisrir@linux.vnet.ibm.com>
#
# Based on code by Martin J. Bligh <mbligh@google.com>
#   copyright 2006 Google, Inc.
#   https://github.com/autotest/autotest-client-tests/tree/master/dbench

import os
import re
import multiprocessing
import json

from avocado import Test
from avocado.utils import archive
from avocado.utils import process
from avocado.utils import build
from avocado.utils import disk
from avocado.utils import distro
from avocado.utils import lv_utils
from avocado.utils import softwareraid
from avocado.utils.partition import Partition
from avocado.utils.partition import PartitionError
from avocado.utils.software_manager import SoftwareManager


class Dbench(Test):

    """
    Dbench is a tool to generate I/O workloads to either a filesystem or to a
    networked CIFS or NFS server.
    Dbench is a utility to benchmark a system based on client workload
    profiles.
    """

    def setUp(self):
        '''
        Build Dbench
        Source:
        http://samba.org/ftp/tridge/dbench/dbench-3.04.tar.gz
        '''
        fstype = self.params.get('fs', default='')
        self.fs_create = False
        lv_needed = self.params.get('lv', default=False)
        self.lv_create = False
        raid_needed = self.params.get('raid', default=False)
        self.raid_create = False
        self.disk = self.params.get('disk', default=None)
        if not self.disk:
            self.cancel("Provide the test disks to proceed !")
        self.md_name = self.params.get('raid_name', default='md127')
        self.mountpoint = self.params.get('dir', default='/mnt')
        self.disk_obj = Partition(self.disk, mountpoint=self.mountpoint)
        self.pre_cleanup()
        self.clear_disk(self.disk_obj, self.disk)
        if not os.path.exists(self.mountpoint):
            os.mkdir(self.mountpoint)
        sm = SoftwareManager()
        pkgs = ["gcc", "patch"]
        if raid_needed:
            pkgs.append('mdadm')
        for pkg in pkgs:
            if not sm.check_installed(pkg) and not sm.install(pkg):
                self.error('%s is needed for the test to be run' % pkg)

        if fstype == 'btrfs':
            ver = int(distro.detect().version)
            rel = int(distro.detect().release)
            if distro.detect().name == 'rhel':
                if (ver == 7 and rel >= 4) or ver > 7:
                    self.cancel("btrfs is not supported with \
                                RHEL 7.4 onwards")
            if distro.detect().name == 'Ubuntu':
                if not sm.check_installed("btrfs-tools") and not \
                        sm.install("btrfs-tools"):
                    self.cancel('btrfs-tools is needed for the test to be run')

        self.results = []
        tarball = self.fetch_asset(
            'http://samba.org/ftp/tridge/dbench/dbench-3.04.tar.gz')
        archive.extract(tarball, self.teststmpdir)
        cb_version = os.path.basename(tarball.split('.tar.')[0])
        self.sourcedir = os.path.join(self.teststmpdir, cb_version)
        os.chdir(self.sourcedir)
        patch = self.params.get('patch', default='dbench_startup.patch')
        process.run('patch -p1 < %s' % self.get_data(patch), shell=True)
        process.run('./configure')
        build.make(self.sourcedir)
        if self.disk is not None:
            if self.disk in disk.get_disks():
                if raid_needed:
                    raid_name = '/dev/%s' % self.md_name
                    self.create_raid(self.disk, raid_name)
                    self.raid_create = True
                    self.disk = raid_name
                if lv_needed:
                    self.disk = self.create_lv(self.disk)
                    self.lv_create = True
                if fstype:
                    self.create_fs(self.disk, fstype)
                    self.fs_create = True

    def pre_cleanup(self):
        umount_dir = "umount -f %s" % self.mountpoint
        process.system(umount_dir, shell=True, ignore_status=True)
        delete_lv = "lvremove -f /dev/mapper/avocado_vg-avocado_lv"
        process.system(delete_lv, shell=True, ignore_status=True)
        delete_vg = "vgremove -f avocado_vg"
        process.system(delete_vg, shell=True, ignore_status=True)
        delete_rd = 'mdadm --stop /dev/%s' % self.md_name
        process.system(delete_rd, shell=True, ignore_status=True)

    def clear_disk(self, obj, disk):
        obj.unmount()
        delete_fs = "dd if=/dev/zero bs=512 count=512 of=%s" % disk
        if process.system(delete_fs, shell=True, ignore_status=False):
            self.fail("Failed to delete filesystem on %s", disk)

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
        return '/dev/mapper/%s-%s' % (vgname, lvname)

    def delete_lv(self):
        vgname = 'avocado_vg'
        lvname = 'avocado_lv'
        lv_utils.lv_remove(vgname, lvname)
        lv_utils.vg_remove(vgname)

    def create_fs(self, l_disk, fstype):
        self.part_obj = Partition(l_disk, mountpoint=self.mountpoint)
        self.part_obj.unmount(force=True)
        self.part_obj.mkfs(fstype)
        try:
            self.part_obj.mount()
        except PartitionError:
            self.fail("Mounting disk %s on directory %s failed"
                      % (l_disk, self.mountpoint))

    def test(self):
        '''
        Test Execution with necessary args
        '''
        nprocs = self.params.get('nprocs', default=None)
        seconds = self.params.get('seconds', default=60)
        args = self.params.get('args', default='')
        if not nprocs:
            nprocs = multiprocessing.cpu_count()
        loadfile = os.path.join(self.sourcedir, 'client.txt')
        cmd = '%s/dbench %s %s -D %s -c %s -t %d' % (self.sourcedir, nprocs,
                                                     args, self.mountpoint, loadfile,
                                                     seconds)
        process.run(cmd)

        self.results = process.system_output(cmd).decode("utf-8")
        pattern = re.compile(r"Throughput (.*?) MB/sec (.*?) procs")
        (throughput, procs) = pattern.findall(self.results)[0]
        self.whiteboard = json.dumps({'throughput': throughput,
                                      'procs': procs})

    def tearDown(self):
        '''
        Cleanup of disk used to perform this test
        '''
        if self.disk is not None:
            if self.fs_create:
                self.clear_disk(self.part_obj, self.disk)
            if self.lv_create:
                self.delete_lv()
            if self.raid_create:
                self.delete_raid()
