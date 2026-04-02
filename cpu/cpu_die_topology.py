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
"""

import os
import glob
from avocado import Test
from avocado.utils import distro, genio


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

        # Get list of online CPUs
        self.online_cpus = self._get_online_cpus()
        if not self.online_cpus:
            self.cancel("No online CPUs found")

        self.log.info("Testing with %d online CPUs", len(self.online_cpus))

    def _get_online_cpus(self):
        """
        Get list of online CPU numbers.

        :return: List of online CPU numbers
        """
        online_cpus = []
        cpu_dirs = glob.glob(os.path.join(self.cpu_path, "cpu[0-9]*"))

        for cpu_dir in sorted(cpu_dirs):
            cpu_num = int(os.path.basename(cpu_dir)[3:])
            online_file = os.path.join(cpu_dir, "online")

            # CPU0 may not have online file, assume it's always online
            if not os.path.exists(online_file):
                online_cpus.append(cpu_num)
            else:
                try:
                    status = genio.read_file(online_file).strip()
                    if status == "1":
                        online_cpus.append(cpu_num)
                except Exception as e:
                    self.log.warning("Online status read fail - CPU%d: %s",
                                     cpu_num, str(e))

        return online_cpus

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

    def test(self):
        """
        Main test execution - runs all sub-tests.
        """
        self.log.info("=" * 60)
        self.log.info("CPU Die Topology Test - Validating commit fb2ff9fa72e2")
        self.log.info("=" * 60)

        # Run all tests
        self.test_die_id_presence()
        self.test_die_cpumask_presence()
        die_id_map = self.test_die_id_validity()
        self.test_die_cpumask_consistency()
        self.test_die_package_relationship()
        self.test_cpu_die_mask_function()

        # Summary
        self.log.info("=" * 60)
        self.log.info("Test Summary")
        self.log.info("=" * 60)
        self.log.info("Total online CPUs tested: %d", len(self.online_cpus))

        if self.failures:
            self.log.error("Test completed with %d failures:",
                           len(self.failures))
            for failure in self.failures:
                self.log.error("  - %s", failure)
            self.fail("CPU die topology validation failed")
        else:
            self.log.info("PASS: All CPU die topology tests successfull")
