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
# Copyright: 2023 IBM
# Author: Tasmiya Nalatwad <tasmiya@linux.vnet.ibm.com>
#
# Based on code by Martin Bligh <mbligh@google.com>
# copyright 2006 Google, Inc.
# https://github.com/autotest/autotest-client-tests/tree/master/ltp


import os
import re
import shutil
import time
from avocado import Test
from avocado.utils import build, distro, genio, dmesg
from avocado.utils import process, archive
from avocado.utils.partition import Partition
from avocado.utils.ssh import Session

from avocado.utils.software_manager.manager import SoftwareManager


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
            self.device.mount(mountpoint=self.mount_dir,
                              fstype="tmpfs", mnt_check=False)

    def setUp(self):
        smg = SoftwareManager()
        dist = distro.detect()
        self.args = self.params.get('args', default='')
        self.mem_leak = self.params.get('mem_leak', default=0)
        self.peer_public_ip = self.params.get("peer_public_ip", default="")
        self.peer_user = self.params.get("peer_user", default="root")
        self.peer_password = self.params.get("peer_password", default=None)
        self.two_host_configuration = self.params.get("two_host_configuration",
                                                      default=False)
        self.session = Session(self.peer_public_ip, user=self.peer_user,
                               password=self.peer_password)
        if not self.session.connect():
            self.cancel("failed connecting to peer")

        deps = ['gcc', 'make', 'automake', 'autoconf', 'psmisc',
                'libtirpc', 'nfs-utils', 'rpcbind', 'httpd', 'vsftpd']
        if dist.name == "Ubuntu":
            deps.extend(['libnuma-dev'])
        elif dist.name in ["centos", "rhel", "fedora"]:
            deps.extend(['numactl-devel'])
        elif dist.name == "SuSE":
            deps.extend(['libnuma-devel', 'iputils'])
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
        dmesg.clear_dmesg()
        url = self.params.get(
            'url',
            default='https://github.com/linux-test-project/ltp/archive/master.zip')
        zip_file = self.params.get('zip_file', default='ltp-master')
        match = next((ext for ext in [".zip", ".tar"] if ext in url), None)
        tarball = ''
        if match:
            tarball = self.fetch_asset(
                "%s%s" % (zip_file, match), locations=[url], expire='7d')
        else:
            self.cancel("Provided LTP Url is not valid")
        self.ltpdir = '/home/ltp'
        if not os.path.exists(self.ltpdir):
            os.mkdir(self.ltpdir)
        archive.extract(tarball, self.ltpdir)
        unzip_dir = self.params.get('unzip_dir', default='ltp-master')
        ltp_dir = os.path.join(self.ltpdir, unzip_dir)
        os.chdir(ltp_dir)
        build.make(ltp_dir, extra_args='autotools')
        if not self.ltpbin_dir:
            self.ltpbin_dir = os.path.join(self.teststmpdir, 'bin')
        if not os.path.exists(self.ltpbin_dir):
            os.mkdir(self.ltpbin_dir)

        if self.two_host_configuration:
            # setting ltp direcory in peer LPAR for 2 host configuration tests
            destination = "%s:/home" % self.peer_public_ip
            output = self.session.copy_files(self.ltpdir, destination,
                                             recursive=True)
            if not output:
                self.cancel("unable to copy the ltp into peer machine")
            time.sleep(10)
            cmd = "cd %s;make autotools;./configure;make;make install" % ltp_dir
            output = self.session.cmd(cmd)
            if not output.exit_status == 0:
                self.cancel("Unable to compile ltp in peer machine")

            # Adding Rhost name and passwd in tst_net.sh for ltp between 2 host
            output = self.session.cmd('hostname')
            if not output.exit_status == 0:
                self.cancel("Unable to get the hostname of peer machine")
            ltp_tstnet_dir = os.path.join(ltp_dir, 'testcases/lib/tst_net.sh')
            if not os.path.exists(ltp_tstnet_dir):
                self.log.info("File tst_net.sh does not exist")

            ltp_tstnet_dir_copy = os.path.join(ltp_dir,
                                               'testcases/lib/tst_net_copy.sh')
            shutil.copy(ltp_tstnet_dir, ltp_tstnet_dir_copy)
            replacements = [("export RHOST=\"$RHOST\"",
                            "export RHOST=\"" + str(output.stdout) + "\""),
                            ("export PASSWD=\"${PASSWD:-}\"",
                            "export PASSWD=\"" + self.peer_password + "\"")]
            with open(ltp_tstnet_dir_copy, 'r') as input_file, open(ltp_tstnet_dir, 'w') as output_file:
                for line in input_file:
                    if replacements:
                        for old_string, new_string in replacements:
                            line = line.replace(old_string, new_string)
                    output_file.write(line)
            os.remove(ltp_tstnet_dir_copy)

        process.system('./configure --prefix=%s' % self.ltpbin_dir)
        build.make(ltp_dir)
        build.make(ltp_dir, extra_args='install')

        # necessary services to be started on the host before test run starts
        services = ['nfs-server', 'rpcbind', 'httpd', 'vsftpd']
        for service in services:
            cmd = "service " + service + " restart"
            if process.system(cmd, ignore_status=True, shell=True) != 0:
                self.cancel("Unable to start the service in host machine")

    def test(self):
        logfile = os.path.join(self.logdir, 'ltp.log')
        failcmdfile = os.path.join(self.logdir, 'failcmdfile')
        skipfileurl = self.params.get(
            'skipfileurl', default=None)
        if skipfileurl:
            skipfilepath = self.fetch_asset(
                "skipfile", locations=[skipfileurl], expire='7d')
        else:
            skipfilepath = self.get_data('skipfile')
        os.chmod(self.teststmpdir, 0o755)
        self.args += (" -q -p -l %s -C %s -d %s -S %s"
                      % (logfile, failcmdfile, self.teststmpdir,
                         skipfilepath))
        if self.mem_leak:
            self.args += " -M %s" % self.mem_leak
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

        if self.failed_tests:
            self.fail("LTP tests failed: %s" % self.failed_tests)

        error = dmesg.collect_errors_dmesg(['WARNING: CPU:', 'Oops', 'Segfault',
                                            'soft lockup', 'Unable to handle'])
        if len(error):
            self.fail("Issue %s listed in dmesg please check" % error)

    def tearDown(self):
        if os.path.exists(self.ltpdir):
            shutil.rmtree(self.ltpdir)
        else:
            self.log.info("Unable to delete ltp from host machine")
        cmd = "rm -rf %s" % self.ltpdir
        output = self.session.cmd(cmd)
        if not output.exit_status == 0:
            self.cancel("Unable to delete ltp in peer machine")
        if self.mount_dir:
            self.device.unmount()
