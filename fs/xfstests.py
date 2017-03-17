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
from avocado.utils import process, build, git, distro, partition
from avocado.utils.software_manager import SoftwareManager


class Xfstests(Test):

    def setUp(self):
        """
        Build xfstest
        Source: git://git.kernel.org/pub/scm/fs/xfs/xfstests-dev.git
        """
        sm = SoftwareManager()

        detected_distro = distro.detect()

        packages = ['e2fsprogs', 'automake', 'gcc', 'quota', 'attr',
                    'make',  'xfsprogs',  'gawk']

        if 'Ubuntu' in detected_distro.name:
            packages.extend(['xfslibs-dev', 'uuid-dev', 'libtool-bin', 'libuuid1',
                             'libattr1-dev', 'libacl1-dev', 'libgdbm-dev',
                             'uuid-runtime', 'libaio-dev', 'fio', 'dbench'])

        elif detected_distro.name in ['centos', 'fedora', 'redhat']:
            packages.extend(['acl', 'bc', 'dump', 'indent', 'libtool', 'lvm2',
                             'xfsdump', 'psmisc', 'sed', 'libacl-devel',
                             'libattr-devel', 'libaio-devel', 'libuuid-devel',
                             'openssl-devel', 'xfsprogs-devel', 'btrfs-progs-devel'])
            if detected_distro.name != 'redhat':
                packages.extend(['fio', 'dbench'])
        else:
            self.skip("test not supported in %s" % detected_distro.name)

        for package in packages:
            if not sm.check_installed(package) and not sm.install(package):
                self.skip("Fail to install %s required for this test." %
                          package)
        self.test_range = self.params.get('test_range', default=None)

        self.skip_dangerous = self.params.get('skip_dangerous', default=True)
        self.dev_type = self.params.get('type', default='loop')
        self.fs_to_test = self.params.get('file_system', default='ext4')
        if self.dev_type == 'loop':
            base_disk = self.params.get('base_disk', default=None)
            if not base_disk:
                self.skip('Please provide a base disk to create loop device')
            self._create_loop_device(base_disk)
        else:
            self.test_dev = self.params.get('test_dev', default=None)
            self.scratch_dev = self.params.get('scratch_dev', default=None)
            # TODO: Overwirte the disk in local.config

        git.get_repo('git://git.kernel.org/pub/scm/fs/xfs/xfstests-dev.git',
                     destination_dir=self.srcdir)
        data_dir = os.path.abspath(self.datadir)

        shutil.copyfile(os.path.join(data_dir, 'group'),
                        os.path.join(self.srcdir, 'group'))
        shutil.copyfile(os.path.join(data_dir, 'local.config'),
                        os.path.join(self.srcdir, 'local.config'))

        build.make(self.srcdir)
        self.available_tests = self._get_available_tests()

        self.test_list = self._create_test_list()
        self.log.info("Tests available in srcdir: %s",
                      ", ".join(self.available_tests))
        process.run('useradd fsgqa', sudo=True)
        process.run('useradd 123456-fsgqa', sudo=True)
        self.scratch_mnt = '/mnt/scratch'
        self.test_mnt = '/mnt/test'
        if not os.path.exists(self.scratch_mnt):
            os.makedirs(self.scratch_mnt)
        if not os.path.exists(self.test_mnt):
            os.makedirs(self.test_mnt)

    def test(self):
        failures = False
        os.chdir(self.srcdir)
        if not self.test_list:
            self.log.info('Running all tests')
            cmd = './check -g auto'
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
        process.system('userdel 123456-fsgqa', sudo=True)
        # In case if any test has been interrupted
        process.system('umount self.scratch_mnt self.test_mnt',
                       sudo=True, ignore_status=True)
        if os.path.exists(self.scratch_mnt):
            os.rmdir(self.scratch_mnt)
        if os.path.exists(self.test_mnt):
            os.rmdir(self.test_mnt)
        if self.dev_type == 'loop':
            process.system(
                'for i in $(seq 0 1); do losetup -d '
                '/dev/loop$i; done', shell=True, sudo=True)
        self.part.unmount()

    def _create_loop_device(self, base_disk):
        self.part = partition.Partition(
            base_disk, mountpoint='/mnt/loop-device')
        self.part.mount()
        # Creating two loop devices
        process.run(
            'for i in $(seq 0 1); do fallocate -o 0 -l 9GiB '
            '/mnt/loop-device/file-$i.img; done', shell=True, sudo=True)
        process.run(
            'for i in $(seq 0 1); do losetup /dev/loop$i '
            '/mnt/loop-device/file-$i.img; done', shell=True, sudo=True)
        if process.system('which mkfs.%s' % self.fs_to_test):
            self.skip('Unknown filesystem %s' % self.fs_to_test)
        # mkfs for two loop device
        for i in range(2):
            loop_dev = partition.Partition('/dev/loop%s' % i)
            loop_dev.mkfs(fstype=self.fs_to_test)

    def _create_test_list(self):
        test_list = []
        dangerous_tests = []
        if self.skip_dangerous:
            dangerous_tests = self._get_tests_for_group('dangerous')
        if self.test_range:
            for test in self._parse_test_range(self.test_range):
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
