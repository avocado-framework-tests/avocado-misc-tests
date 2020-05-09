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
# Based on code by Randy Dunlap <rdunlap@xenotime.net>
#   copyright 2006 Randy Dunlap <rdunlap@xenotime.net>
#   https://github.com/autotest/autotest-client-tests/tree/master/fio

"""
FIO Test
"""

import os

from avocado import Test
from avocado import main
from avocado.utils import archive
from avocado.utils import build
from avocado.utils import disk
from avocado.utils import lv_utils
from avocado.utils import process, distro
from avocado.utils.partition import Partition
from avocado.utils.software_manager import SoftwareManager
from avocado.utils.partition import PartitionError


class FioTest(Test):

    """
    fio is an I/O tool meant to be used both for benchmark and
    stress/hardware verification.

    :see: http://freecode.com/projects/fio

    :param fio_tarbal: name of the tarbal of fio suite located in deps path
    :param fio_job: config defining set of executed tests located in deps path
    """

    def setUp(self):
        """
        Build 'fio'.
        """
        default_url = "https://brick.kernel.dk/snaps/fio-git-latest.tar.gz"
        url = self.params.get('fio_tool_url', default=default_url)
        self.disk = self.params.get('disk', default=None)
        fstype = self.params.get('fs', default=None)
        if fstype == 'btrfs':
            ver = int(distro.detect().version)
            rel = int(distro.detect().release)
            if distro.detect().name == 'rhel':
                if (ver == 7 and rel >= 4) or ver > 7:
                    self.cancel("btrfs is not supported with \
                                RHEL 7.4 onwards")
        self.fs_create = False
        lv_needed = self.params.get('lv', default=False)
        self.lv_create = False

        if distro.detect().name in ['Ubuntu', 'debian']:
            pkg_list = ['libaio-dev']
            if fstype == 'btrfs':
                pkg_list.append('btrfs-progs')
        else:
            pkg_list = ['libaio', 'libaio-devel']

        smm = SoftwareManager()
        for pkg in pkg_list:
            if pkg and not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel("Package %s is missing and could not be installed"
                            % pkg)

        if not self.disk:
            self.disk = self.workdir

        if self.disk in disk.get_disks():
            if lv_needed:
                self.disk = self.create_lv(self.disk)
                self.lv_create = True
                self.dirs = self.disk
            else:
                self.dirs = self.disk

            if fstype:
                self.dirs = self.workdir
                self.create_fs(self.disk, self.dirs, fstype)
                self.fs_create = True
            else:
                self.dirs = self.disk

        else:
            self.dirs = self.disk

        tarball = self.fetch_asset(url)
        archive.extract(tarball, self.teststmpdir)
        self.sourcedir = os.path.join(self.teststmpdir, "fio")
        build.make(self.sourcedir)
        self.fio_file = 'fiotest-image'

    def create_lv(self, l_disk):
        vgname = 'avocado_vg'
        lvname = 'avocado_lv'
        lv_size = int(lv_utils.get_diskspace(l_disk)) / 2330168
        lv_utils.vg_create(vgname, disk)
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
            self.fail("Failed to delete filesystem on %s" % l_disk)

    def test(self):
        """
        Execute 'fio' with appropriate parameters.
        """
        self.log.info("Test will run on %s", self.dirs)
        fio_job = self.params.get('fio_job', default='fio-simple.job')
        cmd = '%s/fio %s %s --filename=%s' % (self.sourcedir,
                                              self.get_data(fio_job),
                                              self.dirs, self.fio_file)
        if process.system(cmd, ignore_status=True, shell=True):
            self.fail("fio run failed")

    def tearDown(self):
        '''
        Cleanup of disk used to perform this test
        '''
        if self.fs_create:
            self.delete_fs(self.disk)
        if self.lv_create:
            self.delete_lv()
        if os.path.exists(self.fio_file):
            os.remove(self.fio_file)


if __name__ == "__main__":
    main()
