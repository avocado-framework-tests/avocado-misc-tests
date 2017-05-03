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

from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils import build
from avocado.utils import kernel
from avocado.utils import memory
from avocado.utils import git
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import distro


class libhugetlbfs(Test):

    def setUp(self):
        # Check for root permission
        if os.geteuid() != 0:
            exit("You need to have root privileges to run this script."
                 "\nPlease try again, using 'sudo'. Exiting.")
        # Check for basic utilities
        sm = SoftwareManager()
        detected_distro = distro.detect()
        deps = ['gcc', 'make', 'patch']

        if detected_distro.name == "Ubuntu":
            deps += ['libpthread-stubs0-dev', 'git']
        elif detected_distro.name == "SuSE":
            deps += ['glibc-devel-static', 'git-core']
        else:
            deps += ['glibc-static', 'git']

        for package in deps:
            if not sm.check_installed(package) and not sm.install(package):
                self.cancel(' %s is needed for the test to be run' % package)

        kernel.check_version("2.6.16")

        if detected_distro.name == "Ubuntu":
            op = glob.glob("/usr/lib/*/libpthread.a")
        else:
            op = glob.glob("/usr/lib*/libpthread.a")

        if not op:
            self.error("libpthread.a is required!!!"
                       "\nTry installing glibc-static")

        # Get arguments:
        self.hugetlbfs_dir = self.params.get('hugetlbfs_dir', default=None)
        pages_requested = self.params.get('pages_requested',
                                          default=20)

        # Check hugepages:
        pages_available = 0
        if os.path.exists('/proc/sys/vm/nr_hugepages'):
            Hugepages_support = process.system_output('cat /proc/meminfo',
                                                      verbose=False,
                                                      shell=True)
            if 'HugePages_' not in Hugepages_support:
                self.error("No Hugepages Configured")
            memory.set_num_huge_pages(pages_requested)
            pages_available = memory.get_num_huge_pages()
        else:
            self.error("Kernel does not support hugepages")

        # Check no of hugepages :
        if pages_available < pages_requested:
            self.error('%d pages available, < %d pages requested'
                       % pages_available, pages_requested)

        # Check if hugetlbfs is mounted
        cmd_result = process.run('grep hugetlbfs /proc/mounts', verbose=False)
        if not cmd_result:
            if not self.hugetlbfs_dir:
                self.hugetlbfs_dir = os.path.join(self.tmpdir, 'hugetlbfs')
                os.makedirs(self.hugetlbfs_dir)
            process.system('mount -t hugetlbfs none %s' % self.hugetlbfs_dir)

        data_dir = os.path.abspath(self.datadir)
        git.get_repo('https://github.com/libhugetlbfs/libhugetlbfs.git',
                     destination_dir=self.srcdir)
        os.chdir(self.srcdir)
        patch = self.params.get('patch', default='elflink.patch')
        process.run('patch -p1 < %s' % data_dir + '/' + patch, shell=True)

        # FIXME: "redhat" as the distro name for RHEL is deprecated
        # on Avocado versions >= 50.0.  This is a temporary compatibility
        # enabler for older runners, but should be removed soon
        if detected_distro.name in ["rhel", "fedora", "redhat"]:
            falloc_patch = 'patch -p1 < %s ' % (
                os.path.join(data_dir, 'falloc.patch'))
            process.run(falloc_patch, shell=True)

        build.make(self.srcdir, extra_args='BUILDTYPE=NATIVEONLY')

    def _log_parser(self, log):
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
                parsed_results[32][key.lstrip('* ')] = int(values.split()[0])
                parsed_results[64][key.lstrip('* ')] = int(values.split()[1])

        return parsed_results

    def test(self):
        os.chdir(self.srcdir)

        parsed_results = self._log_parser(
            build.run_make(self.srcdir,
                           extra_args='BUILDTYPE=NATIVEONLY check').stdout)
        error = ""

        if parsed_results[32]['FAIL']:
            error += "%s tests failed for 32-bit\n" % (
                parsed_results[32]['FAIL'])

        if parsed_results[64]['FAIL']:
            error += "%s tests failed for 64-bit" % (
                parsed_results[64]['FAIL'])

        if error:
            self.fail(error)

    def tearDown(self):
        if self.hugetlbfs_dir:
            process.system('umount %s' % self.hugetlbfs_dir)


if __name__ == "__main__":
    main()
