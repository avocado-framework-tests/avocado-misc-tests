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
#
# https://github.com/autotest/autotest-client-tests/tree/master/ltp

"""
LTP fsstress test
"""


import os
from avocado import Test
from avocado.utils import build
from avocado.utils import process, archive
from avocado.utils.software_manager import SoftwareManager
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
        smm = SoftwareManager()
        for package in ['gcc', 'make', 'automake', 'autoconf']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel("%s is needed for the test to be run" % package)
        self.disk = self.params.get('disk', default=None)
        self.mount_point = self.params.get('dir', default=self.workdir)
        self.script = self.params.get('script')
        fstype = self.params.get('fs', default='ext4')
        self.fsstress_run = self.params.get('fsstress_loop', default='1')

        if self.disk is not None:
            self.part_obj = Partition(self.disk, mountpoint=self.mount_point)
            self.log.info("Unmounting the disk/dir if it is already mounted")
            self.part_obj.unmount()
            self.log.info("creating %s file system on %s", fstype, self.disk)
            self.part_obj.mkfs(fstype)
            self.log.info("mounting %s on %s", self.disk, self.mount_point)
            try:
                self.part_obj.mount()
            except PartitionError:
                self.fail("Mounting disk %s on directory %s failed"
                          % (self.disk, self.mount_point))

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

    def test_fsstress_run(self):
        '''
        Downloads LTP, compiles, installs and runs filesystem
        tests on a user specified disk
        '''
        if self.script == 'fsstress':
            arg = (" -d %s -n 500 -p 500 -r -l %s"
                   % (self.mount_point, self.fsstress_run))
            self.log.info("Args = %s" % arg)
            cmd = "dmesg -C"
            process.system(cmd, shell=True, ignore_status=True, sudo=True)
            cmd = './%s %s' % (self.script, arg)
            result = process.run(cmd, ignore_status=True)
            cmd = "dmesg --level=err"
            if process.system_output(cmd, shell=True,
                                     ignore_status=True, sudo=False):
                self.fail("FSSTRESS test failed")

    def tearDown(self):
        '''
        Cleanup of disk used to perform this test
        '''
        if self.disk is not None:
            self.log.info("Unmounting disk %s on directory %s",
                          self.disk, self.mount_point)
            self.part_obj.unmount()
            self.log.info("Removing the filesystem created on %s", self.disk)
            delete_fs = "dd if=/dev/zero bs=512 count=512 of=%s" % self.disk
            if process.system(delete_fs, shell=True, ignore_status=True):
                self.fail("Failed to delete filesystem on %s", self.disk)
