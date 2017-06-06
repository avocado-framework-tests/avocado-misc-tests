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
#
# Copyright: 2016 IBM
# Author: Praveen K Pandey <praveen@linux.vnet.ibm.com>
# Author: Harish <harish@linux.vnet.ibm.com>
#
# Based on code by Cleber Rosa <crosa@redhat.com>
#   copyright: 2011 Redhat
#   https://github.com/autotest/autotest-client-tests/tree/master/xfstests


import os
import glob
import re
import shutil

from avocado import Test
from avocado import main
from avocado.utils import process, build, git, distro, partition, disk
from avocado.utils.software_manager import SoftwareManager


class Xfstests(Test):

    """
    xfstests - AKA FSQA SUITE, is set of filesystem tests

    :avocado: tags=fs,privileged
    """

    def setUp(self):
        """
        Build xfstest
        Source: git://git.kernel.org/pub/scm/fs/xfs/xfstests-dev.git
        """
        if process.system_output("df -T / | awk 'END {print $2}'", shell=True) == 'ext3':
            self.skip('Test does not support ext3 root file system')
        sm = SoftwareManager()

        self.detected_distro = distro.detect()

        packages = ['e2fsprogs', 'automake', 'gcc', 'quota', 'attr',
                    'make', 'xfsprogs', 'gawk']
        if 'Ubuntu' in self.detected_distro.name:
            packages.extend(['xfslibs-dev', 'uuid-dev', 'libtool-bin', 'libuuid1',
                             'libattr1-dev', 'libacl1-dev', 'libgdbm-dev',
                             'uuid-runtime', 'libaio-dev', 'fio', 'dbench', 'btrfs-tools'])

        # FIXME: "redhat" as the distro name for RHEL is deprecated
        # on Avocado versions >= 50.0.  This is a temporary compatibility
        # enabler for older runners, but should be removed soon
        elif self.detected_distro.name in ['centos', 'fedora', 'rhel', 'redhat', 'SuSE']:
            packages.extend(['acl', 'bc', 'dump', 'indent', 'libtool', 'lvm2',
                             'xfsdump', 'psmisc', 'sed', 'libacl-devel',
                             'libattr-devel', 'libaio-devel', 'libuuid-devel',
                             'openssl-devel', 'xfsprogs-devel'])
            if self.detected_distro.name == 'SuSE':
                packages.extend(['libbtrfs-devel'])
            else:
                packages.extend(['btrfs-progs-devel'])

            if self.detected_distro.name in ['centos', 'fedora']:
                packages.extend(['fio', 'dbench'])
        else:
            self.skip("test not supported in %s" % self.detected_distro.name)

        for package in packages:
            if not sm.check_installed(package) and not sm.install(package):
                self.skip("Fail to install %s required for this test." %
                          package)

        self.skip_dangerous = self.params.get('skip_dangerous', default=True)
        self.test_range = self.params.get('test_range', default=None)
        self.scratch_mnt = self.params.get(
            'scratch_mnt', default='/mnt/scratch')
        self.test_mnt = self.params.get('test_mnt', default='/mnt/test')
        self.disk_mnt = self.params.get('disk_mnt', default='/mnt/loop_device')
        self.dev_type = self.params.get('type', default='loop')
        self.fs_to_test = self.params.get('fs', default='ext4')
        if process.system('which mkfs.%s' % self.fs_to_test, ignore_status=True):
            self.skip('Unknown filesystem %s' % self.fs_to_test)
        mount = True
        self.devices = []
        shutil.copyfile(os.path.join(self.datadir, 'local.config'),
                        os.path.join(self.srcdir, 'local.config'))
        shutil.copyfile(os.path.join(self.datadir, 'group'),
                        os.path.join(self.srcdir, 'group'))

        if self.dev_type == 'loop':
            base_disk = self.params.get('disk', default=None)
            loop_size = self.params.get('loop_size', default='9GiB')
            if not base_disk:
                # Using root for file creation by default
                if disk.freespace('/') / 1073741824 > 15:
                    self.disk_mnt = ''
                    mount = False
                else:
                    self.skip('Need 15 GB to create loop devices')
            self._create_loop_device(base_disk, loop_size, mount)
        else:
            self.test_dev = self.params.get('disk_test', default=None)
            self.scratch_dev = self.params.get('disk_scratch', default=None)
            self.devices.extend([self.test_dev, self.scratch_dev])
        # mkfs for devices
        if self.devices:
            line = ('export TEST_DEV=%s' % self.devices[0]).replace('/', '\/')
            process.system('sed -i "s/export TEST_DEV=.*/%s/g" %s' %
                           (line, os.path.join(self.srcdir, 'local.config')), shell=True)
            line = ('export SCRATCH_DEV=%s' %
                    self.devices[1]).replace('/', '\/')
            process.system('sed -i "s/export SCRATCH_DEV=.*/%s/g" %s' %
                           (line, os.path.join(self.srcdir, 'local.config')), shell=True)
            for dev in self.devices:
                dev_obj = partition.Partition(dev)
                dev_obj.mkfs(fstype=self.fs_to_test)

        git.get_repo('git://git.kernel.org/pub/scm/fs/xfs/xfstests-dev.git',
                     destination_dir=self.srcdir)

        build.make(self.srcdir)
        self.available_tests = self._get_available_tests()

        self.test_list = self._create_test_list(self.test_range)
        self.log.info("Tests available in srcdir: %s",
                      ", ".join(self.available_tests))
        if not self.test_range:
            self.exclude = self.params.get('exclude', default=None)
            self.gen_exclude = self.params.get('gen_exclude', default=None)
            if self.exclude or self.gen_exclude:
                self.exclude_file = os.path.join(self.srcdir, 'exclude')
                with open(self.exclude_file, 'w') as fp:
                    if self.exclude:
                        self.exclude_tests = self._create_test_list(
                            self.exclude, dangerous=False)
                        for test in self.exclude_tests:
                            fp.write('%s/%s\n' % (self.fs_to_test, test))
                    if self.gen_exclude:
                        self.gen_exclude_tests = self._create_test_list(
                            self.gen_exclude, dangerous=False)
                        for test in self.gen_exclude_tests:
                            fp.write('generic/%s\n' % test)

        process.run('useradd fsgqa', sudo=True)
        if self.detected_distro.name is not 'SuSE':
            process.run('useradd 123456-fsgqa', sudo=True)
        if not os.path.exists(self.scratch_mnt):
            os.makedirs(self.scratch_mnt)
        if not os.path.exists(self.test_mnt):
            os.makedirs(self.test_mnt)

    def test(self):
        failures = False
        os.chdir(self.srcdir)
        if not self.test_list:
            self.log.info('Running all tests')
            args = ''
            if self.exclude or self.gen_exclude:
                args = ' -E %s' % self.exclude_file
            cmd = './check %s -g auto' % args
            result = process.run(cmd, ignore_status=True, verbose=True)
            if result.exit_status == 0:
                self.log.info('OK: All Tests passed.')
            else:
                msg = self._parse_error_message(result.stdout)
                self.log.info('ERR: Test(s) failed. Message: %s', msg)
                failures = True

        else:
            self.log.info('Running only specified tests')
            for test in self.test_list:
                test = '%s/%s' % (self.fs_to_test, test)
                cmd = './check %s' % test
                result = process.run(cmd, ignore_status=True, verbose=True)
                if result.exit_status == 0:
                    self.log.info('OK: Test %s passed.', test)
                else:
                    msg = self._parse_error_message(result.stdout)
                    self.log.info('ERR: %s failed. Message: %s', test, msg)
                    failures = True
        if failures:
            self.fail('One or more tests failed. Please check the logs.')

    def tearDown(self):
        process.system('userdel fsgqa', sudo=True)
        if self.detected_distro.name is not 'SuSE':
            process.system('userdel 123456-fsgqa', sudo=True)
        # In case if any test has been interrupted
        process.system('umount %s %s' % (self.scratch_mnt, self.test_mnt),
                       sudo=True, ignore_status=True)
        if os.path.exists(self.scratch_mnt):
            os.rmdir(self.scratch_mnt)
        if os.path.exists(self.test_mnt):
            os.rmdir(self.test_mnt)
        if self.dev_type == 'loop':
            for dev in self.devices:
                process.system('losetup -d %s' % dev, shell=True,
                               sudo=True, ignore_status=True)
            if self.disk_mnt:
                self.part.unmount()

    def _create_loop_device(self, base_disk, loop_size, mount=True):
        if mount:
            self.part = partition.Partition(
                base_disk, mountpoint=self.disk_mnt)
            self.part.mount()
        # Creating two loop devices
        for i in range(2):
            process.run('fallocate -o 0 -l %s %s/file-%s.img' %
                        (loop_size, self.disk_mnt, i), shell=True, sudo=True)
            dev = process.system_output('losetup -f').strip()
            self.devices.append(dev)
            process.run('losetup %s %s/file-%s.img' %
                        (dev, self.disk_mnt, i), shell=True, sudo=True)

    def _create_test_list(self, test_range, dangerous=True):
        test_list = []
        dangerous_tests = []
        if self.skip_dangerous:
            dangerous_tests = self._get_tests_for_group('dangerous')
        if test_range:
            for test in self._parse_test_range(test_range):
                if dangerous:
                    if test in dangerous_tests:
                        self.log.debug('Test %s is dangerous. Skipping.', test)
                        continue
                if not self._is_test_valid(test):
                    self.log.debug('Test %s invalid. Skipping.', test)
                    continue
                test_list.append(test)

        return test_list

    @staticmethod
    def _parse_test_range(test_range):
        # TODO: Validate test_range format.
        test_list = []
        for item in test_range.split(','):
            if '-' in item:
                start, end = item.split('-')
                for element in range(int(start), int(end) + 1):
                    test_list.append("%03d" % element)
            else:
                test_list.append("%03d" % int(item))
        return test_list

    def _get_tests_for_group(self, group):
        """
        Returns the list of tests that belong to a certain test group
        """
        group_test_line_re = re.compile('(\d{3})\s(.*)')
        group_path = os.path.join(self.srcdir, 'group')
        with open(group_path, 'r') as group_file:
            content = group_file.readlines()

        tests = []
        for g_test in content:
            match = group_test_line_re.match(g_test)
            if match is not None:
                test = match.groups()[0]
                groups = match.groups()[1]
                if group in groups.split():
                    tests.append(test)
        return tests

    def _get_available_tests(self):
        os.chdir(self.srcdir)
        tests_set = []
        tests = glob.glob(self.srcdir + '/tests/*/???.out')
        tests += glob.glob(self.srcdir + '/tests/*/???.out.linux')
        tests = [t.replace('.linux', '') for t in tests]

        tests_set = [t[-7:-4] for t in tests if os.path.exists(t[:-4])]
        tests_set.sort()
        tests_set = set(tests_set)

        return tests_set

    def _is_test_valid(self, test_number):
        os.chdir(self.srcdir)
        if test_number == '000':
            return False
        if test_number not in self.available_tests:
            return False
        return True

    @staticmethod
    def _parse_error_message(output):
        na_re = re.compile(r'Passed all 0 tests')
        na_detail_re = re.compile(r'(\d{3})\s*(\[not run\])\s*(.*)')
        failed_re = re.compile(r'Failed \d+ of \d+ tests')

        lines = output.split('\n')
        result_line = lines[-3]

        error_msg = None
        if na_re.match(result_line):
            detail_line = lines[-3]
            match = na_detail_re.match(detail_line)
            if match is not None:
                error_msg = match.groups()[2]
            else:
                error_msg = 'Test dependency failed, test will not run.'
        elif failed_re.match(result_line):
            error_msg = 'Test error. %s.' % result_line
        else:
            error_msg = 'Could not verify test result. Please check the logs.'

        return error_msg


if __name__ == "__main__":
    main()
