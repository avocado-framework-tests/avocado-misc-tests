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


import os

from avocado import Test
from avocado import main
from avocado.utils import archive
from avocado.utils import build
from avocado.utils import process, distro
from avocado.utils.partition import Partition
from avocado.utils.software_manager import SoftwareManager


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
        default_url = "http://brick.kernel.dk/snaps/fio-2.1.10.tar.gz"
        url = self.params.get('fio_tool_url', default=default_url)
        self.disk = self.params.get('disk', default=None)
        self.dir = self.params.get('dir', default=self.srcdir)
        fstype = self.params.get('fs', default='ext4')
        tarball = self.fetch_asset(url)
        archive.extract(tarball, self.teststmpdir)
        fio_version = os.path.basename(tarball.split('.tar.')[0])
        self.sourcedir = os.path.join(self.teststmpdir, fio_version)
        build.make(self.sourcedir)

        smm = SoftwareManager()
        if fstype == 'btrfs':
            if distro.detect().name == 'Ubuntu':
                if not smm.check_installed("btrfs-tools") and not \
                        smm.install("btrfs-tools"):
                    self.skip('btrfs-tools is needed for the test to be run')

        if self.disk is not None:
            self.part_obj = Partition(self.disk, mountpoint=self.dir)
            self.log.info("Unmounting disk/dir before creating file system")
            self.part_obj.unmount()
            self.log.info("creating file system")
            self.part_obj.mkfs(fstype)
            self.log.info("Mounting disk %s on directory %s",
                          self.disk, self.dir)
            self.part_obj.mount()

    def test(self):
        """
        Execute 'fio' with appropriate parameters.
        """
        self.log.info("Test will run on %s", self.dir)
        fio_job = self.params.get('fio_job', default='fio-simple.job')
        self.fio_file = 'fiotest-image'
        cmd = '%s/fio %s %s --filename=%s' % (self.sourcedir,
                                              os.path.join(
                                                  self.datadir, fio_job),
                                              self.dir, self.fio_file)
        process.system(cmd)

    def tearDown(self):
        '''
        Cleanup of disk used to perform this test
        '''
        if self.disk is not None:
            self.log.info("Unmounting directory %s", self.dir)
            self.part_obj.unmount()
        if os.path.exists(self.fio_file):
            os.remove(self.fio_file)


if __name__ == "__main__":
    main()
