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
from avocado.utils import disk as utils_disk
from avocado.utils import memory
from avocado.utils import process
from avocado.utils.software_manager import SoftwareManager


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
        :param disks: List of directories of used in test. In case only string
                      is used it's split using ','. When the target is not
                      directory, it's created.
        :param gigabytes: Disk space that will be used for the test to run.
        :param chunk_mb: Size of the portion of the disk used to run the test.
                        Cannot be smaller than the total amount of RAM.
        :param source: name of the source file located in deps path
        :param make: name of the makefile file located in deps path
        """
        softm = SoftwareManager()
        if not softm.check_installed("gcc") and not softm.install("gcc"):
            self.skip('Gcc is needed for the test to be run')
        # Log of all the disktest processes
        self.disk_log = os.path.abspath(os.path.join(self.outputdir,
                                                     "log.txt"))

        self._init_params()
        self._compile_disktest()

    def _init_params(self):
        """
        Retrieves and checks the test params
        """
        disks = self.params.get('disks', default=None)
        if disks is None:   # Avocado does not accept lists in params.get()
            disks = [self.workdir]
        elif isinstance(disks, basestring):  # Allow specifying disks as str
            disks = disks.split(',')    # it's string pylint: disable=E1101
        for disk in disks:  # Disks have to be mounted dirs
            if not os.path.isdir(disk):
                os.makedirs(disk)
        self.disks = disks

        memory_mb = memory.memtotal() / 1024
        self.chunk_mb = self.params.get('chunk_mb', default=None)
        if self.chunk_mb is None:   # By default total RAM
            self.chunk_mb = memory_mb
        if self.chunk_mb == 0:
            self.chunk_mb = 1
        if memory_mb > self.chunk_mb:
            self.skip("Chunk size has to be greater or equal to RAM size. "
                      "(%s > %s)" % (self.chunk_mb, memory_mb))

        gigabytes = self.params.get('gigabytes', default=None)
        if gigabytes is None:
            free = 100  # cap it at 100GB by default
            for disk in self.disks:
                free = min(utils_disk.freespace(disk) / 1073741824, free)
            gigabytes = free

        self.no_chunks = 1024 * gigabytes / self.chunk_mb
        if self.no_chunks == 0:
            self.skip("Free disk space is lower than chunk size (%s, %s)"
                      % (1024 * gigabytes, self.chunk_mb))

        self.log.info("Test will use %s chunks %sMB each in %sMB RAM using %s "
                      "GB of disk space on %s disks (%s).", self.no_chunks,
                      self.chunk_mb, memory_mb,
                      self.no_chunks * self.chunk_mb, len(self.disks),
                      self.disks)

    def _compile_disktest(self):
        """
        Compiles the disktest
        """
        c_file = os.path.join(self.datadir, "disktest.c")
        shutil.copy(c_file, self.srcdir)
        build.make(self.srcdir, extra_args="disktest",
                   env={"CFLAGS": "-O2 -Wall -D_FILE_OFFSET_BITS=64 "
                                  "-D _GNU_SOURCE"})

    def one_disk_chunk(self, disk, chunk):
        """
        Tests one part of the disk by spawning a disktest instance.
        :param disk: Directory (usually a mountpoint).
        :param chunk: Portion of the disk used.
        """
        cmd = ("%s/disktest -m %d -f %s/testfile.%d -i -S >>%s 2>&1" %
               (self.srcdir, self.chunk_mb, disk, chunk, self.disk_log))

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
        for i in xrange(self.no_chunks):
            self.log.debug("Testing chunk %s...", i)
            for disk in self.disks:
                procs.append(self.one_disk_chunk(disk, i))
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
        for disk in getattr(self, "disks", []):
            for filename in glob.glob("%s/testfile.*" % disk):
                os.remove(filename)


if __name__ == "__main__":
    main()
