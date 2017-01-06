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


import os
from avocado import Test
from avocado import main
from avocado.utils import build
from avocado.utils import process, archive
from avocado.utils.software_manager import SoftwareManager


class ltp(Test):
    '''
    LTP (Linux Test Project) testsuite
    '''
    def setUp(self):
        '''
        To check and install dependencies for the test
        '''
        sm = SoftwareManager()
        deps = ['gcc', 'make', 'automake', 'autoconf']
        for package in deps:
            if not sm.check_installed(package) and not sm.install(package):
                self.error(package + ' is needed for the test to be run')
        self.disk = self.params.get('disk')
        self.mount_point = self.params.get('mount_point', default=self.srcdir)
        self.script = self.params.get('script')
        self.fs = self.params.get('fs', default='ext4')
        self.args = self.params.get('args', default='').split(',')
        url = "https://github.com/linux-test-project/ltp/\
               archive/master.zip"
        tarball = self.fetch_asset("ltp-master.zip",
                                   locations=[url], expire='7d')
        archive.extract(tarball, self.srcdir)
        ltp_dir = os.path.join(self.srcdir, "ltp-master")
        os.chdir(ltp_dir)
        build.make(ltp_dir, extra_args='autotools')
        ltpbin_dir = os.path.join(ltp_dir, 'bin')
        os.mkdir(ltpbin_dir)
        process.system('./configure --prefix=%s' % ltpbin_dir)
        build.make(ltp_dir)
        build.make(ltp_dir, extra_args='install')

    def test(self):
        for val in self.args:
            self.log.info("creating ext4 filesystem on disk %s" % self.disk)
            create_fs = "mkfs.%s %s" % (self.fs, self.disk)
            self.log.info("%s" % create_fs)
            ret = process.system(create_fs, shell=True)
            if ret != 0:
                self.fail("Created filesystem on %s failed" % self.disk)
            self.log.info("Mounting disk %s to mount location %s"
                          % (self.disk, self.mount_point))
            mounting = "mount %s %s" % (self.disk, self.mount_point)
            self.log.info("%s" % mounting)
            ret = process.system(mounting, shell=True)
            if ret != 0:
                self.fail("Unable to mount to location %s" % self.mount_point)
            if self.script == 'runltp':
                logfile = os.path.join(self.logdir, 'ltp.log')
                failcmdfile = os.path.join(self.logdir, 'failcmdfile')
                val += (" -q -p -l %s -C %s -d %s"
                        % (logfile, failcmdfile, self.mount_point))
            self.log.info("Args = %s" % self.args)
            ltpbin_dir = os.path.join(self.srcdir, "ltp-master", 'bin')
            cmd = os.path.join(ltpbin_dir, self.script) + ' ' + val
            result = process.run(cmd, ignore_status=True)
            # Walk the stdout and try detect failed tests from lines
            # like these:
            # aio01       5  TPASS  :  Test 5: 10 reads and
            # writes in  0.000022 sec
            # vhangup02    1  TFAIL  :  vhangup02.c:88:
            # vhangup() failed, errno:1
            # and check for fail_statuses The first part contain test name
            fail_statuses = ['TFAIL', 'TBROK', 'TWARN']
            split_lines = (line.split(None, 3)
                           for line in result.stdout.splitlines())
            failed_tests = [items[0] for items in split_lines
                            if len(items) == 4 and items[2] in fail_statuses]
            if failed_tests:
                self.fail("LTP tests failed: %s" % ", ".join(failed_tests))
            elif result.exit_status != 0:
                self.fail("No test failures detected, but LTP finished with %s"
                          % (result.exit_status))
            self.log.info("Removing the filesystem created on %s" % self.disk)
            delete_fs = "dd if=/dev/zero bs=512 count=512 of=%s" % self.disk
            self.log.info("%s" % delete_fs)
            ret = process.system(delete_fs, shell=True)
            if ret != 0:
                self.fail("Unable to delete filesystem on disk %s" % self.disk)
            self.log.info("Unmounting directory %s" % self.mount_point)
            unmounting = "umount %s" % self.mount_point
            self.log.info("%s" % unmounting)
            ret = process.system(unmounting, shell=True)
            if ret != 0:
                self.fail("Unable to unmount %s" % self.mount_point)


if __name__ == "__main__":
    main()
