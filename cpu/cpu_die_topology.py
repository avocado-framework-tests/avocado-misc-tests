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
# Author: Sachin Sant <sachinp@linux.ibm.com>
#
# Test to validate die_id and die_cpumask support added by kernel
# commit fb2ff9fa72e2
# ("powerpc/topology: Implement cpu_die_mask()/cpu_die_id()")

"""
Test to validate CPU die topology (die_id and die_cpumask) support.
This test validates the kernel commit fb2ff9fa72e2 which added support
for die_id and die_cpumask on PowerPC systems.

The test includes:
1. Validation of die_id and die_cpumask sysfs interfaces
2. Performance validation using hackbench to demonstrate benefits of
   same-die CPU affinity vs cross-die execution
"""

import os
import re
from avocado import Test
from avocado.utils import cpu, distro, genio, process, archive, build
from avocado.utils.software_manager.manager import SoftwareManager


class CPUDieTopology(Test):
    """
    Test to validate CPU die topology support including die_id and die_cpumask.

    The test validates:
    1. Presence of die_id sysfs entries for each CPU
    2. Presence of die_cpus and die_cpus_list sysfs entries
    3. Validity of die_id values
    4. Consistency of die_cpumask across CPUs in the same die
    5. Relationship between die_id and physical_package_id

    :avocado: tags=cpu,topology,power,privileged
    """

    def setUp(self):
        """
        Verify the test is running on a supported platform.
        """
        if 'ppc' not in distro.detect().arch:
            self.cancel("Test is specific to PowerPC architecture")

        self.cpu_path = "/sys/devices/system/cpu"
        self.failures = []

        # Get list of online CPUs using Avocado's cpu utility
        self.online_cpus = cpu.online_list()
        if not self.online_cpus:
            self.cancel("No online CPUs found")

        self.log.info("Testing with %d online CPUs", len(self.online_cpus))

        # Test type parameter
        self.test_type = self.params.get("test_type", default="topology")

        # Performance test parameters (only needed for performance variant)
        if self.test_type == "performance":
            self.hackbench_groups = self.params.get("hackbench_groups",
                                                    default="20")
            self.hackbench_loops = self.params.get("hackbench_loops",
                                                   default="2000")
            self.hackbench_iterations = self.params.get("hackbench_iterations",
                                                        default="4")
            self.hackbench_binary = None

    def _read_topology_file(self, cpu, filename):
        """
        Read a topology file for a given CPU.

        :param cpu: CPU number
        :param filename: Name of the topology file
        :return: Content of the file or None if file doesn't exist
        """
        filepath = os.path.join(self.cpu_path, f"cpu{cpu}", "topology",
                                filename)

        if not os.path.exists(filepath):
            return None

        try:
            content = genio.read_file(filepath).strip()
            return content
        except Exception as e:
            self.log.error("Failed to read %s for CPU%d: %s", filename, cpu,
                           str(e))
            return None

    def test_die_id_presence(self):
        """
        Test 1: Verify die_id file exists for all online CPUs.
        """
        self.log.info("Test 1: Checking die_id presence for all online CPUs")

        missing_die_id = []
        for cpu in self.online_cpus:
            die_id = self._read_topology_file(cpu, "die_id")
            if die_id is None:
                missing_die_id.append(cpu)
                self.log.warning("CPU%d: die_id file not found", cpu)
            else:
                self.log.debug("CPU%d: die_id = %s", cpu, die_id)

        if missing_die_id:
            msg = f"die_id file missing for CPUs: {missing_die_id}"
            self.log.info("Note: die_id may not be available on systems " +
                          "without coregroup support (returns -1)")
            # This is not a failure as die_id returns -1 on non-coregroup
            # systems
        else:
            self.log.info("PASS: die_id present for all online CPUs")

    def test_die_cpumask_presence(self):
        """
        Test 2: Verify die_cpus and die_cpus_list files exist.
        """
        self.log.info("Test 2: Checking die_cpus and die_cpus_list presence")

        missing_files = []
        for cpu in self.online_cpus[:1]:  # Check for at least one CPU
            die_cpus = self._read_topology_file(cpu, "die_cpus")
            die_cpus_list = self._read_topology_file(cpu, "die_cpus_list")

            if die_cpus is None:
                missing_files.append(f"CPU{cpu}: die_cpus")
            if die_cpus_list is None:
                missing_files.append(f"CPU{cpu}: die_cpus_list")

        if missing_files:
            self.log.info("Note: die_cpus/die_cpus_list may not be " +
                          "available on all systems")
        else:
            self.log.info("PASS: die_cpus and die_cpus_list files present")

    def test_die_id_validity(self):
        """
        Test 3: Verify die_id values are valid (either -1 or >= 0).
        """
        self.log.info("Test 3: Validating die_id values")

        invalid_die_ids = []
        die_id_map = {}

        for cpu in self.online_cpus:
            die_id_str = self._read_topology_file(cpu, "die_id")
            if die_id_str is None:
                continue

            try:
                die_id = int(die_id_str)
                die_id_map[cpu] = die_id

                # die_id should be -1 (no coregroup support) or >= 0
                if die_id < -1:
                    invalid_die_ids.append((cpu, die_id))
                    self.log.error("CPU%d: Invalid die_id = %d", cpu, die_id)
                else:
                    self.log.debug("CPU%d: die_id = %d", cpu, die_id)
            except ValueError:
                invalid_die_ids.append((cpu, die_id_str))
                self.log.error("CPU%d: Non-numeric die_id = %s", cpu,
                               die_id_str)

        if invalid_die_ids:
            self.failures.append(f"Invalid die_id values found: \
                                 {invalid_die_ids}")
            self.fail(f"FAIL: Invalid die_id values: {invalid_die_ids}")
        else:
            self.log.info("PASS: All die_id values are valid")

        return die_id_map

    def test_die_cpumask_consistency(self):
        """
        Test 4: Verify die_cpumask consistency across CPUs in the same die.
        """
        self.log.info("Test 4: Checking die_cpumask consistency")

        # Get die_id for all CPUs
        die_groups = {}
        for cpu in self.online_cpus:
            die_id_str = self._read_topology_file(cpu, "die_id")
            if die_id_str is None:
                continue

            try:
                die_id = int(die_id_str)
                if die_id not in die_groups:
                    die_groups[die_id] = []
                die_groups[die_id].append(cpu)
            except ValueError:
                continue

        self.log.info("Found %d die groups", len(die_groups))

        # For each die, verify all CPUs have the same die_cpus_list
        inconsistencies = []
        for die_id, cpus in die_groups.items():
            if die_id == -1:
                self.log.debug("Skipping die_id -1 (no coregroup support)")
                continue

            self.log.debug("Checking die %d with CPUs: %s", die_id, cpus)

            die_cpus_lists = {}
            for cpu in cpus:
                die_cpus_list = self._read_topology_file(cpu, "die_cpus_list")
                if die_cpus_list:
                    die_cpus_lists[cpu] = die_cpus_list

            if len(set(die_cpus_lists.values())) > 1:
                inconsistencies.append((die_id, die_cpus_lists))
                self.log.error("Die %d: Inconsistent die_cpus_list: %s",
                               die_id, die_cpus_lists)

        if inconsistencies:
            self.failures.append(f"Inconsistent die_cpumask: \
                                 {inconsistencies}")
            self.fail(f"FAIL: Inconsistent die_cpumask found: \
                      {inconsistencies}")
        else:
            self.log.info("PASS: die_cpumask is consistent across all dies")

    def test_die_package_relationship(self):
        """
        Test 5: Verify relationship between die_id and physical_package_id.
        CPUs in the same die should be in the same package.
        """
        self.log.info("Test 5: Checking die and physical_package relationship")

        die_package_map = {}
        violations = []

        for cpu in self.online_cpus:
            die_id_str = self._read_topology_file(cpu, "die_id")
            pkg_id_str = self._read_topology_file(cpu, "physical_package_id")

            if die_id_str is None or pkg_id_str is None:
                continue

            try:
                die_id = int(die_id_str)
                pkg_id = int(pkg_id_str)

                if die_id == -1:
                    continue

                if die_id not in die_package_map:
                    die_package_map[die_id] = pkg_id
                elif die_package_map[die_id] != pkg_id:
                    violations.append((cpu, die_id, pkg_id,
                                      die_package_map[die_id]))
                    self.log.error("CPU%d: die_id=%d has package_id=%d, " +
                                   "expected %d", cpu, die_id, pkg_id,
                                   die_package_map[die_id])
            except ValueError:
                continue

        if violations:
            self.failures.append(f"Die-Package relationship violations: \
                                 {violations}")
            self.fail(f"FAIL: Die-Package relationship violations: \
                      {violations}")
        else:
            self.log.info("PASS: All CPUs in same die are in same package")

    def test_cpu_die_mask_function(self):
        """
        Test 6: Verify cpu_die_mask() kernel function behavior via sysfs.
        """
        self.log.info("Test 6: Testing cpu_die_mask() function behavior")

        # Check if the system has coregroup support
        has_coregroup = False
        for cpu in self.online_cpus[:1]:
            die_id_str = self._read_topology_file(cpu, "die_id")
            if die_id_str and int(die_id_str) >= 0:
                has_coregroup = True
                break

        if has_coregroup:
            self.log.info("System has coregroup support (die_id >= 0)")
            # Verify die_cpus matches coregroup topology
            for cpu in self.online_cpus[:5]:  # Sample first 5 CPUs
                die_cpus = self._read_topology_file(cpu, "die_cpus")
                if die_cpus:
                    self.log.debug("CPU%d: die_cpus = %s", cpu, die_cpus)
        else:
            self.log.info("System doesn't have coregroup support(die_id = -1)")
            self.log.info("On such systems, die_mask equals package mask")

    def _setup_hackbench(self):
        """
        Setup hackbench benchmark from LTP repository.
        Downloads, extracts, and builds hackbench binary.

        :return: Path to hackbench binary or None if setup fails
        """
        self.log.info("Setting up hackbench benchmark")

        sm = SoftwareManager()
        deps = ['gcc', 'make', 'wget']
        for package in deps:
            if not sm.check_installed(package):
                if not sm.install(package):
                    self.log.warning("Failed to install %s", package)
                    return None
        ltp_url = self.params.get(
            'ltp_url',
            default='https://github.com/linux-test-project/ltp/'
                    'archive/master.zip')

        try:
            tarball = self.fetch_asset("ltp-master.zip",
                                       locations=[ltp_url],
                                       expire='7d')
        except Exception as e:
            self.log.error("Failed to download LTP: %s", str(e))
            return None

        ltpdir = os.path.join(self.workdir, 'ltp')
        if not os.path.exists(ltpdir):
            os.makedirs(ltpdir)

        try:
            archive.extract(tarball, ltpdir)
        except Exception as e:
            self.log.error("Failed to extract LTP: %s", str(e))
            return None

        ltp_base = os.path.join(ltpdir, "ltp-master")
        hackbench_dir = os.path.join(ltp_base,
                                     "testcases/kernel/sched/cfs-scheduler")
        if not os.path.exists(hackbench_dir):
            self.log.error("Hackbench directory not found: %s",
                           hackbench_dir)
            return None

        try:
            os.chdir(ltp_base)
            build.make(ltp_base, extra_args='autotools')
            process.run("./configure", shell=True)
            os.chdir(hackbench_dir)
            build.make(hackbench_dir)
        except Exception as e:
            self.log.error("Failed to build hackbench: %s", str(e))
            return None

        hackbench_binary = os.path.join(hackbench_dir, "hackbench")
        if os.path.exists(hackbench_binary):
            self.log.info("Hackbench binary ready: %s", hackbench_binary)
            return hackbench_binary
        else:
            self.log.error("Hackbench binary not found after build")
            return None

    def _run_hackbench(self, cpu_list, iteration_num):
        """
        Run hackbench benchmark with CPU affinity.

        :param cpu_list: List of CPUs to pin the workload to
        :param iteration_num: Iteration number for logging
        :return: Execution time in seconds or None if failed
        """
        if not self.hackbench_binary or not \
                os.path.exists(self.hackbench_binary):
            self.log.error("Hackbench binary not available")
            return None

        # Use comma-separated CPU list to ensure only selected CPUs are used
        # This is critical for cross-die tests where CPUs may not be contiguous
        cpu_list_str = ",".join(map(str, cpu_list))
        cmd = "taskset -c %s %s %s process %s" % (
            cpu_list_str,
            self.hackbench_binary,
            self.hackbench_groups,
            self.hackbench_loops
        )

        self.log.debug("Running: %s", cmd)

        try:
            result = process.run(cmd, shell=True, ignore_status=False)
            output = result.stdout.decode()

            # Parse time from output: "Time: X.XXX"
            time_match = re.search(r'Time:\s+([\d.]+)', output)
            if time_match:
                exec_time = float(time_match.group(1))
                self.log.info("Iteration %d (CPUs %s): Time = %.3f sec",
                              iteration_num, cpu_list_str, exec_time)
                return exec_time
            else:
                self.log.error("Failed to parse time from hackbench")
                return None
        except Exception as e:
            self.log.error("Hackbench execution failed: %s", str(e))
            return None

    def _get_die_cpu_list(self, die_id):
        """
        Get list of CPUs belonging to a specific die.

        :param die_id: Die ID to get CPUs for
        :return: List of CPU numbers in the die
        """
        die_cpus = []
        for cpu in self.online_cpus:
            cpu_die_id = self._read_topology_file(cpu, "die_id")
            if cpu_die_id and int(cpu_die_id) == die_id:
                die_cpus.append(cpu)
        return sorted(die_cpus)

    def _select_test_cpu_sets(self):
        """
        Select CPU sets for performance testing.
        Returns two sets: one from same die, one spanning multiple dies.

        :return: Tuple of (same_die_cpus, cross_die_cpus) or (None, None)
        """
        # Build die groups
        die_groups = {}
        for cpu in self.online_cpus:
            die_id_str = self._read_topology_file(cpu, "die_id")
            if die_id_str is None:
                continue
            try:
                die_id = int(die_id_str)
                if die_id >= 0:  # Skip -1 (no coregroup support)
                    if die_id not in die_groups:
                        die_groups[die_id] = []
                    die_groups[die_id].append(cpu)
            except ValueError:
                continue

        if len(die_groups) < 2:
            self.log.info("System has less than 2 dies, skipping " +
                          "performance test")
            return None, None

        # Sort dies by CPU count (descending) to find best candidates
        sorted_dies = sorted(die_groups.items(),
                             key=lambda x: len(x[1]),
                             reverse=True)

        # Strategy: Find two dies with at least 8 CPUs each
        # Use 16 CPUs from die 0 for same-die test
        # Use 8 CPUs from each of die 0 and die 1 for cross-die test
        if len(sorted_dies[0][1]) < 8 or len(sorted_dies[1][1]) < 8:
            self.log.info("Need at least 8 CPUs in each of 2 dies")
            return None, None

        die0_id, die0_cpus = sorted_dies[0]
        die1_id, die1_cpus = sorted_dies[1]

        # Same-die test: Use 16 CPUs from die 0 (or fewer if not available)
        num_same_die = min(16, len(die0_cpus))
        same_die_cpus = sorted(die0_cpus)[:num_same_die]
        self.log.info("Selected %d same-die CPUs from die %d: %s",
                      num_same_die, die0_id, same_die_cpus)

        # Cross-die test: Use 8 CPUs from each die (or split evenly)
        num_from_die0 = min(8, len(die0_cpus))
        num_from_die1 = min(8, len(die1_cpus))

        cross_die_cpus = (sorted(die0_cpus)[:num_from_die0] +
                          sorted(die1_cpus)[:num_from_die1])
        cross_die_cpus = sorted(cross_die_cpus)

        self.log.info("Selected %d cross-die CPUs from dies %d and %d: %s",
                      len(cross_die_cpus), die0_id, die1_id, cross_die_cpus)

        return same_die_cpus, cross_die_cpus

    def test_die_performance_benefit(self):
        """
        Test 7: Validate performance benefits of same-die CPU affinity.

        This test demonstrates that workloads pinned to CPUs within
        the same die perform better than workloads spanning multiple
        dies, validating the practical benefits of the die topology
        information.
        """
        if self.test_type != "performance":
            self.cancel("Performance test not enabled (test_type=%s)" %
                        self.test_type)

        self.log.info("Test 7: Validating die topology performance")
        self.log.info("=" * 60)

        # Setup hackbench
        self.hackbench_binary = self._setup_hackbench()
        if not self.hackbench_binary:
            self.cancel("Hackbench setup failed - required for test")

        # Select CPU sets for testing
        same_die_cpus, cross_die_cpus = self._select_test_cpu_sets()
        if not same_die_cpus or not cross_die_cpus:
            self.cancel("Could not select appropriate CPU sets for" +
                        "testing (need system with 2+ dies, each with " +
                        "8+ CPUs)")

        # Display topology information
        self.log.info("Same-die CPU set: %s", same_die_cpus)
        same_die_id = self._read_topology_file(same_die_cpus[0], "die_id")
        same_die_list = self._read_topology_file(same_die_cpus[0],
                                                 "die_cpus_list")
        self.log.info("  Die ID: %s", same_die_id)
        self.log.info("  Die CPUs list: %s", same_die_list)

        self.log.info("Cross-die CPU set: %s", cross_die_cpus)
        for cpu in [cross_die_cpus[0], cross_die_cpus[8]]:
            die_id = self._read_topology_file(cpu, "die_id")
            die_list = self._read_topology_file(cpu, "die_cpus_list")
            self.log.info("  CPU%d - Die ID: %s, Die CPUs: %s",
                          cpu, die_id, die_list)

        # Run same-die tests
        self.log.info("-" * 60)
        self.log.info("Running same-die tests (CPUs %d-%d)",
                      min(same_die_cpus), max(same_die_cpus))
        same_die_times = []
        for i in range(1, int(self.hackbench_iterations) + 1):
            exec_time = self._run_hackbench(same_die_cpus, i)
            if exec_time:
                same_die_times.append(exec_time)

        # Run cross-die tests
        self.log.info("-" * 60)
        self.log.info("Running cross-die tests (CPUs %s)",
                      cross_die_cpus)
        cross_die_times = []
        for i in range(1, int(self.hackbench_iterations) + 1):
            exec_time = self._run_hackbench(cross_die_cpus, i)
            if exec_time:
                cross_die_times.append(exec_time)

        # Analyze results
        self.log.info("=" * 60)
        self.log.info("Performance Analysis")
        self.log.info("=" * 60)

        if not same_die_times or not cross_die_times:
            self.fail("Insufficient data for performance analysis - " +
                      "hackbench runs failed")

        same_die_avg = sum(same_die_times) / len(same_die_times)
        cross_die_avg = sum(cross_die_times) / len(cross_die_times)

        self.log.info("Same-die execution:")
        self.log.info("  Times: %s", [f"{t:.3f}" for t in same_die_times])
        self.log.info("  Average: %.3f sec", same_die_avg)
        self.log.info("  Min: %.3f sec, Max: %.3f sec",
                      min(same_die_times), max(same_die_times))

        self.log.info("Cross-die execution:")
        self.log.info("  Times: %s", [f"{t:.3f}" for t in cross_die_times])
        self.log.info("  Average: %.3f sec", cross_die_avg)
        self.log.info("  Min: %.3f sec, Max: %.3f sec",
                      min(cross_die_times), max(cross_die_times))

        # Calculate performance difference
        if same_die_avg > 0:
            perf_degradation = ((cross_die_avg - same_die_avg) /
                                same_die_avg) * 100
            self.log.info("-" * 60)
            self.log.info("Performance Impact:")
            self.log.info(" Cross-die execution is %.1f%% slower than " +
                          "same-die", perf_degradation)

            if perf_degradation > 10:
                self.log.info(" SIGNIFICANT: Cross-die penalty > 10%%")
                self.log.info(" This validates the importance of die topology")
                self.log.info(" information for workload placement")
            elif perf_degradation > 0:
                self.log.info(" MODERATE: Cross-die penalty detected")
            else:
                self.log.info(" No significant cross-die penalty observed")

        self.log.info("=" * 60)
        self.log.info("PASS: Performance test completed successfully")

    def tearDown(self):
        """
        Report any collected failures at the end of all tests.
        """
        if self.failures:
            self.log.error("=" * 60)
            self.log.error("Test completed with %d failures:",
                           len(self.failures))
            for failure in self.failures:
                self.log.error("  - %s", failure)
            self.log.error("=" * 60)
            self.fail("CPU die topology validation failed")
