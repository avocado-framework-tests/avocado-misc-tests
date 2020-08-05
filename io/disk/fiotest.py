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
import avocado

from avocado import Test
from avocado.utils import archive
from avocado.utils import build
from avocado.utils import pmem
from avocado.utils import disk
from avocado.utils import lv_utils
from avocado.utils import process, distro
from avocado.utils import softwareraid
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
        self.disk_type = self.params.get('disk_type', default='')
        fs_args = self.params.get('fs_args', default='')
        mnt_args = self.params.get('mnt_args', default='')
        self.fio_file = 'fiotest-image'

        self.fs_create = False
        self.lv_create = False
        self.raid_create = False

        fstype = self.params.get('fs', default='')
        if fstype == 'btrfs':
            ver = int(distro.detect().version)
            rel = int(distro.detect().release)
            if distro.detect().name == 'rhel':
                if (ver == 7 and rel >= 4) or ver > 7:
                    self.cancel("btrfs is not supported with \
                                RHEL 7.4 onwards")

        lv_needed = self.params.get('lv', default=False)
        raid_needed = self.params.get('raid', default=False)

        if distro.detect().name in ['Ubuntu', 'debian']:
            pkg_list = ['libaio-dev']
            if fstype == 'btrfs':
                pkg_list.append('btrfs-progs')
        else:
            pkg_list = ['libaio', 'libaio-devel']
            if self.disk_type == 'nvdimm':
                pkg_list.extend(['autoconf', 'pkg-config'])
                if distro.detect().name == 'SuSE':
                    pkg_list.extend(['ndctl', 'libnuma-devel',
                                     'libndctl-devel'])
                else:
                    pkg_list.extend(['ndctl', 'daxctl', 'numactl-devel',
                                     'ndctl-devel', 'daxctl-devel'])
        if raid_needed:
            pkg_list.append('mdadm')

        smm = SoftwareManager()
        for pkg in pkg_list:
            if pkg and not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel("Package %s is missing and could not be installed"
                            % pkg)

        tarball = self.fetch_asset(url)
        archive.extract(tarball, self.teststmpdir)
        self.sourcedir = os.path.join(self.teststmpdir, "fio")

        if self.disk_type == 'nvdimm':
            self.setup_pmem_disk(mnt_args)
            self.log.info("Building PMDK for NVDIMM fio engines")
            pmdk_url = self.params.get('pmdk_url', default='')
            tar = self.fetch_asset(pmdk_url, expire='7d')
            archive.extract(tar, self.teststmpdir)
            version = os.path.basename(tar.split('.tar.')[0])
            pmdk_src = os.path.join(self.teststmpdir, version)
            build.make(pmdk_src)
            build.make(pmdk_src, extra_args='install prefix=/usr')
            os.chdir(self.sourcedir)
            out = process.system_output(
                "./configure --prefix=/usr", shell=True)
            for eng in ['PMDK libpmem', 'PMDK dev-dax', 'libnuma']:
                for line in out.decode().splitlines():
                    if line.startswith(eng) and 'no' in line:
                        self.cancel("PMEM engines not built with fio")

        if not self.disk:
            self.disk = self.workdir

        self.dirs = self.disk
        if self.disk in disk.get_disks():
            if raid_needed:
                raid_name = '/dev/md/mdsraid'
                self.create_raid(self.disk, raid_name)
                self.raid_create = True
                self.disk = raid_name

            if lv_needed:
                self.disk = self.create_lv(self.disk)
                self.lv_create = True
                self.dirs = self.disk

            if fstype:
                self.dirs = self.workdir
                self.create_fs(self.disk, self.dirs, fstype, fs_args, mnt_args)
                self.fs_create = True

        build.make(self.sourcedir)

    @avocado.fail_on(pmem.PMemException)
    def setup_pmem_disk(self, mnt_args):
        if not self.disk:
            self.plib = pmem.PMem()
            regions = sorted(self.plib.run_ndctl_list(
                '-R'), key=lambda i: i['size'], reverse=True)
            if not regions:
                self.plib.enable_region()
                regions = sorted(self.plib.run_ndctl_list(
                    '-R'), key=lambda i: i['size'], reverse=True)
            region = self.plib.run_ndctl_list_val(regions[0], 'dev')
            if self.plib.run_ndctl_list("-N -r %s" % region):
                self.plib.destroy_namespace(region=region, force=True)
            if 'dax' in mnt_args:
                self.plib.create_namespace(region=region)
                self.disk = "/dev/%s" % self.plib.run_ndctl_list_val(
                    self.plib.run_ndctl_list('-N -r %s' % region)[0], 'blockdev')
            else:
                self.plib.create_namespace(
                    region=region, mode='devdax')
                self.fio_file = "/dev/%s" % self.plib.run_ndctl_list_val(
                    self.plib.run_ndctl_list('-N -r %s' % region)[0], 'chardev')

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

    def create_fs(self, l_disk, mountpoint, fstype, fs_args='', mnt_args=''):
        self.part_obj = Partition(l_disk, mountpoint=mountpoint)
        self.part_obj.unmount()
        self.part_obj.mkfs(fstype, args=fs_args)
        try:
            self.part_obj.mount(args=mnt_args)
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

        # if fs is present create a file on that fs, if no fs
        # self.dirs = path to disk, thus a filename is not needed
        if self.fs_create:
            cmd = '%s/fio %s --filename=%s/%s' % (self.sourcedir,
                                                  self.get_data(fio_job),
                                                  self.dirs, self.fio_file)
        else:
            cmd = '%s/fio %s --filename=%s' % (self.sourcedir,
                                               self.get_data(fio_job),
                                               self.dirs)
        status = process.system(cmd, ignore_status=True, shell=True)
        if status:
            # status of 3 is a common warning with iscsi disks but fio
            # process completes successfully so throw a warning not
            # a fail. For other nonzero statuses we should fail.
            if status == 3:
                self.log.warning("Warnings during fio run")
            else:
                self.fail("fio run failed")

    def tearDown(self):
        '''
        Cleanup of disk used to perform this test
        '''
        if os.path.exists(self.fio_file):
            os.remove(self.fio_file)
        if self.fs_create:
            self.delete_fs(self.disk)
        if self.lv_create:
            self.delete_lv()
        if self.raid_create:
            self.delete_raid()
