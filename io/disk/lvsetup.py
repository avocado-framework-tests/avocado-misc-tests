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
from avocado import main
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import lv_utils
from avocado.utils import distro


class Lvsetup(Test):

    """
    Test class for creating logical volumes.
    """
    ramdisks = []

    def setUp(self):
        """
        Check existence of input PV,VG, LV and snapshots prior to Test.
        """
        pkg = ""
        smm = SoftwareManager()
        self.disk = self.params.get('disks', default=None)
        vg_name = self.params.get('vg_name', default='avocado_vg')
        lv_name = self.params.get('lv_name', default='avocado_lv')
        self.fs_name = self.params.get('fs', default='ext4').lower()
        if self.fs_name == 'xfs':
            pkg = 'xfsprogs'
        if self.fs_name == 'btrfs':
            if distro.detect().name == 'SuSE':
                pkg = 'btrfsprogs'
            else:
                pkg = 'btrfs-progs'
        if pkg and not smm.check_installed(pkg) and not smm.install(pkg):
            self.cancel("Package %s could not be installed" % pkg)
        lv_snapshot_name = self.params.get(
            'lv_snapshot_name', default='avocado_sn')
        self.ramdisk_basedir = self.params.get(
            'ramdisk_basedir', default=os.path.join(self.workdir, 'ramdisk'))
        self.ramdisk_sparse_filename = self.params.get(
            'ramdisk_sparse_filename', default='virtual_hdd')

        if lv_utils.vg_check(vg_name):
            self.cancel('Volume group %s already exists' % vg_name)
        self.vg_name = vg_name
        if lv_utils.lv_check(vg_name, lv_name):
            self.cancel('Logical Volume %s already exists' % lv_name)
        self.lv_name = lv_name
        if lv_utils.lv_check(vg_name, lv_snapshot_name):
            self.cancel('Snapshot %s already exists' % lv_snapshot_name)
        self.mount_loc = os.path.join(self.workdir, 'mountpoint')
        if not os.path.isdir(self.mount_loc):
            os.makedirs(self.mount_loc)
        self.lv_snapshot_name = lv_snapshot_name

        if self.disk:
            # converting bytes to megabytes, and using only 45% of the size
            self.lv_size = int(lv_utils.get_diskspace(self.disk)) / 2330168
        else:
            self.lv_size = '1G'
        self.lv_size = self.params.get('lv_size', default=self.lv_size)
        self.lv_snapshot_size = self.params.get('lv_snapshot_size',
                                                default=self.lv_size)
        self.ramdisk_vg_size = self.params.get('ramdisk_vg_size',
                                               default=self.lv_size)

    @avocado.fail_on(lv_utils.LVException)
    def create_lv(self):
        """
        General logical volume setup.

        A volume group with given name is created in the ramdisk. It then
        creates a logical volume.
        """
        self.ramdisks.append(lv_utils.vg_ramdisk(self.disk, self.vg_name,
                                                 self.ramdisk_vg_size,
                                                 self.ramdisk_basedir,
                                                 self.ramdisk_sparse_filename))
        lv_utils.lv_create(self.vg_name, self.lv_name, self.lv_size)
        lv_utils.lv_mount(self.vg_name, self.lv_name, self.mount_loc,
                          create_filesystem=self.fs_name)
        lv_utils.lv_umount(self.vg_name, self.lv_name)

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
        self.mount_unmount_lv()

    @avocado.fail_on(lv_utils.LVException)
    def test_vg_recreate(self):
        """
        Deactivate, export, import and activate a volume group.
        """
        self.create_lv()
        lv_utils.vg_reactivate(self.vg_name, export=True)
        self.mount_unmount_lv()

    @avocado.fail_on(lv_utils.LVException)
    def test_lv_snapshot(self):
        """
        Takes a snapshot from the logical and merges snapshot with the
        logical volume.
        """
        self.create_lv()
        lv_utils.lv_take_snapshot(self.vg_name, self.lv_name,
                                  self.lv_snapshot_name,
                                  self.lv_snapshot_size)
        lv_utils.lv_revert(self.vg_name, self.lv_name, self.lv_snapshot_name)
        self.mount_unmount_lv()

    def tearDown(self):
        """
        Clear all PV,VG, LV and snapshots created by the test.
        """
        # Remove created VG and unmount from base directory
        errs = []
        for ramdisk in self.ramdisks:
            try:
                lv_utils.vg_ramdisk_cleanup(*ramdisk)
            except Exception as exc:
                errs.append("Fail to cleanup ramdisk %s: %s" % (ramdisk, exc))
        if errs:
            self.error("\n".join(errs))


if __name__ == "__main__":
    main()
