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
# Author: Narasimhan V <sim@linux.vnet.ibm.com>
# Copyright: 2016 Red Hat, Inc.
# Author: Lukas Doktor <ldoktor@redhat.com>
#
# Based on the code by:
#
# Copyright: 2012 Intra2net
# Author: Plamen Dimitrov (plamen.dimitrov@intra2net.com)

"""
Test that automatically takes shapshots from created logical volumes
using a given policy.

For details about the policy see README.
"""
import os

import avocado
from avocado import Test
from avocado.utils import disk, distro, lv_utils
from avocado.utils.disk import DiskError
from avocado.utils.software_manager import SoftwareManager


class Lvsetup(Test):

    """
    Test class for creating logical volumes.
    """
    def setUp(self):
        """
        Check existence of input PV,VG, LV and snapshots prior to Test.
        """
        pkgs = [""]
        smm = SoftwareManager()
        self.disk = self.params.get('lv_disks', default=None)
        self.vg_name = self.params.get('vg_name', default='avocado_vg')
        self.lv_name = self.params.get('lv_name', default='avocado_lv')
        self.fs_name = self.params.get('fs', default='ext4').lower()
        self.lv_size = self.params.get('lv_size', default='0')
        if self.fs_name == 'xfs':
            pkgs = ['xfsprogs']
        if self.fs_name == 'btrfs':
            ver = int(distro.detect().version)
            rel = int(distro.detect().release)
            if distro.detect().name == 'rhel':
                if (ver == 7 and rel >= 4) or ver > 7:
                    self.cancel("btrfs is not supported with RHEL 7.4 onwards")
            if distro.detect().name == 'SuSE':
                pkgs = ['btrfsprogs']
            else:
                pkgs = ['btrfs-progs']
        if distro.detect().name in ['Ubuntu', 'debian']:
            pkgs.extend(['lvm2'])

        for pkg in pkgs:
            if pkg and not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel("Package %s could not be installed" % pkg)

        self.lv_snap_name = self.params.get(
            'lv_snapshot_name', default='avocado_sn')

        if lv_utils.vg_check(self.vg_name):
            self.cancel('Volume group %s already exists' % self.vg_name)
        if lv_utils.lv_check(self.vg_name, self.lv_name):
            self.cancel('Logical Volume %s already exists' % self.lv_name)
        if lv_utils.lv_check(self.vg_name, self.lv_snap_name):
            self.cancel('Snapshot %s already exists' % self.lv_snap_name)

        self.mount_loc = os.path.join(self.workdir, 'mountpoint')
        if not os.path.isdir(self.mount_loc):
            os.makedirs(self.mount_loc)

        if self.lv_size:
            # converting to megabytes
            if self.lv_size.endswith('G'):
                self.lv_size = int(self.lv_size.strip('G')) * 1024
            elif self.lv_size.endswith('M'):
                self.lv_size = int(self.lv_size.strip('M'))
            else:
                self.lv_size = int(self.lv_size) / 1024 / 1024

        if self.disk:
            disk_size = lv_utils.get_devices_total_space(self.disk.split())
            # converting bytes to megabytes
            disk_size = disk_size / (1024 * 1024)

            if self.lv_size:
                if self.lv_size > disk_size:
                    self.cancel("lv size provided more than size of disks")
            else:
                self.lv_size = disk_size

            self.device = self.disk
        else:
            if not self.lv_size:
                self.lv_size = 1024 * 1024 * 1024

            try:
                self.device = disk.create_loop_device(self.lv_size)
            except DiskError:
                self.cancel("Could not create loop device")

            # converting bytes to megabytes
            self.lv_size = self.lv_size / (1024 * 1024)

        # Using only 45% of lv size, to accomodate lv snapshot also.
        self.lv_size = (self.lv_size * 45) / 100

        self.lv_snapshot_size = self.params.get('lv_snapshot_size',
                                                default=self.lv_size)

    @avocado.fail_on(lv_utils.LVException)
    def create_lv(self):
        """
        General logical volume setup.

        A volume group with given name is created in the ramdisk. It then
        creates a logical volume.
        """
        lv_utils.vg_create(self.vg_name, self.device)
        if not lv_utils.vg_check(self.vg_name):
            self.fail('Volume group %s not created' % self.vg_name)
        lv_utils.lv_create(self.vg_name, self.lv_name, self.lv_size)
        if not lv_utils.lv_check(self.vg_name, self.lv_name):
            self.fail('Logical Volume %s not created' % self.lv_name)

    @avocado.fail_on(lv_utils.LVException)
    def delete_lv(self):
        """
        Clear all PV,VG, LV and snapshots created by the test.
        """
        if lv_utils.lv_check(self.vg_name, self.lv_name):
            lv_utils.lv_remove(self.vg_name, self.lv_name)
        if lv_utils.vg_check(self.vg_name):
            lv_utils.vg_remove(self.vg_name)

    @avocado.fail_on(lv_utils.LVException)
    def mount_unmount_lv(self):
        """
        Mounts and unmounts the filesystem on the logical volume.
        """
        lv_utils.lv_mount(self.vg_name, self.lv_name, self.mount_loc)
        lv_utils.lv_umount(self.vg_name, self.lv_name)

    @avocado.fail_on(lv_utils.LVException)
    def test(self):
        """
        A volume group with given name is created in the ramdisk. It then
        creates a logical volume, mounts and unmounts it.
        """
        self.create_lv()
        lv_utils.lv_mount(self.vg_name, self.lv_name, self.mount_loc,
                          create_filesystem=self.fs_name)
        lv_utils.lv_umount(self.vg_name, self.lv_name)
        self.mount_unmount_lv()

    @avocado.fail_on(lv_utils.LVException)
    def test_vg_reactivate(self):
        """
        Deactivate, export, import and activate a volume group.
        """
        self.create_lv()
        lv_utils.lv_mount(self.vg_name, self.lv_name, self.mount_loc,
                          create_filesystem=self.fs_name)
        lv_utils.lv_umount(self.vg_name, self.lv_name)
        lv_utils.vg_reactivate(self.vg_name, export=True)
        self.mount_unmount_lv()

    @avocado.fail_on(lv_utils.LVException)
    def test_lv_snapshot(self):
        """
        Takes a snapshot from the logical and merges snapshot with the
        logical volume.
        """
        self.create_lv()
        lv_utils.lv_mount(self.vg_name, self.lv_name, self.mount_loc,
                          create_filesystem=self.fs_name)
        lv_utils.lv_umount(self.vg_name, self.lv_name)
        lv_utils.lv_take_snapshot(self.vg_name, self.lv_name,
                                  self.lv_snap_name,
                                  self.lv_snapshot_size)
        lv_utils.lv_revert(self.vg_name, self.lv_name, self.lv_snap_name)
        self.mount_unmount_lv()

    def tearDown(self):
        """
        Cleans up loop device.
        """
        self.delete_lv()
        if not self.disk:
            disk.delete_loop_device(self.device)
