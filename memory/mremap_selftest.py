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

    @staticmethod
    def check_dmesg():
        """
        Check dmesg for errors during test execution
        """
        errorlog = ['WARNING: CPU:', 'Oops', 'Segfault', 'soft lockup',
                    'ard LOCKUP', 'Unable to handle paging request',
                    'rcu_sched detected stalls', 'NMI backtrace for cpu',
                    'BUG:', 'Call Trace:']
        err = []
        logs = process.system_output("dmesg -Txl 1,2,3,4",
                                     ignore_status=True).decode("utf-8").splitlines()
        for error in errorlog:
            for log in logs:
                if error in log:
                    err.append(log)
        return "\n".join(err)

    def setUp(self):
        """
        Setup: Install dependencies and clone kernel source
        """
        smm = SoftwareManager()
        detected_distro = distro.detect()

        # Base dependencies
        deps = ['gcc', 'make', 'git']

        # Distribution-specific dependencies
        if detected_distro.name in ["Ubuntu", 'debian']:
            deps.extend(['build-essential'])
        elif detected_distro.name == "SuSE":
            deps.extend(['git-core'])

        # Install dependencies
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

        # Get kernel source URL and branch from parameters
        self.kernel_url = self.params.get(
            'kernel_url',
            default='https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git')
        self.kernel_branch = self.params.get('kernel_branch', default='master')

        # Clone kernel source to test temporary directory
        self.log.info("Cloning kernel source from %s (branch: %s)",
                      self.kernel_url, self.kernel_branch)

        # git.get_repo clones directly into destination_dir
        self.sourcedir = os.path.join(self.workdir, 'linux-kernel')
        git.get_repo(self.kernel_url,
                     branch=self.kernel_branch,
                     destination_dir=self.sourcedir)

        self.selftest_dir = os.path.join(self.sourcedir, 'tools', 'testing',
                                         'selftests', 'mm')

        if not os.path.exists(self.selftest_dir):
            self.cancel("Kernel selftest directory not found at %s" % self.selftest_dir)

        # Build kernel headers first (required for selftests)
        self.log.info("Building kernel headers")
        try:
            os.chdir(self.sourcedir)
            build.make(self.sourcedir, extra_args='headers')
        except Exception as e:
            self.log.warning("Failed to build kernel headers: %s", str(e))

        # Build mm selftests using the Makefile
        self.log.info("Building mm selftests")
        try:
            os.chdir(os.path.join(self.sourcedir, 'tools', 'testing', 'selftests'))
            build.make(os.path.join(self.sourcedir, 'tools', 'testing', 'selftests'),
                       extra_args='-C mm')
        except Exception as e:
            self.cancel("Failed to build mm selftests: %s" % str(e))

        # Verify mremap_test binary was created
        self.mremap_test_bin = os.path.join(self.selftest_dir, 'mremap_test')
        if not os.path.exists(self.mremap_test_bin):
            self.cancel("mremap_test binary not found after build at %s" % self.mremap_test_bin)

        # Clear dmesg before test
        dmesg.clear_dmesg()

    def parse_mremap_times(self, output):
        """
        Parse mremap test output to extract timing information for alignment tests.
        Returns dict with test descriptions and their times in nanoseconds.
        """
        import re
        times = {}

        for line in output.split('\n'):
            # Match lines like: "ok 4 8KB mremap - Source PTE-aligned, Destination PTE-aligned"
            # followed by: "	mremap time:         7652ns"
            if 'mremap -' in line and ('aligned' in line.lower() or 'MB' in line or 'KB' in line):
                # Extract test description
                match = re.search(r'ok \d+ (.+)', line)
                if match:
                    test_desc = match.group(1).strip()
                    # Look for the timing line (should be next line in output)
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
        the mremap operation takes the least time compared to other alignment scenarios.
        """
        self.log.info("Running mremap_test")
        os.chdir(self.selftest_dir)

        result = process.run('./mremap_test',
                             ignore_status=True,
                             sudo=True)

        output = result.stdout.decode('utf-8')
        self.log.info("Test output:\n%s", output)

        # Check dmesg for errors
        dmesg_errors = self.check_dmesg()
        if dmesg_errors:
            self.log.error("Errors found in dmesg:\n%s", dmesg_errors)
            self.fail("Test failed with dmesg errors")

        # Parse timing information
        times = self.parse_mremap_times(output)

        if not times:
            self.log.warning("No timing information found in output")
            # Still check basic pass/fail
            if result.exit_status != 0:
                self.fail("mremap_test failed with exit code: %d" % result.exit_status)
            return

        # Find PMD-aligned tests (both source and destination PMD-aligned)
        pmd_aligned_tests = {}
        other_tests = {}

        for test_desc, time_ns in times.items():
            # PMD-aligned means both source and destination are PMD-aligned
            if 'PMD-aligned' in test_desc and test_desc.count('PMD-aligned') == 2:
                pmd_aligned_tests[test_desc] = time_ns
            elif 'mremap time' in test_desc or 'aligned' in test_desc.lower():
                other_tests[test_desc] = time_ns

        self.log.info("=" * 80)
        self.log.info("PMD-aligned tests (both source and dest):")
        for test, time in pmd_aligned_tests.items():
            self.log.info("  %s: %d ns", test, time)

        self.log.info("\nOther alignment tests:")
        for test, time in other_tests.items():
            self.log.info("  %s: %d ns", test, time)
        self.log.info("=" * 80)

        # Verify PMD-aligned tests are fastest
        if pmd_aligned_tests:
            min_pmd_time = min(pmd_aligned_tests.values())
            max_pmd_time = max(pmd_aligned_tests.values())

            self.log.info("\nPMD-aligned time range: %d - %d ns", min_pmd_time, max_pmd_time)

            # Check if any non-PMD-aligned test is faster than PMD-aligned
            failures = []
            for test_desc, time_ns in other_tests.items():
                if time_ns < min_pmd_time:
                    msg = "FAIL: %s (%d ns) is faster than PMD-aligned (%d ns)" % (
                        test_desc, time_ns, min_pmd_time)
                    self.log.error(msg)
                    failures.append(msg)

            if failures:
                self.log.error("=" * 80)
                self.log.error("PERFORMANCE VALIDATION FAILED:")
                self.log.error("PMD-aligned operations should be fastest!")
                for failure in failures:
                    self.log.error("  - %s", failure)
                self.log.error("=" * 80)
                self.fail("PMD-aligned mremap is not the fastest. See failures above.")
            else:
                self.log.info("=" * 80)
                self.log.info("SUCCESS: PMD-aligned mremap operations are fastest!")
                self.log.info("PMD-aligned min time: %d ns", min_pmd_time)
                if other_tests:
                    min_other = min(other_tests.values())
                    self.log.info("Other alignments min time: %d ns", min_other)
                    self.log.info("Performance improvement: %.2fx faster",
                                  min_other / min_pmd_time)
                self.log.info("=" * 80)
        else:
            self.log.warning("No PMD-aligned tests found in output")
            if result.exit_status != 0:
                self.fail("mremap_test failed with exit code: %d" % result.exit_status)

    def tearDown(self):
        """
        Cleanup and final dmesg check
        """
        # Final dmesg check
        dmesg_errors = self.check_dmesg()
        if dmesg_errors:
            self.log.warning("Errors found in dmesg during tearDown:\n%s",
                             dmesg_errors)
