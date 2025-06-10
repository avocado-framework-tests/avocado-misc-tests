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
# Author: Vaishnavi Bhat <vaishnavi@linux.vnet.ibm.com>
#       : Naresh Bannoth <nbannoth@linux.vnet.ibm.com>
#
# https://github.com/autotest/autotest-client-tests/tree/master/ltp

"""
LTP fsstress test
"""

import os
import time
from avocado import Test
from avocado.utils import build
from avocado.utils import disk
from avocado.utils import dmesg
from avocado.utils import lv_utils
from avocado.utils import wait
from avocado.utils import softwareraid
from avocado.utils import distro
from avocado.utils import process, archive
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils.partition import Partition
from avocado.utils.partition import PartitionError


class LtpFs(Test):

    '''
    Using LTP (Linux Test Project) testsuite to run Filesystem related tests
    '''

    def setUp(self):
        '''
        To check and install dependencies for the test
        '''
        self.err_mesg = []
        device = self.params.get('disk', default=None)
        self.dir = self.params.get('dir', default=None)
        self.fstype = self.params.get('fs', default='')
        self.fs_create = False
        lv_needed = self.params.get('lv', default=False)
        self.lv_create = False
        raid_needed = self.params.get('raid', default=False)
        self.raid_create = False
        self.fsstress_count = self.params.get('fsstress_loop', default='1')
        self.n_val = self.params.get('n_val', default='100')
        self.p_val = self.params.get('p_val', default='100')

        if device is not None:
            self.disk = disk.get_absolute_disk_path(device)
            if self.disk not in disk.get_all_disk_paths():
                self.cancel("Missing disk %s in OS" % self.disk)
        else:
            self.cancel("Please Provide valid device name")

        if not self.dir:
            self.dir = self.workdir

        smm = SoftwareManager()
        detected_distro = distro.detect()
        packages = ['gcc', 'make', 'automake', 'autoconf']
        if raid_needed:
            packages.append('mdadm')
        for package in packages:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel("%s is needed for the test to be run" % package)

        if self.fstype == 'btrfs':
            if detected_distro.name == 'Ubuntu':
                ver = int(detected_distro.version.split('.')[0])
            else:
                ver = int(detected_distro.version)
            rel = int(detected_distro.release)
            if detected_distro.name == 'rhel':
                if (ver == 7 and rel >= 4) or ver > 7:
                    self.cancel("btrfs is not supported with \
                                RHEL 7.4 onwards")
            if detected_distro.name == 'Ubuntu':
                if not smm.check_installed("btrfs-progs") and not \
                        smm.install("btrfs-progs"):
                    self.cancel('btrfs-progs is needed for the test to be run')

        self.raid_name = '/dev/md/sraid'
        self.vgname = 'avocado_vg'
        self.lvname = 'avocado_lv'
        self.target = self.disk
        self.lv_disk = self.disk
        self.part_obj = Partition(self.disk, mountpoint=self.dir)
        self.sw_raid = softwareraid.SoftwareRaid(self.raid_name, '0',
                                                 self.disk.split(), '1.2')
        dmesg.clear_dmesg()

        self.pre_cleanup()
        if raid_needed:
            self.create_raid(self.disk, self.raid_name)
            self.raid_create = True
            self.target = self.raid_name

        if lv_needed:
            self.lv_disk = self.target
            self.target = self.create_lv(self.target)
            self.lv_create = True

        if self.fstype:
            self.create_fs(self.target, self.dir, self.fstype)
            self.fs_create = True

        url = "https://github.com/linux-test-project/ltp/"
        url += "archive/master.zip"
        tarball = self.fetch_asset("ltp-master.zip",
                                   locations=[url], expire='7d')
        archive.extract(tarball, self.teststmpdir)
        ltp_dir = os.path.join(self.teststmpdir, "ltp-master")
        os.chdir(ltp_dir)
        build.make(ltp_dir, extra_args='autotools')
        process.system('./configure', ignore_status=True)
        build.make(ltp_dir)
        build.make(ltp_dir, extra_args='install')
        fsstress_dir = os.path.join(ltp_dir,
                                    'testcases/kernel/fs/fsstress')
        os.chdir(fsstress_dir)

    def create_raid(self, l_disk, l_raid_name):
        """
        creates a softwareraid with given raid name on given disk

        :param l_disk: disk name on which raid will be created
        :l_raid_name: name of the softwareraid
        :return: None
        """
        self.log.info("creating softwareraid on {}" .format(l_disk))
        self.sw_raid = softwareraid.SoftwareRaid(l_raid_name, '0',
                                                 l_disk.split(), '1.2')
        self.sw_raid.create()

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

    def create_fs(self, l_disk, mountpoint, fstype):
        """
        umounts the given disk if mounted then creates a filesystem on it
        and then mounts it on given directory

        :param l_disk: disk name on which fs will be created
        :param mountpoint: directory name on which the disk will be mounted
        :param fstype: filesystem type like ext4,xfs,btrfs etc
        :returns: None
        """
        self.part_obj = Partition(l_disk,
                                  mountpoint=mountpoint)
        self.part_obj.unmount()
        self.part_obj.mkfs(fstype)
        try:
            self.part_obj.mount()
        except PartitionError:
            self.fail("Mounting disk %s on directory %s failed"
                      % (l_disk, mountpoint))

    def pre_cleanup(self):
        """
        cleanup the disk and directory before test starts on it
        """
        self.log.info("Pre_cleaning of disk and directories...")
        disk_list = ['/dev/mapper/avocado_vg-avocado_lv', self.raid_name,
                     self.disk]
        for disk in disk_list:
            self.delete_fs(disk)
        self.log.info("checking ...lv/vg existence...")
        if lv_utils.lv_check(self.vgname, self.lvname):
            self.log.info("found lv existence... deleting it")
            self.delete_lv()
        elif lv_utils.vg_check(self.vgname):
            self.log.info("found vg existence ... deleting it")
            lv_utils.vg_remove(self.vgname)
        self.log.info("checking for softwareraid existence...")
        if self.sw_raid.exists():
            self.log.info("found softwareraid existence... deleting it")
            self.delete_raid()
        else:
            self.log.info("No softwareraid detected ")
        self.log.info("\n End of pre_cleanup")

    def delete_raid(self):
        """
        it checks for existing of raid and deletes it if exists
        """
        self.log.info("deleting Sraid %s" % self.raid_name)

        def is_raid_deleted():
            self.sw_raid.stop()
            self.sw_raid.clear_superblock()
            self.log.info("checking for raid metadata")
            cmd = "wipefs -af %s" % self.disk
            process.system(cmd, shell=True, ignore_status=True)
            if self.sw_raid.exists():
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
            self.err_mesg.extend(['failed to delete sraid %s' % self.raid_name])

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
            self.log.info("lv %s deleted", self.lvname)
        else:
            self.err_mesg.extend(['failed to delete lv %s' % self.lvname])
        # checking and deleting if lvm_meta_data exists after lv removed
        cmd = 'blkid -o value -s TYPE %s' % self.lv_disk
        out = process.system_output(cmd, shell=True,
                                    ignore_status=True).decode("utf-8")
        if out == 'LVM2_member':
            cmd = "wipefs -af %s" % self.lv_disk
            process.system(cmd, shell=True, ignore_status=True)

    def delete_fs(self, l_disk):
        """
        checks for disk/dir mount, unmount if mounted and checks for
        filesystem existence and wipe it off after dir/disk unmount.

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
                self.err_mesg.extend(['%s unmount failed', l_disk])
        else:
            self.log.info("disk %s not mounted." % l_disk)
        self.log.info("checking if dir %s is mounted." % self.dir)
        if disk.is_dir_mounted(self.dir):
            self.log.info("%s is mounted, unmounting it ....", self.dir)
            if wait.wait_for(is_dir_unmounted, timeout=10):
                self.log.info("%s unmounted successfully" % self.dir)
            else:
                self.err_mesg.extend(['failed to unount %s', self.dir])
        else:
            self.log.info("dir %s not mounted." % self.dir)
        self.log.info("checking if fs exists in {}" .format(l_disk))
        if disk.fs_exists(l_disk):
            self.log.info("found fs on %s, removing it....", l_disk)
            if wait.wait_for(is_fs_deleted, timeout=10):
                self.log.info("fs removed successfully..")
            else:
                self.err_mesg.extend([f'failed to delete fs on {l_disk}'])
        else:
            self.log.info(f'No fs detected on {self.disk}')

    def test_fsstress_run(self):
        '''
        Downloads LTP, compiles, installs and runs filesystem
        tests on a user specified disk
        '''
        arg = (" -d %s -n %s -p %s -r -l %s"
               % (self.dir, self.n_val, self.p_val, self.fsstress_count))
        self.log.info("Args = %s" % arg)
        dmesg.clear_dmesg()
        cmd = './fsstress %s' % arg
        process.run(cmd, ignore_status=True)
        cmd = "dmesg --level=err"
        if process.system_output(cmd, shell=True,
                                 ignore_status=True, sudo=False):
            self.fail("FSSTRESS test failed")

    def tearDown(self):
        '''
        Cleanup of disk used to perform this test
        '''
        if self.fs_create:
            self.delete_fs(self.target)
        if self.lv_create:
            self.delete_lv()
        if self.raid_create:
            self.delete_raid()
        dmesg.clear_dmesg()
        if self.err_mesg:
            self.log.warning("test failed due to following errors %s" % self.err_mesg)
