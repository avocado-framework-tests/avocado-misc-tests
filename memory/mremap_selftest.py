#!/usr/bin/env python
#
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
# Copyright: 2026 IBM
# Author: Pavithra <pavithra@linux.ibm.com>
#

import os
from avocado import Test
from avocado.utils import process, build, git, distro, dmesg
from avocado.utils.software_manager.manager import SoftwareManager


class MremapSelftest(Test):
    """
    Kernel selftest for mremap system call
    This test runs the mremap_test from Linux kernel selftests

    :avocado: tags=memory,mremap,selftest
    """

    def setUp(self):
        """
        Setup: Install dependencies and clone kernel source
        """
        smm = SoftwareManager()
        detected_distro = distro.detect()

        deps = ['gcc', 'make', 'git']

        if detected_distro.name in ["Ubuntu", 'debian']:
            deps.extend(['build-essential'])
        elif detected_distro.name == "SuSE":
            deps.extend(['git-core'])

        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

        self.kernel_url = self.params.get(
            'kernel_url',
            default='https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git')
        self.kernel_branch = self.params.get('kernel_branch', default='master')
        self.log.info("Cloning kernel source from %s (branch: %s)",
                      self.kernel_url, self.kernel_branch)
        self.sourcedir = os.path.join(self.workdir, 'linux-kernel')
        git.get_repo(self.kernel_url,
                     branch=self.kernel_branch,
                     destination_dir=self.sourcedir)
        self.selftest_dir = os.path.join(self.sourcedir, 'tools', 'testing',
                                         'selftests', 'mm')

        if not os.path.exists(self.selftest_dir):
            self.cancel("Kernel selftest directory not found at %s" % self.selftest_dir)
        self.log.info("Building kernel headers")
        try:
            os.chdir(self.sourcedir)
            build.make(self.sourcedir, extra_args='headers')
        except Exception as e:
            self.log.warning("Failed to build kernel headers: %s", str(e))

        self.log.info("Building mm selftests")
        try:
            os.chdir(os.path.join(self.sourcedir, 'tools', 'testing', 'selftests'))
            build.make(os.path.join(self.sourcedir, 'tools', 'testing', 'selftests'),
                       extra_args='-C mm')
        except Exception as e:
            self.cancel("Failed to build mm selftests: %s" % str(e))

        self.mremap_test_bin = os.path.join(self.selftest_dir, 'mremap_test')
        if not os.path.exists(self.mremap_test_bin):
            self.cancel("mremap_test binary not found after build at %s" % self.mremap_test_bin)

        dmesg.clear_dmesg()

    def parse_mremap_times(self, output):
        """
        Parse mremap test output to extract timing information for alignment tests.
        Returns dict with test descriptions and their times in nanoseconds.
        """
        import re
        times = {}

        for line in output.split('\n'):
            if 'mremap -' in line and ('aligned' in line.lower() or 'MB' in line or 'KB' in line):
                match = re.search(r'ok \d+ (.+)', line)
                if match:
                    test_desc = match.group(1).strip()
                    time_match = re.search(r'mremap time:\s+(\d+)ns', output[output.find(line):])
                    if time_match:
                        time_ns = int(time_match.group(1))
                        times[test_desc] = time_ns
                        self.log.info("Found: %s = %d ns", test_desc, time_ns)
        return times

    def test_mremap_basic(self):
        """
        Run mremap test and verify that PMD-aligned operations are fastest.

        The test validates that when both source and destination are PMD-aligned,
        the mremap operation takes the least time compared to other alignment scenarios
        where the source is PMD-aligned but destination is not.

        Only cases where source is PMD-aligned are considered for comparison.
        """
        self.log.info("Running mremap_test")
        os.chdir(self.selftest_dir)

        result = process.run('./mremap_test',
                             ignore_status=True,
                             sudo=True)

        output = result.stdout.decode('utf-8')
        self.log.info("Test output:\n%s", output)

        dmesg.collect_errors_dmesg(['WARNING: CPU:', 'Oops', 'Segfault',
                                    'soft lockup', 'ard LOCKUP',
                                    'Unable to handle paging request',
                                    'rcu_sched detected stalls',
                                    'NMI backtrace for cpu', 'BUG:',
                                    'Call Trace:'])

        times = self.parse_mremap_times(output)

        if not times:
            self.log.warning("No timing information found in output")
            if result.exit_status != 0:
                self.fail("mremap_test failed with exit code: %d" % result.exit_status)
            return

        pmd_src_and_dest_aligned = {}
        pmd_src_only_aligned = {}
        other_tests = {}

        for test_desc, time_ns in times.items():
            if 'Source PMD-aligned' in test_desc:
                if 'Destination PMD-aligned' in test_desc:
                    pmd_src_and_dest_aligned[test_desc] = time_ns
                else:
                    pmd_src_only_aligned[test_desc] = time_ns
            else:
                other_tests[test_desc] = time_ns

        self.log.info("=" * 80)
        self.log.info("Tests with Source PMD-aligned AND Destination PMD-aligned:")
        for test, time in pmd_src_and_dest_aligned.items():
            self.log.info("  %s: %d ns", test, time)

        self.log.info("\nTests with Source PMD-aligned but Destination NOT PMD-aligned:")
        for test, time in pmd_src_only_aligned.items():
            self.log.info("  %s: %d ns", test, time)

        self.log.info("\nOther tests (Source NOT PMD-aligned - excluded from comparison):")
        for test, time in other_tests.items():
            self.log.info("  %s: %d ns", test, time)
        self.log.info("=" * 80)

        if pmd_src_and_dest_aligned:
            min_both_pmd = min(pmd_src_and_dest_aligned.values())
            max_both_pmd = max(pmd_src_and_dest_aligned.values())

            self.log.info("\nSource+Dest PMD-aligned time range: %d - %d ns",
                          min_both_pmd, max_both_pmd)

            failures = []
            if pmd_src_only_aligned:
                for test_desc, time_ns in pmd_src_only_aligned.items():
                    if time_ns < min_both_pmd:
                        msg = "FAIL: %s (%d ns) is faster than Source+Dest PMD-aligned (%d ns)" % (
                            test_desc, time_ns, min_both_pmd)
                        self.log.error(msg)
                        failures.append(msg)

            if failures:
                self.log.error("=" * 80)
                self.log.error("PERFORMANCE VALIDATION FAILED:")
                self.log.error("When source is PMD-aligned, having dest also PMD-aligned should be fastest!")
                for failure in failures:
                    self.log.error("  - %s", failure)
                self.log.error("=" * 80)
                self.fail("Source+Dest PMD-aligned mremap is not the fastest among PMD-source cases. See failures above.")
            else:
                self.log.info("=" * 80)
                self.log.info("SUCCESS: When source is PMD-aligned, Source+Dest PMD-aligned is fastest!")
                self.log.info("Source+Dest PMD-aligned min time: %d ns", min_both_pmd)
                if pmd_src_only_aligned:
                    min_src_only = min(pmd_src_only_aligned.values())
                    self.log.info("Source PMD-aligned only (dest not) min time: %d ns", min_src_only)
                    self.log.info("Performance improvement: %.2fx faster",
                                  min_src_only / min_both_pmd)
                self.log.info("=" * 80)
        else:
            self.log.warning("No Source+Dest PMD-aligned tests found in output")
            if result.exit_status != 0:
                self.fail("mremap_test failed with exit code: %d" % result.exit_status)

    def tearDown(self):
        """
        Cleanup and clear dmesg
        """
        dmesg.clear_dmesg()
