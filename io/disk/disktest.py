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
from avocado import main
from avocado.utils import build
from avocado.utils import memory
from avocado.utils import process
from avocado.utils import lv_utils
from avocado.utils.partition import Partition
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
        softm = SoftwareManager()
        if not softm.check_installed("gcc") and not softm.install("gcc"):
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
        self.disk = self.params.get('disk', default=None)
        self.dirs = self.params.get('dir', default=self.workdir)
        self.fstype = self.params.get('fs', default='ext4')

        gigabytes = int(lv_utils.get_diskspace(self.disk)) // 1073741824
        memory_mb = memory.meminfo.MemTotal.m
        self.chunk_mb = gigabytes * 950
        if memory_mb > self.chunk_mb:
            self.cancel("Chunk size has to be greater or equal to RAM size. "
                        "(%s > %s)" % (self.chunk_mb, memory_mb))

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
            self.part_obj = Partition(self.disk, mountpoint=self.dirs)
            self.log.info("Unmounting the disk/dir if it is already mounted")
            self.part_obj.unmount()
            self.log.info("creating %s fs on %s", self.fstype, self.disk)
            self.part_obj.mkfs(self.fstype)
            self.log.info("mounting %s on %s", self.disk, self.dirs)
            try:
                self.part_obj.mount()
            except PartitionError:
                self.fail("Mounting disk %s on directory %s failed"
                          % (self.disk, self.dirs))

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
            self.log.info("Unmounting disk %s on directory %s",
                          self.disk, self.dirs)
            self.part_obj.unmount()
        self.log.info("Removing the filesystem created on %s", self.disk)
        delete_fs = "dd if=/dev/zero bs=512 count=512 of=%s" % self.disk
        if process.system(delete_fs, shell=True, ignore_status=True):
            self.fail("Failed to delete filesystem on %s", self.disk)


if __name__ == "__main__":
    main()
