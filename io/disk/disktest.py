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
# Copyright: 2016 IBM
# Author: Nosheen Pathan <nopathan@linux.vnet.ibm.com>
# Copyright: 2016 Red Hat, Inc.
# Author: Lukas Doktor <ldoktor@redhat.com>
#       : Naresh Bannoth <nbannoth@linux.vnet.ibm.com>
#
# Based on code by Martin Bligh (mbligh@google.com)
#   Copyright: 2007 Google, Inc.
#   https://github.com/autotest/autotest-client-tests/tree/master/disktest
"""
Disktest test
"""

import glob
import os
import shutil
import time

from avocado import Test
from avocado.utils import build
from avocado.utils import memory
from avocado.utils import dmesg
from avocado.utils import process, distro
from avocado.utils import disk
from avocado.utils import lv_utils
from avocado.utils import wait
from avocado.utils.partition import Partition
from avocado.utils import softwareraid
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils.partition import PartitionError


class Disktest(Test):

    """
    Avocado module for disktest.
    Pattern test of the disk, using unique signatures for each block and each
    iteration of the test. Designed to check for data corruption issues in the
    disk and disk controller.
    It writes 50MB/s of 500KB size ops.
    """

    def setUp(self):
        """
        Verifies if we have gcc to compile disktest.

        :param disk: Disk to be used in test.
        :param dir: Directory of used in test. When the target does not exist,
                    it's created.
        :param gigabytes: Disk space that will be used for the test to run.
        :param chunk_mb: Size of the portion of the disk used to run the test.
                         Cannot be smaller than the total amount of RAM.
        """
        smm = SoftwareManager()
        if not smm.check_installed("gcc") and not smm.install("gcc"):
            self.cancel('Gcc is needed for the test to be run')
        # Log of all the disktest processes
        self.disk_log = os.path.abspath(os.path.join(self.outputdir,
                                                     "log.txt"))
        self.fs_create = False
        self.raid_needed = self.params.get('raid', default=False)
        self.raid_create = False
        self.disk = self.params.get('disk', default=None)
        self.dir = self.params.get('dir', default=None)
        self.fstype = self.params.get('fs', default='ext4')
        self.raid_name = '/dev/md/sraid'
        self.err_mesg = []

        if self.fstype == 'btrfs':
            ver = int(distro.detect().version)
            rel = int(distro.detect().release)
            if distro.detect().name == 'rhel':
                if (ver == 7 and rel >= 4) or ver > 7:
                    self.cancel("btrfs is not supported with \
                                RHEL 7.4 onwards")
        if self.raid_needed:
            if not smm.check_installed("mdadm") \
               and not smm.install("mdadm"):
                self.cancel('mdadm is needed for the test to be run')

        self.vgname = 'avocado_vg'
        self.lvname = 'avocado_lv'
        self.target = self.disk
        self.part_obj = Partition(self.disk, mountpoint=self.dir)
        self.sw_raid = softwareraid.SoftwareRaid(self.raid_name, '0',
                                                 self.disk.split(), '1.2')

        self._init_params()
        self._compile_disktest()

    def _init_params(self):
        """
        Retrieves and checks the test params
        """
        gigabytes = lv_utils.get_device_total_space(self.target) // 1073741824
        memory_mb = memory.meminfo.MemTotal.m
        self.log.info("memory_mb=%s" % memory_mb)
        self.chunk_mb = gigabytes * 950

        self.no_chunks = 1024 * gigabytes // self.chunk_mb
        if self.no_chunks == 0:
            self.cancel("Free disk space is lower than chunk size (%s, %s)"
                        % (1024 * gigabytes, self.chunk_mb))

        self.log.info("Test will use %s chunks %sMB each in %sMB RAM using %s "
                      "GB of disk space on %s dir (%s).", self.no_chunks,
                      self.chunk_mb, memory_mb,
                      self.no_chunks * self.chunk_mb, len(self.dir),
                      self.dir)

        dmesg.clear_dmesg()
        self.pre_cleanup()
        if self.disk is not None:
            if self.disk in disk.get_disks():
                if self.raid_needed:
                    self.create_raid(self.target, self.raid_name)
                    self.raid_create = True
                    self.target = self.raid_name

                if self.fstype:
                    self.create_fs(self.target, self.dir, self.fstype)
                    self.fs_create = True
            else:
                self.cancel("Missing disk %s in OS" % self.disk)
        else:
            self.cancel("please provide a valid disk")

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

    def create_fs(self, l_disk, mountpoint, fstype):
        """
        umounts the given disk if mounted then creates a filesystem on it
        and then mounts it on given directory

        :param l_disk: disk name on which fs will be created
        :param mountpoint: directory name on which the disk will be mounted
        :param fstype: filesystem type like ext4,xfs,btrfs etc
        :returns: None
        """
        self.part_obj = Partition(l_disk, mountpoint=mountpoint)
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
        self.log.info("Pre_cleaning of disk and diretories...")
        disk_list = ['/dev/mapper/avocado_vg-avocado_lv', self.raid_name,
                     self.disk]
        for disk1 in disk_list:
            self.delete_fs(disk1)
        self.log.info("checking ...lv/vg existance...")
        if lv_utils.lv_check(self.vgname, self.lvname):
            self.log.info("found lv existance... deleting it")
            self.delete_lv()
        elif lv_utils.vg_check(self.vgname):
            self.log.info("found vg existance ... deleting it")
            lv_utils.vg_remove(self.vgname)
        self.log.info("checking for softwareraid existance...")
        if self.sw_raid.exists():
            self.log.info("found softwareraid existance... deleting it")
            self.delete_raid()
        else:
            self.log.info("No softwareraid detected ")
        self.log.info("\n End of pre_cleanup")

    def _compile_disktest(self):
        """
        Compiles the disktest
        """
        c_file = self.get_data("disktest.c")
        shutil.copy(c_file, self.teststmpdir)
        build.make(self.teststmpdir, extra_args="disktest",
                   env={"CFLAGS": "-O2 -Wall -D_FILE_OFFSET_BITS=64 "
                                  "-D _GNU_SOURCE"})

    def one_disk_chunk(self, disk, chunk):
        """
        Tests one part of the disk by spawning a disktest instance.

        :param disk: Directory (usually a mountpoint).
        :param chunk: Portion of the disk used.
        :returns: Returns process ID and process
        """
        cmd = ("%s/disktest -m %d -f %s/testfile.%d -i -S >> \"%s\" 2>&1" %
               (self.teststmpdir, self.chunk_mb, disk, chunk, self.disk_log))
        proc = process.get_sub_process_klass(cmd)(cmd, shell=True,
                                                  verbose=False)
        pid = proc.start()
        return pid, proc

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
            self.err_mesg.append("failed to delete sraid %s" % self.raid_name)

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
            self.err_mesg.append("failed to delete lv %s" % self.lvname)
        # checking and deleteing if lvm_meta_data exists after lv removed
        cmd = 'blkid -o value -s TYPE %s' % self.disk
        out = process.system_output(cmd, shell=True,
                                    ignore_status=True).decode("utf-8")
        if out == 'LVM2_member':
            cmd = "wipefs -af %s" % self.disk
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
                self.err_mesg.append(f'failed to delete fs on {l_disk}')
        else:
            self.log.info(f'No fs detected on {self.disk}')

    def test(self):
        """
        Runs one iteration of disktest.
        """
        procs = []
        errors = []
        for i in range(self.no_chunks):
            self.log.debug("Testing chunk %s...", i)
            procs.append(self.one_disk_chunk(self.dir, i))
            for pid, proc in procs:
                if proc.wait():
                    errors.append(str(pid))
        if errors:
            self.fail("The %s pid(s) failed, please check the logs and %s"
                      " for details." % (", ".join(errors), self.disk_log))

    def tearDown(self):
        """
        To clean all the testfiles generated
        """
        for disk1 in getattr(self, "dir", []):
            for filename in glob.glob("%s/testfile.*" % disk1):
                os.remove(filename)
        if self.disk is not None:
            if self.fs_create:
                self.delete_fs(self.target)
            if self.raid_create:
                self.delete_raid()
        dmesg.clear_dmesg()
        if self.err_mesg:
            self.warn("test failed due to following errors %s" % self.err_mesg)
