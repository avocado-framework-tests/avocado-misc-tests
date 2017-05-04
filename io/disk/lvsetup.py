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
        self.disk = self.params.get('disk', default=None)
        vg_name = self.params.get('vg_name', default='avocado_vg')
        lv_name = self.params.get('lv_name', default='avocado_lv')
        self.lv_size = self.params.get('lv_size', default='1G')
        self.fs_name = self.params.get('fs', default='ext4').lower()
        if self.fs_name == 'xfs':
            pkg = 'xfsprogs'
        if self.fs_name == 'btrfs':
            if distro.detect().name == 'SuSE':
                pkg = 'btrfsprogs'
            else:
                pkg = 'btrfs-progs'
        if pkg and not smm.check_installed(pkg) and not smm.install(pkg):
            self.skip("Package %s is missing and could not be installed" % pkg)
        lv_snapshot_name = self.params.get(
            'lv_snapshot_name', default='avocado_sn')
        self.lv_snapshot_size = self.params.get(
            'lv_snapshot_size', default='1G')
        self.ramdisk_vg_size = self.params.get(
            'ramdisk_vg_size', default='10000')
        self.ramdisk_basedir = self.params.get(
            'ramdisk_basedir', default=self.workdir)
        self.ramdisk_sparse_filename = self.params.get(
            'ramdisk_sparse_filename', default='virtual_hdd')

        if lv_utils.vg_check(vg_name):
            self.skip('Volume group %s already exists' % vg_name)
        self.vg_name = vg_name
        if lv_utils.lv_check(vg_name, lv_name):
            self.skip('Logical Volume %s already exists' % lv_name)
        self.lv_name = lv_name
        if lv_utils.lv_check(vg_name, lv_snapshot_name):
            self.skip('Snapshot %s already exists' % lv_snapshot_name)
        self.mount_loc = self.srcdir
        self.lv_snapshot_name = lv_snapshot_name

    @avocado.fail_on(lv_utils.LVException)
    def test_snapshot(self):
        """
        General logical volume setup.

        A volume group with given name is created in the ramdisk. It then
        creates a logical volume. Takes a snapshot from the logical and
        merges snapshot with the logical volume.
        """
        self.ramdisks.append(lv_utils.vg_ramdisk(self.disk, self.vg_name,
                                                 self.ramdisk_vg_size,
                                                 self.ramdisk_basedir,
                                                 self.ramdisk_sparse_filename))
        lv_utils.lv_create(self.vg_name, self.lv_name, self.lv_size)
        lv_utils.lv_mount(self.vg_name, self.lv_name, self.mount_loc,
                          create_filesystem=self.fs_name)
        lv_utils.lv_umount(self.vg_name, self.lv_name)
        lv_utils.lv_take_snapshot(self.vg_name, self.lv_name,
                                  self.lv_snapshot_name,
                                  self.lv_snapshot_size)
        lv_utils.lv_revert(self.vg_name, self.lv_name, self.lv_snapshot_name)

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
