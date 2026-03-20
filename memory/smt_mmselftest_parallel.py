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
# Copyright: 2026 IBM
# Author: Pavithra Prakash <pavrampu@linux.vnet.ibm.com>
# Assisted with AI Agent

import os
import time
import threading
from avocado import Test
from avocado.utils import process, distro, build
from avocado.utils.software_manager.manager import SoftwareManager


class SmtMmSelftestParallel(Test):
    """
    Test to run SMT switching in parallel with kernel memory selftests
    (both powerpc/mm and mm) to verify system stability under concurrent
    CPU topology changes and memory stress testing.

    Runs:
    - make -C tools/testing/selftests/powerpc/mm run_tests
    - make -C tools/testing/selftests/mm run_tests

    :avocado: tags=memory,smt,kernel,selftest,stress,privileged,powerpc
    """

    def setUp(self):
        """
        Setup test environment and check prerequisites
        """
        sm = SoftwareManager()
        self.detected_distro = distro.detect()

        # Check for powerpc-utils (needed for ppc64_cpu command)
        deps = ['powerpc-utils', 'time', 'gcc', 'make', 'git']
        if self.detected_distro.name in ["Ubuntu", 'debian']:
            deps.extend(['libelf-dev', 'libssl-dev', 'flex', 'bison'])
        elif self.detected_distro.name == "SuSE":
            deps.extend(['libelf-devel', 'libopenssl-devel', 'flex', 'bison'])
        else:
            deps.extend(['elfutils-libelf-devel', 'openssl-devel', 'flex', 'bison'])

        for package in deps:
            if not sm.check_installed(package) and not sm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

        # Check if system is SMT capable
        smt_op = process.run("ppc64_cpu --smt", shell=True,
                             ignore_status=True).stderr.decode("utf-8")
        if "is not SMT capable" in smt_op:
            self.cancel("Machine is not SMT capable, skipping the test")

        # Get test parameters
        self.smt_iterations = self.params.get('smt_iterations', default=1000)
        self.smt_sleep = self.params.get('smt_sleep', default=2)
        self.kernel_repo = self.params.get('kernel_repo',
                                           default='https://github.com/torvalds/linux.git')
        self.kernel_branch = self.params.get('kernel_branch', default='master')

        # Store initial state
        smt_out = process.system_output("ppc64_cpu --smt", shell=True)
        self.initial_smt = smt_out.decode().strip()
        self.log.info("Initial SMT state: %s", self.initial_smt)

        # Clone kernel source if not already present
        self.kernel_src = os.path.join(self.workdir, 'linux')
        if not os.path.exists(self.kernel_src):
            self.log.info("Cloning kernel source from %s (shallow clone)", self.kernel_repo)
            try:
                # Use shallow clone to save time and space
                os.makedirs(self.kernel_src, exist_ok=True)
                os.chdir(self.kernel_src)
                process.run("git init", shell=True)
                process.run("git remote add origin %s" % self.kernel_repo, shell=True)
                # Shallow clone with depth=1 to get only latest commit
                self.log.info("Fetching latest kernel source (this may take 10-15 minutes)...")
                process.run("git fetch --depth 1 origin %s" % self.kernel_branch,
                            shell=True, timeout=1800)
                process.run("git checkout FETCH_HEAD", shell=True)
                self.log.info("Kernel source cloned successfully")
            except Exception as e:
                self.cancel("Failed to clone kernel source: %s" % str(e))
        else:
            self.log.info("Using existing kernel source at %s", self.kernel_src)

        # Build kernel headers and selftests
        self.selftest_dir = os.path.join(self.kernel_src, 'tools', 'testing', 'selftests')
        self.mm_selftest_dir = os.path.join(self.selftest_dir, 'mm')
        self.powerpc_mm_selftest_dir = os.path.join(self.selftest_dir, 'powerpc', 'mm')

        if not os.path.exists(self.selftest_dir):
            self.cancel("Kernel selftests directory not found")

        if not os.path.exists(self.mm_selftest_dir):
            self.cancel("Memory selftests directory not found at %s" % self.mm_selftest_dir)

        if not os.path.exists(self.powerpc_mm_selftest_dir):
            self.cancel("PowerPC memory selftests directory not found at %s" %
                        self.powerpc_mm_selftest_dir)

        self.log.info("Building kernel headers")
        try:
            os.chdir(self.kernel_src)
            build.make(self.kernel_src, extra_args='headers')
        except Exception as e:
            self.log.warning("Failed to build kernel headers: %s", str(e))

        self.log.info("Building kernel memory selftests (mm)")
        try:
            build.make(self.selftest_dir, extra_args='-C mm')
        except Exception as e:
            self.log.warning("Failed to build mm selftests: %s", str(e))

        self.log.info("Building kernel powerpc memory selftests (powerpc/mm)")
        try:
            build.make(self.selftest_dir, extra_args='-C powerpc/mm')
        except Exception as e:
            self.log.warning("Failed to build powerpc/mm selftests: %s", str(e))

        # Thread control
        self.stop_threads = False
        self.smt_test_error = None
        self.selftest_error = None
        self.smt_test_completed = False
        self.selftest_completed = False
        self.failed_tests = []

    def smt_switching_test(self):
        """
        Test1 - Continuously switch between different SMT levels
        Based on the provided bash script
        """
        try:
            smt_levels = [2, 'off', 3, 4, 8, 6, 8]

            for iteration in range(1, self.smt_iterations + 1):
                if self.stop_threads:
                    break

                self.log.info("[SMT Test] Iteration %d/%d",
                              iteration, self.smt_iterations)

                for smt_level in smt_levels:
                    if self.stop_threads:
                        break

                    # Switch SMT level with timing
                    self.log.info("[SMT Test] Switching to SMT=%s", smt_level)
                    cmd = "time ppc64_cpu --smt=%s" % smt_level
                    result = process.run(cmd, shell=True, sudo=True,
                                         ignore_status=True)

                    if result.exit_status != 0:
                        stderr = result.stderr.decode()
                        msg = "[SMT Test] Failed to set SMT=%s - %s"
                        self.log.warning(msg, smt_level, stderr)
                    else:
                        # Log timing information
                        stderr = result.stderr.decode()
                        if stderr:
                            self.log.debug("[SMT Test] Timing: %s", stderr.strip())

                    # Get CPU info
                    info_output = process.system_output(
                        "ppc64_cpu --info", shell=True).decode()
                    self.log.debug("[SMT Test] CPU Info:\n%s", info_output)

                    time.sleep(self.smt_sleep)

                    # Verify SMT state
                    smt_output = process.system_output(
                        "ppc64_cpu --smt", shell=True)
                    current_smt = smt_output.decode().strip()
                    self.log.info("[SMT Test] Current SMT state: %s", current_smt)

            self.smt_test_completed = True
            self.log.info("[SMT Test] Completed successfully")

        except Exception as e:
            self.smt_test_error = "SMT test failed: %s" % str(e)
            self.log.error(self.smt_test_error)

    def parse_selftest_output(self, output, test_suite):
        """
        Parse kernel selftest output to extract failed test cases.
        Kernel selftests typically output in format:
        - "selftests: test_name: test_file ... [PASS|FAIL|SKIP]"
        - "not ok N - test_name # SKIP/FAIL reason"
        """
        failed = []
        for line in output.split('\n'):
            line = line.strip()
            # Match various failure patterns
            if any(pattern in line.lower() for pattern in ['[fail]', 'not ok', 'failed']):
                # Skip lines that are just status summaries
                if 'passed' not in line.lower() or 'failed' in line.lower():
                    failed.append("%s: %s" % (test_suite, line))
            # Also catch test execution errors
            elif 'error' in line.lower() and 'test' in line.lower():
                failed.append("%s: %s" % (test_suite, line))
        return failed

    def kernel_selftest_runner(self):
        """
        Test2 - Run kernel memory selftests (both powerpc/mm and mm)
        Uses:
        - make -C tools/testing/selftests/powerpc/mm run_tests
        - make -C tools/testing/selftests/mm run_tests
        """
        try:
            os.chdir(self.selftest_dir)

            # Run powerpc/mm selftests
            self.log.info("[Memory Selftest] Running powerpc/mm selftests")
            self.log.info("=" * 80)
            result = process.run("make -C powerpc/mm run_tests", shell=True,
                                 ignore_status=True, sudo=True)

            output = result.stdout.decode()
            self.log.info("[Memory Selftest] powerpc/mm output:\n%s", output)

            # Parse for failed tests
            failed = self.parse_selftest_output(output, "powerpc/mm")
            if failed:
                self.failed_tests.extend(failed)
                self.log.warning("[Memory Selftest] powerpc/mm: %d test(s) failed", len(failed))
            else:
                self.log.info("[Memory Selftest] powerpc/mm: All tests passed or skipped")

            # Check if we should continue
            if self.stop_threads or self.smt_test_completed:
                self.log.info("[Memory Selftest] SMT test completed, finishing up")
                self.selftest_completed = True
                return

            # Run mm selftests
            self.log.info("=" * 80)
            self.log.info("[Memory Selftest] Running mm selftests")
            self.log.info("=" * 80)
            result = process.run("make -C mm run_tests", shell=True,
                                 ignore_status=True, sudo=True)

            output = result.stdout.decode()
            self.log.info("[Memory Selftest] mm output:\n%s", output)

            # Parse for failed tests
            failed = self.parse_selftest_output(output, "mm")
            if failed:
                self.failed_tests.extend(failed)
                self.log.warning("[Memory Selftest] mm: %d test(s) failed", len(failed))
            else:
                self.log.info("[Memory Selftest] mm: All tests passed or skipped")

            self.selftest_completed = True
            self.log.info("[Memory Selftest] Completed successfully")

        except Exception as e:
            self.selftest_error = "Memory selftest failed: %s" % str(e)
            self.log.error(self.selftest_error)

    def test_parallel_smt_mmselftest(self):
        """
        Main test - Run SMT switching and kernel memory selftests in parallel
        SMT test runs until completion, selftest runs once
        """
        self.log.info("=" * 80)
        self.log.info("Starting parallel SMT switching and kernel memory selftest")
        self.log.info("SMT iterations: %d", self.smt_iterations)
        self.log.info("PowerPC MM selftest path: %s", self.powerpc_mm_selftest_dir)
        self.log.info("MM selftest path: %s", self.mm_selftest_dir)
        self.log.info("=" * 80)

        # Create threads for parallel execution
        smt_thread = threading.Thread(target=self.smt_switching_test,
                                      name="SMTTest")
        selftest_thread = threading.Thread(target=self.kernel_selftest_runner,
                                           name="KernelSelftest")

        # Start both threads
        self.log.info("Starting both test threads...")
        smt_thread.start()
        time.sleep(5)  # Give SMT test a head start
        selftest_thread.start()

        # Wait for selftest to complete first
        selftest_thread.join()
        self.log.info("Selftest thread completed")

        # Signal SMT test to stop
        self.stop_threads = True

        # Wait for SMT thread to complete
        smt_thread.join()
        self.log.info("SMT test thread completed")

        # Report failed tests
        if self.failed_tests:
            self.log.error("=" * 80)
            self.log.error("FAILED TEST CASES:")
            self.log.error("=" * 80)
            for failed_test in self.failed_tests:
                self.log.error("  - %s", failed_test)
            self.log.error("=" * 80)
            self.log.error("Total failed tests: %d", len(self.failed_tests))
        else:
            self.log.info("All memory selftests passed!")

        # Check for errors
        if self.smt_test_error:
            self.fail(self.smt_test_error)
        if self.selftest_error:
            self.fail(self.selftest_error)

        self.log.info("=" * 80)
        self.log.info("Test completed successfully - no crashes or hangs detected")
        if self.failed_tests:
            self.log.info("Note: %d selftest(s) failed (see above)", len(self.failed_tests))
        self.log.info("=" * 80)

    def tearDown(self):
        """
        Cleanup - Restore initial state
        """
        self.log.info("Cleaning up and restoring initial state...")

        # Stop threads if still running
        self.stop_threads = True
        time.sleep(2)

        # Restore initial SMT state
        try:
            # Extract SMT level from initial state (e.g., "SMT=4" -> "4")
            if "SMT=" in self.initial_smt:
                smt_value = self.initial_smt.split("SMT=")[1].split()[0]
                process.system("ppc64_cpu --smt=%s" % smt_value,
                               ignore_status=True)
            elif "off" in self.initial_smt.lower():
                process.system("ppc64_cpu --smt=off", ignore_status=True)
            self.log.info("SMT state restored to: %s", self.initial_smt)
        except Exception as e:
            self.log.warning("Failed to restore SMT state: %s", e)
