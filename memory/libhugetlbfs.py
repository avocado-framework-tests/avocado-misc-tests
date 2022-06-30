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
# Based on code by:
# Author: Yao Fei Zhu <walkinair@cn.ibm.com>
# copyright : 2006 IBM

import os
import glob
import tempfile

from avocado import Test
from avocado import skipUnless
from avocado.utils import process
from avocado.utils import build
from avocado.utils import git
from avocado.utils import distro
from avocado.utils import genio
from avocado.utils import memory
from avocado.utils.software_manager.manager import SoftwareManager


class LibHugetlbfs(Test):
    '''
    libhugetlbfs: libhugetlbfs is a library which provides easy
    access to huge pages of memory. test to excersize libhugetlbfs library

    :avocado: tags=memory,privileged,hugepage
    '''

    @skipUnless('Hugepagesize' in dict(memory.meminfo),
                "Hugepagesize not defined in kernel.")
    def setUp(self):

        # Check for basic utilities
        smm = SoftwareManager()
        detected_distro = distro.detect()
        if (detected_distro.name == 'rhel' and detected_distro.version == '9'):
            self.cancel("libhugetlbfs is not available RHEL 9.x onwards")
        deps = ['gcc', 'make', 'patch']
        if detected_distro.name in ["Ubuntu", 'debian']:
            deps += ['libpthread-stubs0-dev', 'git']
        elif detected_distro.name == "SuSE":
            deps += ['glibc-devel-static', 'git-core']
        else:
            deps += ['glibc-static', 'git']

        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel(' %s is needed for the test to be run' % package)

        if detected_distro.name in ["Ubuntu", 'debian']:
            out = glob.glob("/usr/lib/*/libpthread.a")
        else:
            out = glob.glob("/usr/lib*/libpthread.a")

        if not out:
            self.cancel("libpthread.a is required!!!"
                        "\nTry installing glibc-static")

        page_sizes = memory.get_supported_huge_pages_size()
        self.page_sizes = [str(each // 1024) for each in page_sizes]

        # Get arguments:
        pages_requested = self.params.get('pages_requested',
                                          default=20)

        # Check hugepages:
        pages_available = 0
        if os.path.exists('/proc/sys/vm/nr_hugepages'):

            hugepages_support = genio.read_file("/proc/meminfo").rstrip("\n")

            if 'HugePages_' not in hugepages_support:
                self.cancel("No Hugepages Configured")
        else:
            self.cancel("Kernel does not support hugepages")

        self.configured_page_sizes = []
        self.hugetlbfs_dir = {}

        for hp_size in self.page_sizes:
            try:
                genio.write_file(
                    '/sys/kernel/mm/hugepages/hugepages-%skB/nr_hugepages' %
                    str(int(hp_size) * 1024), str(pages_requested))
            except OSError:
                if (int(hp_size) * 1024) == 16777216:
                    self.log.warn('Running 16GB hugepages')
                else:
                    self.cancel('Writing to hugepage file failed')
            pages_available = int(genio.read_file(
                '/sys/kernel/mm/hugepages/huge'
                'pages-%skB/nr_hugepages' % str(int(hp_size) * 1024).strip()))
            if pages_available < pages_requested:
                self.log.warn('%d pages available, < %d pages '
                              'requested', pages_available, pages_requested)

            if pages_available:
                self.hugetlbfs_dir.update(
                    {hp_size: tempfile.mkdtemp(dir=self.teststmpdir,
                                               prefix='avocado_' + __name__)})
                if process.system('mount -t hugetlbfs -o pagesize=%sM none %s' %
                                  (hp_size, self.hugetlbfs_dir[hp_size]), sudo=True,
                                  ignore_status=True):
                    self.cancel("hugetlbfs mount failed")
                self.configured_page_sizes.append(hp_size)

        if not self.configured_page_sizes:
            self.cancel("No hugepage size configured")

        git.get_repo('https://github.com/libhugetlbfs/libhugetlbfs.git',
                     destination_dir=self.workdir)
        os.chdir(self.workdir)
        patch = self.params.get('patch', default='elflink.patch')
        process.run('patch -p1 < %s' % self.get_data(patch), shell=True)

        build.make(self.workdir, extra_args='BUILDTYPE=NATIVEONLY')

    @staticmethod
    def _log_parser(log, column):
        """
        Parses the log, returning a dictionary with the test results.
        Test summary section example:
        ********** TEST SUMMARY
        *                      16M
        *                      32-bit 64-bit
        *     Total testcases:     0     93
        *             Skipped:     0      0
        *                PASS:     0     90
        *                FAIL:     0      3
        *    Killed by signal:     0      0
        *   Bad configuration:     0      0
        *       Expected FAIL:     0      0
        *     Unexpected PASS:     0      0
        * Strange test result:     0      0
        **********

        Return example:
        {32: {'Bad configuration': 0,
              'Expected FAIL ': 0,
              'FAIL': 0,
              'Killed  by signal': 0,
              'PASS': 0,
              'Skipped': 0,
              'Strange test result': 0,
              'Total testcases:': 0,
              'Unexpected PASS': 0},
         64: {'Bad configuration': 0,
              'Expected FAIL ': 0,
              'FAIL': 3,
              'Killed  by signal': 0,
              'PASS': 90,
              'Skipped': 0,
              'Strange test result': 0,
              'Total testcases:': 93,
              'Unexpected PASS': 0}}

        """
        section = False
        parsed_results = {32: {}, 64: {}}

        for line in log.splitlines():
            if line == '********** TEST SUMMARY':
                section = True
            if line == '**********':
                section = False
            if section and ':' in line:
                key, values = line.split(':')
                parsed_results[32][key.lstrip(
                    '* ')] = int(values.split()[column])
                parsed_results[64][key.lstrip(
                    '* ')] = int(values.split()[column + 1])

        return parsed_results

    def test(self):
        os.chdir(self.workdir)

        functional_test = self.params.get('functional_test', default=False)
        test_type = 'check'
        if functional_test:
            test_type = 'func'
        run_log = build.run_make(
            self.workdir, extra_args='BUILDTYPE=NATIVEONLY %s' % test_type,
            process_kwargs={'ignore_status': True}).stdout.decode('utf-8')
        parsed_results = []
        error = ""
        for idx, hp_size in enumerate(self.configured_page_sizes):
            parsed_results.append(self._log_parser(run_log, idx * 2))

            if parsed_results[idx][32]['FAIL']:
                error += "%s 32-bit tests failed for %sMB hugepage\n" % (
                    parsed_results[idx][32]['FAIL'], hp_size)

            if parsed_results[idx][64]['FAIL']:
                error += "%s 64-bit tests failed for %sMB hugepage\n" % (
                    parsed_results[idx][64]['FAIL'], hp_size)

        if error:
            self.fail(error)

    def tearDown(self):
        for hp_size in self.configured_page_sizes:
            if process.system('umount %s' %
                              self.hugetlbfs_dir[hp_size], ignore_status=True):
                self.log.warn("umount of hugetlbfs dir failed")
