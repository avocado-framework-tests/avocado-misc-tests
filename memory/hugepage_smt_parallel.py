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
from avocado.utils import process, distro, genio
from avocado.utils.software_manager.manager import SoftwareManager


class HugepageSmtParallel(Test):
    """
    Test to run hugepage allocation/deallocation in parallel with
    SMT switching to verify system stability under concurrent memory
    and CPU topology changes.

    :avocado: tags=memory,hugepage,smt,stress,privileged
    """

    def setUp(self):
        """
        Setup test environment and check prerequisites
        """
        sm = SoftwareManager()
        self.detected_distro = distro.detect()

        # Check for powerpc-utils (needed for ppc64_cpu command)
        deps = ['powerpc-utils', 'time']
        for package in deps:
            if not sm.check_installed(package) and not sm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

        # Check if system is SMT capable
        smt_op = process.run("ppc64_cpu --smt", shell=True,
                             ignore_status=True).stderr.decode("utf-8")
        if "is not SMT capable" in smt_op:
            self.cancel("Machine is not SMT capable, skipping the test")

        # Check if hugepages are supported
        if not os.path.exists("/proc/sys/vm/nr_hugepages"):
            self.cancel("Hugepages not supported on this system")

        # Get test parameters
        self.test_duration = self.params.get('test_duration', default=300)
        self.hugepage_2mb_count = self.params.get('hugepage_2mb_count',
                                                  default=2000)
        self.hugepage_1gb_count = self.params.get('hugepage_1gb_count',
                                                  default=200)
        self.smt_iterations = self.params.get('smt_iterations', default=10)
        self.hugepage_sleep = self.params.get('hugepage_sleep', default=3)
        self.smt_sleep = self.params.get('smt_sleep', default=2)

        # Check if 1GB hugepages are available
        hp_1gb = "/sys/kernel/mm/hugepages/hugepages-1048576kB/nr_hugepages"
        self.hugepage_1gb_path = hp_1gb
        if not os.path.exists(self.hugepage_1gb_path):
            self.log.warning("1GB hugepages not available, "
                             "will only test 2MB hugepages")
            self.hugepage_1gb_path = None

        # Store initial state
        smt_out = process.system_output("ppc64_cpu --smt", shell=True)
        self.initial_smt = smt_out.decode().strip()
        hp_2mb = genio.read_file("/proc/sys/vm/nr_hugepages").strip()
        self.initial_hugepages_2mb = hp_2mb
        if self.hugepage_1gb_path:
            hp_1gb = genio.read_file(self.hugepage_1gb_path).strip()
            self.initial_hugepages_1gb = hp_1gb

        self.log.info("Initial SMT state: %s", self.initial_smt)
        self.log.info("Initial 2MB hugepages: %s", self.initial_hugepages_2mb)
        if self.hugepage_1gb_path:
            self.log.info("Initial 1GB hugepages: %s",
                          self.initial_hugepages_1gb)

        # Thread control
        self.stop_threads = False
        self.test1_error = None
        self.test2_error = None

    def hugepage_stress_test(self):
        """
        Test1 - Continuously allocate and deallocate hugepages
        """
        try:
            start_time = time.time()
            iteration = 0

            while not self.stop_threads and \
                    (time.time() - start_time) < self.test_duration:
                iteration += 1
                self.log.info("[Hugepage Test] Iteration %d", iteration)

                # Allocate 2MB hugepages
                msg = "[Hugepage Test] Allocating %d 2MB hugepages"
                self.log.info(msg, self.hugepage_2mb_count)
                genio.write_file("/proc/sys/vm/nr_hugepages",
                                 str(self.hugepage_2mb_count))
                allocated_2mb = genio.read_file(
                    "/proc/sys/vm/nr_hugepages").strip()
                self.log.info("[Hugepage Test] 2MB hugepages allocated: %s",
                              allocated_2mb)

                # Allocate 1GB hugepages if available
                if self.hugepage_1gb_path:
                    msg = "[Hugepage Test] Allocating %d 1GB hugepages"
                    self.log.info(msg, self.hugepage_1gb_count)
                    genio.write_file(self.hugepage_1gb_path,
                                     str(self.hugepage_1gb_count))
                    allocated_1gb = genio.read_file(
                        self.hugepage_1gb_path).strip()
                    msg = "[Hugepage Test] 1GB hugepages allocated: %s"
                    self.log.info(msg, allocated_1gb)

                time.sleep(self.hugepage_sleep)

                # Deallocate hugepages
                self.log.info("[Hugepage Test] Removing hugepages")
                genio.write_file("/proc/sys/vm/nr_hugepages", "0")
                freed_2mb = genio.read_file("/proc/sys/vm/nr_hugepages")
                freed_2mb = freed_2mb.strip()
                msg = "[Hugepage Test] 2MB hugepages after removal: %s"
                self.log.info(msg, freed_2mb)

                if self.hugepage_1gb_path:
                    genio.write_file(self.hugepage_1gb_path, "0")
                    freed_1gb = genio.read_file(self.hugepage_1gb_path)
                    freed_1gb = freed_1gb.strip()
                    msg = "[Hugepage Test] 1GB hugepages after removal: %s"
                    self.log.info(msg, freed_1gb)

                time.sleep(self.hugepage_sleep)

        except Exception as e:
            self.test1_error = "Hugepage test failed - %s" % str(e)
            self.log.error(self.test1_error)

    def smt_switching_test(self):
        """
        Test2 - Continuously switch between different SMT levels
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

                    # Switch SMT level
                    self.log.info("[SMT Test] Switching to SMT=%s",
                                  smt_level)
                    cmd = "ppc64_cpu --smt=%s" % smt_level
                    result = process.run(cmd, shell=True, sudo=True,
                                         ignore_status=True)

                    if result.exit_status != 0:
                        stderr = result.stderr.decode()
                        msg = "[SMT Test] Failed to set SMT=%s - %s"
                        self.log.warning(msg, smt_level, stderr)

                    # Get CPU info
                    info_output = process.system_output(
                        "ppc64_cpu --info", shell=True).decode()
                    self.log.debug("[SMT Test] CPU Info \n%s", info_output)

                    time.sleep(self.smt_sleep)

                    # Verify SMT state
                    smt_output = process.system_output(
                        "ppc64_cpu --smt", shell=True)
                    current_smt = smt_output.decode().strip()
                    self.log.info("[SMT Test] Current SMT state - %s",
                                  current_smt)

        except Exception as e:
            self.test2_error = "SMT test failed - %s" % str(e)
            self.log.error(self.test2_error)

    def test_parallel_hugepage_smt(self):
        """
        Main test - Run hugepage and SMT tests in parallel
        """
        self.log.info("=" * 80)
        msg = "Starting parallel hugepage allocation and SMT switching test"
        self.log.info(msg)
        self.log.info("Test duration - %d seconds", self.test_duration)
        self.log.info("SMT iterations - %d", self.smt_iterations)
        self.log.info("=" * 80)

        # Create threads for parallel execution
        thread1 = threading.Thread(target=self.hugepage_stress_test,
                                   name="HugepageTest")
        thread2 = threading.Thread(target=self.smt_switching_test,
                                   name="SMTTest")

        # Start both threads
        self.log.info("Starting both test threads...")
        thread1.start()
        thread2.start()

        # Wait for both threads to complete
        thread1.join()
        thread2.join()

        self.log.info("Both test threads completed")

        # Check for errors
        if self.test1_error:
            self.fail(self.test1_error)
        if self.test2_error:
            self.fail(self.test2_error)

        self.log.info("=" * 80)
        msg = "Test completed successfully - no crashes or hangs detected"
        self.log.info(msg)
        self.log.info("=" * 80)

    def tearDown(self):
        """
        Cleanup - Restore initial state
        """
        self.log.info("Cleaning up and restoring initial state...")

        # Stop threads if still running
        self.stop_threads = True
        time.sleep(2)

        # Restore initial hugepage settings
        try:
            genio.write_file("/proc/sys/vm/nr_hugepages",
                             self.initial_hugepages_2mb)
            if self.hugepage_1gb_path:
                genio.write_file(self.hugepage_1gb_path,
                                 self.initial_hugepages_1gb)
            self.log.info("Hugepage settings restored")
        except Exception as e:
            self.log.warning("Failed to restore hugepage settings - %s", e)

        # Restore initial SMT state
        try:
            # Extract SMT level from initial state (e.g., "SMT=4" -> "4")
            if "SMT=" in self.initial_smt:
                smt_value = self.initial_smt.split("SMT=")[1].split()[0]
                process.system("ppc64_cpu --smt=%s" % smt_value,
                               ignore_status=True)
            elif "off" in self.initial_smt.lower():
                process.system("ppc64_cpu --smt=off", ignore_status=True)
            self.log.info("SMT state restored to - %s", self.initial_smt)
        except Exception as e:
            self.log.warning("Failed to restore SMT state - %s", e)
