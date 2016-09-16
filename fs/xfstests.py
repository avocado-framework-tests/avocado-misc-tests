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
from avocado.utils import process, build, git, distro
from avocado.utils.software_manager import SoftwareManager


class Xfstests(Test):

    PASSED_RE = re.compile(r'Passed all \d+ tests')
    FAILED_RE = re.compile(r'Failed \d+ of \d+ tests')
    NA_RE = re.compile(r'Passed all 0 tests')
    NA_DETAIL_RE = re.compile(r'(\d{3})\s*(\[not run\])\s*(.*)')
    GROUP_TEST_LINE_RE = re.compile('(\d{3})\s(.*)')

    def _get_available_tests(self):
        os.chdir(self.srcdir)

        tests = glob.glob(self.srcdir + '/tests/*/???.out')
        tests += glob.glob(self.srcdir + '/tests/*/???.out.linux')
        tests = [t.replace('.linux', '') for t in tests]
        tests_list = [t[-7:-4] for t in tests if os.path.exists(t[:-4])]
        tests_list.append('')
        tests_list.sort()
        return tests_list

    def _run_sub_test(self, test):

        os.chdir(self.srcdir)
        self.log.info("Running test: %s" % test)
        output = process.system_output('./check %s' % test,
                                       ignore_status=True)
        lines = output.split('\n')
        result_line = lines[-3]
        if self.NA_RE.match(result_line):
            detail_line = lines[-3]
            match = self.NA_DETAIL_RE.match(detail_line)
            if match is not None:
                error_msg = match.groups()[2]
            else:
                error_msg = 'Test dependency failed, test not run'
            raise self.error(error_msg)

        elif self.FAILED_RE.match(result_line):
            raise self.error('Test error, check debug logs for complete '
                             'test output')

        elif self.PASSED_RE.match(result_line):
            return

        else:
            raise self.error('Could not assert test success or failure, '
                             'assuming failure. Please check debug logs')

    def _get_groups(self):
        '''
        Returns the list of groups known to xfstests
        By reading the group file and identifying unique mentions of groups
        '''
        groups = []
        for l in open(os.path.join(self.srcdir, 'group')).readlines():
            m = self.GROUP_TEST_LINE_RE.match(l)
            if m is not None:
                groups = m.groups()[1].split()
                for g in groups:
                    if g not in groups:
                        groups.add(g)
        return groups

    def _get_tests_for_group(self, group):
        '''
        Returns the list of tests that belong to a certain test group
        '''
        tests = []
        for l in open(os.path.join(self.srcdir, 'group')).readlines():
            m = self.GROUP_TEST_LINE_RE.match(l)
            if m is not None:
                test = m.groups()[0]
                groups = m.groups()[1]
                if group in groups.split():
                    if test not in tests:
                        tests.append(test)
        return tests

    def setUp(self):
        '''
        Build xfstest
        Source:
        git://git.kernel.org/pub/scm/fs/xfs/xfstests-dev.git
        '''

        # Check for basic utilities
        sm = SoftwareManager()
        detected_distro = distro.detect()

        packages = ['xfslibs-dev', 'uuid-dev', 'libtool-bin', 'e2fsprogs',
                    'automake',  'gcc', 'libuuid1', 'quota', 'attr',
                    'libattr1-dev', 'make', 'libacl1-dev', 'xfsprogs',
                    'libgdbm-dev', 'gawk', 'fio', 'dbench', 'uuid-runtime']
        for package in packages:
            if not sm.check_installed(package) and not sm.install(package):
                self.error(
                    "Fail to install %s required for this test." % package)

        self._test_number = self.params.get('test_number', default='')
        self._skip_dangerous = self.params.get('skip_dangerous', default=True)
        self._test_range = self.params.get('test_range', default=None)

        data_dir = os.path.abspath(self.datadir)
        git.get_repo('git://git.kernel.org/pub/scm/fs/xfs/xfstests-dev.git',
                     destination_dir=self.srcdir)
        os.chdir(self.srcdir)
        shutil.copyfile(data_dir + '/group',
                        os.path.join(self.srcdir, 'group'))

        if self._skip_dangerous:
            if self._test_number in self._get_tests_for_group('dangerous'):
                self.skip('test is dangerous, skipped')

        build.make(self.srcdir)

        process.run('useradd fsgqa', sudo=True)
        process.run('useradd 123456-fsgqa', sudo=True)

        self.log.info("Available tests in srcdir: %s" %
                      ", ".join(self._get_available_tests()))

    def _check_test_validity(self, test_number):
        os.chdir(self.srcdir)
        if test_number == '000':
            self.log.info('Dummy test to setup xfstests')
            return

        if test_number not in self._get_available_tests():
            raise self.error('test file %s not found' % test_number)

    def test(self):

        os.chdir(self.srcdir)

        test_list = []

        if self._test_range:
            for item in self._test_range.split(','):
                if '-' in item:
                    start, end = item.split('-')
                    test_list.extend(range(int(start), int(end) + 1))
                else:
                    test_list.append(int(item))
            for test in test_list:
                check_test = "%03d" % test
                test_no = '*/' + check_test
                self._check_test_validity(check_test)
                self._run_sub_test(test_no)

        self._check_test_validity(self._test_number)

        if self._test_number:
            self._test_number = '*/' + self._test_number

        self._run_sub_test(self._test_number)


if __name__ == "__main__":
    main()
