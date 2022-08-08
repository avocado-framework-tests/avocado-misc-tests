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
#       : Naresh Bannoth <nbannoth@linux.vnet.ibm.com>
# Based on code by Randy Dunlap <rdunlap@xenotime.net>
#   copyright 2006 Randy Dunlap <rdunlap@xenotime.net>
#   https://github.com/autotest/autotest-client-tests/tree/master/fio

"""
FIO Test
"""

import os
import time
import avocado

from avocado import Test
from avocado.utils import archive
from avocado.utils import build
from avocado.utils import pmem
from avocado.utils import disk
from avocado.utils import dmesg
from avocado.utils import lv_utils, wait
from avocado.utils import process, distro
from avocado.utils import softwareraid
from avocado.utils.partition import Partition
from avocado.utils.software_manager.manager import SoftwareManager
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
        self.dir = self.params.get('dir', default='/mnt')
        self.disk_type = self.params.get('disk_type', default='')
        fstype = self.params.get('fs', default='')
        fs_args = self.params.get('fs_args', default='')
        mnt_args = self.params.get('mnt_args', default='')
        lv_needed = self.params.get('lv', default=False)
        raid_needed = self.params.get('raid', default=False)
        self.fio_file = 'fiotest-image'

        self.fs_create = False
        self.lv_create = False
        self.raid_create = False
        self.devdax_file = None

        if fstype == 'btrfs':
            ver = int(distro.detect().version)
            rel = int(distro.detect().release)
            if distro.detect().name == 'rhel':
                if (ver == 7 and rel >= 4) or ver > 7:
                    self.cancel("btrfs is not supported with \
                                RHEL 7.4 onwards")

        if distro.detect().name in ['Ubuntu', 'debian']:
            pkg_list = ['libaio-dev']
            if fstype == 'btrfs':
                pkg_list.append('btrfs-progs')
        elif distro.detect().name is 'SuSE':
            pkg_list = ['libaio1', 'libaio-devel']
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
        fio_flags = ""
        self.ld_path = ""
        self.raid_name = '/dev/md/sraid'
        self.vgname = 'avocado_vg'
        self.lvname = 'avocado_lv'
        self.err_mesg = []

        if self.disk_type == 'nvdimm':
            self.setup_pmem_disk(mnt_args)
            self.log.info("Building PMDK for NVDIMM fio engines")
            pmdk_url = self.params.get('pmdk_url', default='')
            tar = self.fetch_asset(pmdk_url, expire='7d')
            archive.extract(tar, self.teststmpdir)
            version = os.path.basename(tar.split('.tar.')[0])
            pmdk_src = os.path.join(self.teststmpdir, version)
            build.make(pmdk_src)
            build.make(pmdk_src, extra_args='install prefix=%s' %
                       self.teststmpdir)
            os.chdir(self.sourcedir)
            ext_flags = '`PKG_CONFIG_PATH=%s/lib/pkgconfig pkg-config --cflags\
                    --libs libpmem libpmemblk`' % self.teststmpdir
            self.ld_path = "LD_LIBRARY_PATH=%s/lib" % self.teststmpdir
            out = process.system_output('./configure --extra-cflags='
                                        '"%s"' % ext_flags, shell=True)
            fio_flags = "LDFLAGS='%s'" % ext_flags
            for eng in ['PMDK libpmem', 'PMDK dev-dax', 'libnuma']:
                for line in out.decode().splitlines():
                    if line.startswith(eng) and 'no' in line:
                        self.cancel("PMEM engines not built with fio")

        if not self.disk:
            self.dir = self.workdir

        self.target = self.disk
        self.lv_disk = self.disk
        self.part_obj = Partition(self.disk, mountpoint=self.dir)
        self.sraid = softwareraid.SoftwareRaid(self.raid_name, '0',
                                               self.disk.split(), '1.2')
        dmesg.clear_dmesg()
        if self.disk in disk.get_disks():
            self.pre_cleanup()
            if raid_needed:
                self.create_raid(self.target, self.raid_name)
                self.raid_create = True
                self.target = self.raid_name

            if lv_needed:
                self.lv_disk = self.target
                self.target = self.create_lv(self.target)
                self.lv_create = True

            if fstype:
                self.create_fs(self.target, self.dir, fstype,
                               fs_args, mnt_args)
                self.fs_create = True
        else:
            self.cancel("Missing disk %s in OS" % self.disk)

        build.make(self.sourcedir, extra_args=fio_flags)

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
                    self.plib.run_ndctl_list('-N -r %s' % region)[0],
                    'blockdev')
            else:
                self.plib.create_namespace(
                    region=region, mode='devdax')
                self.devdax_file = "/dev/%s" % self.plib.run_ndctl_list_val(
                    self.plib.run_ndctl_list('-N -r %s' % region)[0],
                    'chardev')

    def pre_cleanup(self):
        """
        cleanup the disk and directory before test starts on it
        """
        self.log.info("Pre_cleaning of disk and diretories...")
        disk_list = ['/dev/mapper/avocado_vg-avocado_lv', self.raid_name,
                     self.disk]
        for disk in disk_list:
            self.delete_fs(disk)
        self.log.info("checking ...lv/vg existance...")
        if lv_utils.lv_check(self.vgname, self.lvname):
            self.log.info("found lv existance... deleting it")
            self.delete_lv()
        elif lv_utils.vg_check(self.vgname):
            self.log.info("found vg existance ... deleting it")
            lv_utils.vg_remove(self.vgname)
        else:
            self.log.info("No VG/LV detected")
        self.log.info("checking for sraid existance...")
        if self.sraid.exists():
            self.log.info("found sraid existance... deleting it")
            self.delete_raid()
        else:
            self.log.info("No softwareraid detected ")
        self.log.info("\n End of pre_cleanup")

    def create_raid(self, l_disk, l_raid_name):
        """
        creates a softwareraid with given raid name on given disk

        :param l_disk: disk name on which raid will be created
        :l_raid_name: name of the softwareraid
        :return: None
        """
        self.log.info("creating softwareraid on {}" .format(l_disk))
        self.sraid = softwareraid.SoftwareRaid(l_raid_name, '0',
                                               l_disk.split(), '1.2')
        self.sraid.create()

    def create_lv(self, l_disk):
        """
        creates a volume group then logical volume on it and returns lv.

        :param l_disk: disk name on which a lv will be created
        :returns: Returns the lv name
        :rtype: str
        """
        lv_size = lv_utils.get_device_total_space(l_disk) / 2330168
        lv_utils.vg_create(self.vgname, l_disk, force=True)
        lv_utils.lv_create(self.vgname, self.lvname, lv_size)
        return '/dev/%s/%s' % (self.vgname, self.lvname)

    def create_fs(self, l_disk, mountpoint, fstype, fs_args='', mnt_args=''):
        """
        umounts the given disk if mounted then creates a filesystem on it
        and then mounts it on given directory

        :param l_disk: disk name on which fs will be created
        :param mountpoint: directory name on which the disk will be mounted
        :param fstype: filesystem type like ext4,xfs,btrfs etc
        :param fs_args: filesystem related extra arguments like -f -b -s etc
        :param mnt_args: mounting arguments like -o etc
        :returns: None
        """
        self.part_obj = Partition(l_disk, mountpoint=mountpoint)
        self.part_obj.unmount()
        self.part_obj.mkfs(fstype, args=fs_args)
        try:
            self.part_obj.mount(args=mnt_args)
        except PartitionError:
            self.fail("Mounting disk %s on directory %s failed"
                      % (l_disk, mountpoint))

    def delete_raid(self):
        """
        it checks for existing of raid and deletes it if exists
        """
        self.log.info("deleting Sraid %s" % self.raid_name)

        def is_raid_deleted():
            self.sraid.stop()
            self.sraid.clear_superblock()
            self.log.info("checking for raid metadata")
            cmd = "wipefs -af %s" % self.disk
            process.system(cmd, shell=True, ignore_status=True)
            if self.sraid.exists():
                return False
            return True
        self.log.info("checking lvm_metadata on %s" % self.raid_name)
        cmd = 'blkid -o value -s TYPE %s' % self.raid_name
        out = process.system_output(cmd, shell=True,
                                    ignore_status=True).decode("utf-8")
        if out == 'LVM2_member':
            cmd = "wipefs -af %s" % self.raid_name
            process.system(cmd, shell=True, ignore_status=True)
        if wait.wait_for(is_raid_deleted, timeout=10):
            self.log.info("software raid  %s deleted" % self.raid_name)
        else:
            self.err_mesg.append("failed to delete raid %s" % self.raid_name)

    def delete_lv(self):
        """
        checks if lv/vg exists and delete them along with its metadata
        if exists.
        """
        def is_lv_deleted():
            lv_utils.lv_remove(self.vgname, self.lvname)
            time.sleep(5)
            lv_utils.vg_remove(self.vgname)
            if lv_utils.lv_check(self.vgname, self.lvname):
                return False
            return True
        if wait.wait_for(is_lv_deleted, timeout=10):
            self.log.info("lv %s deleted" % self.lvname)
        else:
            self.err_mesg.append("lv %s not deleted" % self.lvname)
        # checking and deleteing if lvm_meta_data exists after lv removed
        cmd = 'blkid -o value -s TYPE %s' % self.lv_disk
        out = process.system_output(cmd, shell=True,
                                    ignore_status=True).decode("utf-8")
        if out == 'LVM2_member':
            cmd = "wipefs -af %s" % self.lv_disk
            process.system(cmd, shell=True, ignore_status=True)

    def delete_fs(self, l_disk):
        """
        checks for disk/dir mount, unmount if mounted and checks for
        filesystem exitance and wipe it off after dir/disk unmount.

        :param l_disk: disk name for which you want to check the mount status
        :return: None
        """
        def is_fs_deleted():
            cmd = "wipefs -af %s" % l_disk
            process.system(cmd, shell=True, ignore_status=True)
            if disk.fs_exists(l_disk):
                return False
            return True

        def is_disk_unmounted():
            cmd = "umount %s" % l_disk
            cmd1 = 'umount /dev/mapper/avocado_vg-avocado_lv'
            process.system(cmd, shell=True, ignore_status=True)
            process.system(cmd1, shell=True, ignore_status=True)
            if disk.is_disk_mounted(l_disk):
                return False
            return True

        def is_dir_unmounted():
            cmd = 'umount %s' % self.dir
            process.system(cmd, shell=True, ignore_status=True)
            if disk.is_dir_mounted(self.dir):
                return False
            return True

        self.log.info("checking if disk is mounted.")
        if disk.is_disk_mounted(l_disk):
            self.log.info("%s is mounted, unmounting it ....", l_disk)
            if wait.wait_for(is_disk_unmounted, timeout=10):
                self.log.info("%s unmounted successfully" % l_disk)
            else:
                self.err_mesg.append("%s unmount failed", l_disk)
        else:
            self.log.info("disk %s not mounted." % l_disk)
        self.log.info("checking if dir %s is mounted." % self.dir)
        if disk.is_dir_mounted(self.dir):
            self.log.info("%s is mounted, unmounting it ....", self.dir)
            if wait.wait_for(is_dir_unmounted, timeout=10):
                self.log.info("%s unmounted successfully" % self.dir)
            else:
                self.err_mesg.append("failed to unount %s", self.dir)
        else:
            self.log.info("dir %s not mounted." % self.dir)
        self.log.info("checking if fs exists in {}" .format(l_disk))
        if disk.fs_exists(l_disk):
            self.log.info("found fs on %s, removing it....", l_disk)
            if wait.wait_for(is_fs_deleted, timeout=10):
                self.log.info("fs removed successfully..")
            else:
                self.err_mesg.append("failed to delete fs on %s", l_disk)
        else:
            self.log.info("No fs detected on %s" % self.disk)

    def test(self):
        """
        Execute 'fio' with appropriate parameters.
        """
        self.log.info("Test will run on %s", self.dir)
        fio_job = self.params.get('fio_job', default='fio-simple.job')

        # if fs is present create a file on that fs, if no fs
        # self.dirs = path to disk, thus a filename is not needed
        if self.fs_create:
            filename = "%s/%s" % (self.dir, self.fio_file)
        elif self.devdax_file:
            filename = self.devdax_file
        elif self.disk:
            filename = self.target
        else:
            filename = self.dir
        cmd = '%s %s/fio %s --filename=%s' % (self.ld_path,
                                              self.sourcedir,
                                              self.get_data(fio_job),
                                              filename)
        self.log.info("running fio test using command : %s" % cmd)
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
            self.delete_fs(self.target)
        if self.lv_create:
            self.delete_lv()
        if self.raid_create:
            self.delete_raid()
        dmesg.clear_dmesg()
        if self.err_mesg:
            self.warn("test failed due to following errors %s" % self.err_mesg)
