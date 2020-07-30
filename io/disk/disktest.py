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

from avocado import Test
from avocado.utils import build
from avocado.utils import memory
from avocado.utils import process, distro
from avocado.utils import disk
from avocado.utils import lv_utils
from avocado.utils.partition import Partition
from avocado.utils import softwareraid
from avocado.utils.software_manager import SoftwareManager
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
        self.softm = SoftwareManager()
        if not self.softm.check_installed("gcc") and not self.softm.install("gcc"):
            self.cancel('Gcc is needed for the test to be run')
        # Log of all the disktest processes
        self.disk_log = os.path.abspath(os.path.join(self.outputdir,
                                                     "log.txt"))

        self._init_params()
        self._compile_disktest()

    def _init_params(self):
        """
        Retrieves and checks the test params
        """
        self.fs_create = False
        lv_needed = self.params.get('lv', default=False)
        self.lv_create = False
        raid_needed = self.params.get('raid', default=False)
        self.raid_create = False
        self.disk = self.params.get('disk', default=None)
        self.fstype = self.params.get('fs', default='ext4')
        self.dirs = self.disk
        if self.fstype == 'btrfs':
            ver = int(distro.detect().version)
            rel = int(distro.detect().release)
            if distro.detect().name == 'rhel':
                if (ver == 7 and rel >= 4) or ver > 7:
                    self.cancel("btrfs is not supported with \
                                RHEL 7.4 onwards")
        if raid_needed:
            if not self.softm.check_installed("mdadm") \
               and not self.softm.install("mdadm"):
                self.cancel('mdadm is needed for the test to be run')
        gigabytes = lv_utils.get_device_total_space(self.disk) // 1073741824
        memory_mb = memory.meminfo.MemTotal.m
        self.chunk_mb = gigabytes * 950

        self.no_chunks = 1024 * gigabytes // self.chunk_mb
        if self.no_chunks == 0:
            self.cancel("Free disk space is lower than chunk size (%s, %s)"
                        % (1024 * gigabytes, self.chunk_mb))

        self.log.info("Test will use %s chunks %sMB each in %sMB RAM using %s "
                      "GB of disk space on %s dirs (%s).", self.no_chunks,
                      self.chunk_mb, memory_mb,
                      self.no_chunks * self.chunk_mb, len(self.dirs),
                      self.dirs)

        if self.disk is not None:
            if self.disk in disk.get_disks():
                if raid_needed:
                    raid_name = '/dev/md/mdsraid'
                    self.create_raid(self.disk, raid_name)
                    self.raid_create = True
                    self.disk = raid_name
                    self.dirs = self.disk

                if lv_needed:
                    self.disk = self.create_lv(self.disk)
                    self.lv_create = True
                    self.dirs = self.disk

                if self.fstype:
                    self.dirs = self.workdir
                    self.create_fs(self.disk, self.dirs, self.fstype)
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
            self.fail("Failed to delete filesystem on %s", l_disk)

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
        """
        cmd = ("%s/disktest -m %d -f %s/testfile.%d -i -S >> \"%s\" 2>&1" %
               (self.teststmpdir, self.chunk_mb, disk, chunk, self.disk_log))

        proc = process.get_sub_process_klass(cmd)(cmd, shell=True,
                                                  verbose=False)
        pid = proc.start()
        return pid, proc

    def test(self):
        """
        Runs one iteration of disktest.

        """
        procs = []
        errors = []
        for i in range(self.no_chunks):
            self.log.debug("Testing chunk %s...", i)
            procs.append(self.one_disk_chunk(self.dirs, i))
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
        for disk in getattr(self, "dirs", []):
            for filename in glob.glob("%s/testfile.*" % disk):
                os.remove(filename)
        if self.disk is not None:
            if self.fs_create:
                self.delete_fs(self.disk)
            if self.lv_create:
                self.delete_lv()
            if self.raid_create:
                self.delete_raid()
