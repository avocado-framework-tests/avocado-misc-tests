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
# Author: Santhosh G <santhog4@linux.vnet.ibm.com>
#
# Based on code by Martin Bligh <mbligh@google.com>
# copyright 2006 Google, Inc.
# https://github.com/autotest/autotest-client-tests/tree/master/ltp


import os
import re
from avocado import Test
from avocado import main
from avocado.utils import build, distro, genio
from avocado.utils import process, archive
from avocado.utils.partition import Partition

from avocado.utils.software_manager import SoftwareManager


def clear_dmesg():
    process.run("dmesg -c ", sudo=True)


def collect_dmesg(obj):
    obj.whiteboard = process.system_output("dmesg").decode()


class LTP(Test):

    """
    LTP (Linux Test Project) testsuite
    :param args: Extra arguments ("runltp" can use with
                 "-f $test")
    """
    failed_tests = list()
    mem_tests = ['-f mm', '-f hugetlb']

    @staticmethod
    def mount_point(mount_dir):
        lines = genio.read_file('/proc/mounts').rstrip('\t\r\0').splitlines()
        for substr in lines:
            mop = substr.split(" ")[1]
            if mop == mount_dir:
                return True
        return False

    def check_thp(self):
        if 'thp_file_alloc' in genio.read_file('/proc/vm'
                                               'stat').rstrip('\t\r\n\0'):
            self.thp = True
        return self.thp

    def setup_tmpfs_dir(self):
        # check for THP page cache
        self.check_thp()

        if not os.path.isdir(self.mount_dir):
            os.makedirs(self.mount_dir)

        self.device = None
        if not self.mount_point(self.mount_dir):
            if self.thp:
                self.device = Partition(
                    device="none", mountpoint=self.mount_dir,
                    mount_options="huge=always")
            else:
                self.device = Partition(
                    device="none", mountpoint=self.mount_dir)
            self.device.mount(mountpoint=self.mount_dir, fstype="tmpfs")

    def setUp(self):
        smg = SoftwareManager()
        dist = distro.detect()
        self.args = self.params.get('args', default='')
        self.mem_leak = self.params.get('mem_leak', default=0)

        deps = ['gcc', 'make', 'automake', 'autoconf', 'psmisc']
        if dist.name == "Ubuntu":
            deps.extend(['libnuma-dev'])
        elif dist.name in ["centos", "rhel", "fedora"]:
            deps.extend(['numactl-devel'])
        elif dist.name == "SuSE":
            deps.extend(['libnuma-devel'])
        self.ltpbin_dir = self.mount_dir = None
        self.thp = False
        if self.args in self.mem_tests:
            self.mount_dir = self.params.get('tmpfs_mount_dir', default=None)
            if self.mount_dir:
                self.setup_tmpfs_dir()
            over_commit = self.params.get('overcommit', default=True)
            if not over_commit:
                process.run('echo 2 > /proc/sys/vm/overcommit_memory',
                            shell=True, ignore_status=True)

        for package in deps:
            if not smg.check_installed(package) and not smg.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        clear_dmesg()
        url = "https://github.com/linux-test-project/ltp/archive/master.zip"
        tarball = self.fetch_asset("ltp-master.zip", locations=[url])
        archive.extract(tarball, self.workdir)
        ltp_dir = os.path.join(self.workdir, "ltp-master")
        os.chdir(ltp_dir)
        build.make(ltp_dir, extra_args='autotools')
        if not self.ltpbin_dir:
            self.ltpbin_dir = os.path.join(ltp_dir, 'bin')
        os.mkdir(self.ltpbin_dir)
        process.system('./configure --prefix=%s' % self.ltpbin_dir)
        build.make(ltp_dir)
        build.make(ltp_dir, extra_args='install')

    def test(self):
        logfile = os.path.join(self.logdir, 'ltp.log')
        failcmdfile = os.path.join(self.logdir, 'failcmdfile')

        self.args += (" -q -p -l %s -C %s -d %s -S %s"
                      % (logfile, failcmdfile, self.workdir,
                         self.get_data('skipfile')))
        if self.mem_leak:
            self.args += " -M %s" % self.mem_leak
        self.ltpbin_dir = os.path.join(self.workdir, "ltp-master", 'bin')
        cmd = "%s %s" % (os.path.join(self.ltpbin_dir, 'runltp'), self.args)
        process.run(cmd, ignore_status=True)
        # Walk the ltp.log and try detect failed tests from lines like these:
        # msgctl04                                           FAIL       2
        with open(logfile, 'r') as file_p:
            lines = file_p.readlines()
            for line in lines:
                if 'FAIL' in line:
                    value = re.split(r'\s+', line)
                    self.failed_tests.append(value[0])

        collect_dmesg(self)
        if self.failed_tests:
            self.fail("LTP tests failed: %s" % self.failed_tests)

    def tearDown(self):
        if self.mount_dir:
            self.device.unmount()


if __name__ == "__main__":
    main()
