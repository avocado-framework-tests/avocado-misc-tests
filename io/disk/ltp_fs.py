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
# Author: Harsha Thyagaraja <harshkid@linux.vnet.ibm.com>
#
# Based on code by Martin Bligh <mbligh@google.com>
# copyright 2006 Google, Inc.
# https://github.com/autotest/autotest-client-tests/tree/master/ltp

"""
LTP Filesystem tests
"""


import os

from avocado import Test
from avocado.utils import (archive, build, disk, distro, lv_utils, process,
                           softwareraid)
from avocado.utils.partition import Partition, PartitionError
from avocado.utils.software_manager import SoftwareManager


class LtpFs(Test):

    '''
    Using LTP (Linux Test Project) testsuite to run Filesystem related tests
    '''

    def setUp(self):
        '''
        To check and install dependencies for the test
        '''
        self.fs_create = False
        lv_needed = self.params.get('lv', default=False)
        self.lv_create = False
        raid_needed = self.params.get('raid', default=False)
        self.raid_create = False
        smm = SoftwareManager()
        packages = ['gcc', 'make', 'automake', 'autoconf']
        if raid_needed:
            packages.append('mdadm')
        for package in packages:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel("%s is needed for the test to be run" % package)
        self.disk = self.params.get('disk', default=None)
        self.script = self.params.get('script')
        fstype = self.params.get('fs', default='')
        self.args = self.params.get('args', default='')

        if fstype == 'btrfs':
            ver = int(distro.detect().version)
            rel = int(distro.detect().release)
            if distro.detect().name == 'rhel':
                if (ver == 7 and rel >= 4) or ver > 7:
                    self.cancel("btrfs is not supported with \
                                RHEL 7.4 onwards")

        self.mount_point = self.disk
        if self.disk is not None:
            if self.disk in disk.get_disks():
                if raid_needed:
                    raid_name = '/dev/md/mdsraid'
                    self.create_raid(self.disk, raid_name)
                    self.raid_create = True
                    self.disk = raid_name
                    self.mount_point = self.disk

                if lv_needed:
                    self.disk = self.create_lv(self.disk)
                    self.lv_create = True
                    self.mount_point = self.disk

                if fstype:
                    self.mount_point = self.workdir
                    self.create_fs(self.disk, self.mount_point, fstype)
                    self.fs_create = True

        url = "https://github.com/linux-test-project/ltp/"
        url += "archive/master.zip"
        tarball = self.fetch_asset("ltp-master.zip",
                                   locations=[url], expire='7d')
        archive.extract(tarball, self.teststmpdir)
        ltp_dir = os.path.join(self.teststmpdir, "ltp-master")
        os.chdir(ltp_dir)
        build.make(ltp_dir, extra_args='autotools')
        self.ltpbin_dir = os.path.join(ltp_dir, 'bin')
        if not os.path.isdir(self.ltpbin_dir):
            os.mkdir(self.ltpbin_dir)
            process.system('./configure --prefix=%s' %
                           self.ltpbin_dir, ignore_status=True)
            build.make(ltp_dir)
            build.make(ltp_dir, extra_args='install')

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
            self.fail("Failed to delete filesystem on %s" % l_disk)

    def test_fs_run(self):
        '''
        Downloads LTP, compiles, installs and runs filesystem
        tests on a user specified disk
        '''
        if self.script == 'runltp':
            logfile = os.path.join(self.logdir, 'ltp.log')
            failcmdfile = os.path.join(self.logdir, 'failcmdfile')
            self.args += (" -q -p -l %s -C %s -d %s"
                          % (logfile, failcmdfile, self.mount_point))
            self.log.info("Args = %s", self.args)
            cmd = '%s %s' % (os.path.join(self.ltpbin_dir, self.script),
                             self.args)
            result = process.run(cmd, ignore_status=True)
            # Walk the stdout and try detect failed tests from lines
            # like these:
            # aio01       5  TPASS  :  Test 5: 10 reads and
            # writes in  0.000022 sec
            # vhangup02    1  TFAIL  :  vhangup02.c:88:
            # vhangup() failed, errno:1
            # and check for fail_status The first part contain test name
            fail_status = ['TFAIL', 'TBROK', 'TWARN']
            split_lines = (line.split(None, 3)
                           for line in result.stdout.splitlines())
            failed_tests = [items[0] for items in split_lines
                            if len(items) == 4 and items[2] in fail_status]
            if failed_tests:
                self.fail("LTP tests failed: %s" % ", ".join(failed_tests))
            elif result.exit_status != 0:
                self.fail("No test failures detected, but LTP finished with %s"
                          % (result.exit_status))

    def tearDown(self):
        '''
        Cleanup of disk used to perform this test
        '''
        if self.disk is not None:
            if self.fs_create:
                self.delete_fs(self.disk)
            if self.lv_create:
                self.delete_lv()
            if self.raid_create:
                self.delete_raid()
