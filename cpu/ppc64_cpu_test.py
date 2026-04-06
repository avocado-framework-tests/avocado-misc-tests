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
# Author: Narasimhan V <sim@linux.vnet.ibm.com>
# Modified by: Samir A <samir@linux.ibm.com>

"""
Test to verify ppc64_cpu command.
"""

import os
import re
import random
import time
from avocado import Test
from avocado.utils import process
from avocado.utils import cpu
from avocado.utils import distro, build, archive
from avocado.utils import genio
from avocado.utils.software_manager.manager import SoftwareManager
from math import ceil


class PPC64Test(Test):
    """
    Test to verify ppc64_cpu command for different supported values.

    :avocado: tags=cpu,power,privileged
    """

    def setUp(self):
        """
        Verifies if powerpc-utils is installed, and gets current SMT value.
        """
        if 'ppc' not in distro.detect().arch:
            self.cancel("Processor is not ppc64")
        self.sm = SoftwareManager()
        if not self.sm.check_installed("powerpc-utils"):
            if not self.sm.install("powerpc-utils"):
                self.cancel("Cannot install powerpc-utils, check the log!")

        self.loop = int(self.params.get('test_loop', default=100))
        self.run_type = self.params.get('type', default='distro')
        self.smt_str = "ppc64_cpu --smt"
        # Dynamically set max SMT specified at boot time
        process.system("%s=on" % self.smt_str, shell=True)
        # and get its value
        smt_op = process.system_output(self.smt_str, shell=True).decode()
        if "is not SMT capable" in smt_op:
            self.cancel("Machine is not SMT capable")
        if "Inconsistent state" in smt_op:
            self.cancel("Machine has mix of ST and SMT cores")

        self.curr_smt = smt_op.strip().split("=")[-1].split()[-1]
        self.smt_subcores = 0
        if os.path.exists("/sys/devices/system/cpu/subcores_per_core"):
            self.smt_subcores = 1
        self.failures = []
        self.failure_count = 0
        self.failure_message = "\n"
        self.smt_values = {1: "off"}
        self.key = 0
        self.value = ""
        self.max_smt_value = int(self.curr_smt)

        # Get total cores for dynamic tests
        cores_output = process.system_output("ppc64_cpu --cores-present",
                                             shell=True).decode()
        self.total_cores = int(cores_output.strip().split()[-1])

        # Generate all possible SMT values dynamically
        self.all_smt_values = self._generate_smt_values()

        # Test parameters - all configurable via YAML
        self.stress_iterations = int(
            self.params.get('stress_iterations', default=20))
        self.parallel_iterations = int(
            self.params.get('parallel_iterations', default=3))
        self.random_iterations = int(
            self.params.get('random_iterations', default=50))
        self.num_parallel_threads = int(
            self.params.get('num_parallel_threads', default=4))

        # Test execution flags
        self.run_all_smt_operations = self.params.get(
            'run_all_smt_operations', default=True)
        self.run_dynamic_core_operations = self.params.get(
            'run_dynamic_core_operations', default=True)
        self.run_smt_core_interaction = self.params.get(
            'run_smt_core_interaction', default=True)
        self.run_random_stress = self.params.get(
            'run_random_stress', default=True)
        self.run_parallel_operations = self.params.get(
            'run_parallel_operations', default=True)
        self.run_progressive_core_online = self.params.get(
            'run_progressive_core_online', default=True)
        self.run_specific_cores_offline = self.params.get(
            'run_specific_cores_offline', default=True)

        # Verification options
        self.enable_comprehensive_verification = self.params.get(
            'enable_comprehensive_verification', default=True)
        self.verify_after_each_operation = self.params.get(
            'verify_after_each_operation', default=True)

        # Timing options
        self.sleep_after_smt_change = float(
            self.params.get('sleep_after_smt_change', default=1))
        self.sleep_after_core_change = float(
            self.params.get('sleep_after_core_change', default=1))
        self.sleep_between_operations = float(
            self.params.get('sleep_between_operations', default=0.3))

        # Logging options
        self.verbose_logging = self.params.get('verbose_logging', default=True)
        self.log_dmesg = self.params.get('log_dmesg', default=True)

        self.log.info("Total cores: %s, Max SMT: %s",
                      self.total_cores, self.max_smt_value)
        self.log.info("All SMT values to test: %s", self.all_smt_values)
        self.log.info("Test iterations: stress=%s, parallel=%s, random=%s",
                      self.stress_iterations, self.parallel_iterations, self.random_iterations)

    def _generate_smt_values(self):
        """
        Generate all possible SMT values dynamically based on system capability.
        """
        smt_values = ['off']
        for i in range(2, self.max_smt_value + 1):
            smt_values.append(str(i))
        smt_values.append('on')
        return smt_values

    def test_build_upstream(self):
        """
        For upstream target download and compile source code
        Caution : This function will overwrite system installed
        lsvpd Tool binaries with upstream code.
        """
        if self.run_type == 'upstream':
            self.detected_distro = distro.detect()
            deps = ['gcc', 'make', 'automake', 'autoconf', 'bison', 'flex',
                    'libtool', 'zlib-devel', 'ncurses-devel', 'librtas-devel']
            if 'SuSE' in self.detected_distro.name:
                deps.extend(['libnuma-devel'])
            elif self.detected_distro.name in ['centos', 'fedora', 'rhel']:
                deps.extend(['numactl-devel'])
            else:
                self.cancel("Unsupported Linux distribution")
            for package in deps:
                if not self.sm.check_installed(package) and not \
                        self.sm.install(package):
                    self.cancel("Fail to install %s required for this test." %
                                package)
            url = self.params.get(
                'ppcutils_url', default='https://github.com/'
                'ibm-power-utilities/powerpc-utils/archive/refs/heads/'
                'master.zip')
            tarball = self.fetch_asset('ppcutils.zip', locations=[url],
                                       expire='7d')
            archive.extract(tarball, self.workdir)
            self.sourcedir = os.path.join(self.workdir, 'powerpc-utils-master')
            os.chdir(self.sourcedir)
            cmd_result = process.run('./autogen.sh', ignore_status=True,
                                     sudo=True, shell=True)
            if cmd_result.exit_status:
                self.fail('Upstream build: Pre configure step failed')
            cmd_result = process.run('./configure --prefix=/usr',
                                     ignore_status=True, sudo=True, shell=True)
            if cmd_result.exit_status:
                self.fail('Upstream build: Configure step failed')
            build.make(self.sourcedir)
            build.make(self.sourcedir, extra_args='install')
        else:
            self.cancel("This test is supported with upstream as target")

    def equality_check(self, test_name, cmd1, cmd2):
        """
        Verifies if the output of 2 commands are same, and sets failure
        count accordingly.

        :params test_name: Test Name
        :params cmd1: Command 1
        :params cmd2: Command 2
        """
        self.log.info("Testing %s", test_name)
        if str(cmd1) != str(cmd2):
            self.failure_count += 1
            self.failure_message += "%s test failed when SMT=%s\n" \
                % (test_name, self.key)
            self.failures.append("%s test failed when SMT=%s" %
                                 (test_name, self.key))

    def test_cmd_options(self):
        """
        Sets the SMT value, and calls each of the test, for each value.
        """
        for i in range(2, self.max_smt_value):
            self.smt_values[i] = str(i)
        for self.key, self.value in self.smt_values.items():
            process.system_output("%s=%s" % (self.smt_str,
                                             self.key), shell=True)
            process.system_output("ppc64_cpu --info")
            self.smt()
            self.core()
            if self.smt_subcores == 1:
                self.subcore()
            self.threads_per_core()
            self.dscr()

        if self.failure_count > 0 or self.failures:
            self.log.debug("Number of failures is %s", self.failure_count)
            self.log.debug(self.failure_message)
            if self.failures:
                self.log.debug("Failure list: %s", self.failures)
            self.fail()

    def smt(self):
        """
        Tests the SMT in ppc64_cpu command.
        """
        op1 = process.system_output(
            self.smt_str,
            shell=True).decode("utf-8").strip().split("=")[-1].split()[-1]
        self.equality_check("SMT", op1, self.value)

    def core(self):
        """
        Tests the core in ppc64_cpu command.
        """
        op1 = process.system_output(
            "ppc64_cpu --cores-present",
            shell=True).decode("utf-8").strip().split()[-1]
        op2 = cpu.online_cpus_count() / int(self.key)
        self.equality_check("Core", op1, ceil(op2))

    def subcore(self):
        """
        Tests the subcores in ppc64_cpu command.
        """
        op1 = process.system_output(
            "ppc64_cpu --subcores-per-core",
            shell=True).decode("utf-8").strip().split()[-1]
        op2 = genio.read_file(
            "/sys/devices/system/cpu/subcores_per_core").strip()
        self.equality_check("Subcore", op1, op2)

    def threads_per_core(self):
        """
        Tests the threads per core in ppc64_cpu command.
        """
        op1 = process.system_output(
            "ppc64_cpu --threads-per-core",
            shell=True).decode("utf-8").strip().split()[-1]
        op2 = process.system_output("ppc64_cpu --info",
                                    shell=True).decode("utf-8")
        op2 = len(op2.strip().splitlines()[0].split(":")[-1].split())
        self.equality_check("Threads per core", op1, ceil(op2))

    def dscr(self):
        """
        Tests the dscr in ppc64_cpu command.
        """
        op1 = process.system_output(
            "ppc64_cpu --dscr", shell=True).decode("utf-8").strip().split()[-1]
        op2 = int(genio.read_file(
            "/sys/devices/system/cpu/dscr_default").strip(), 16)
        self.equality_check("DSCR", op1, op2)

    def test_smt_loop(self):
        """
        Tests smt on/off in a loop
        """
        for _ in range(1, self.loop):
            if process.system("%s=off && %s=on" % (self.smt_str, self.smt_str),
                              shell=True):
                self.fail('SMT loop test failed')

    def test_single_core_smt(self):
        """
        Test smt level change when single core is online. This
        scenario was attempted to catch a regression.

        ppc64_cpu --cores-on=all
        ppc64_cpu —-smt=on
        ppc64_cpu --cores-on=1
        ppc64_cpu --cores-on
        ppc64_cpu --smt=2
        ppc64_cpu --smt=4
        ppc64_cpu --cores-on
           At this stage the number of online cores should be one.
           If not fail the test case

        """
        # online all cores
        process.system("ppc64_cpu --cores-on=all", shell=True)
        # Set highest SMT level
        process.system("ppc64_cpu --smt=on", shell=True)
        # online single core
        process.system("ppc64_cpu --cores-on=1", shell=True)
        # Record the output
        cores_on = process.system_output("ppc64_cpu --cores-on",
                                         shell=True).decode("utf-8")
        op1 = cores_on.strip().split("=")[-1]
        self.log.debug(op1)
        # Set 2 threads online
        process.system("ppc64_cpu --smt=2", shell=True)
        # Set 4 threads online
        process.system("ppc64_cpu --smt=4", shell=True)
        # Record the output
        cores_on = process.system_output("ppc64_cpu --cores-on",
                                         shell=True).decode("utf-8")
        op2 = cores_on.strip().split("=")[-1]
        self.log.debug(op2)
        if str(op1) != str(op2):
            self.fail("SMT with Single core test failed")

    def parse_lscpu_output(self):
        """
        Parse lscpu output to get online CPU count.
        Returns the count of online CPUs.
        """
        try:
            lscpu_output = process.system_output("lscpu", shell=True).decode()
            for line in lscpu_output.splitlines():
                if line.startswith("On-line CPU(s) list:"):
                    cpu_list = line.split(":")[-1].strip()
                    # Parse ranges like "0-79" or "0-39,80-119"
                    total = 0
                    for part in cpu_list.split(','):
                        if '-' in part:
                            start, end = map(int, part.split('-'))
                            total += (end - start + 1)
                        else:
                            total += 1
                    return total
            # Fallback: try "CPU(s):" line
            for line in lscpu_output.splitlines():
                if line.startswith("CPU(s):"):
                    return int(line.split(":")[-1].strip())
        except Exception as e:
            self.log.warning("Failed to parse lscpu: %s", str(e))
        return None

    def get_online_cpus_from_sysfs(self):
        """
        Get online CPU count from sysfs.
        """
        try:
            online_cpus = genio.read_file(
                "/sys/devices/system/cpu/online").strip()
            total = 0
            for part in online_cpus.split(','):
                if '-' in part:
                    start, end = map(int, part.split('-'))
                    total += (end - start + 1)
                else:
                    total += 1
            return total
        except Exception as e:
            self.log.warning("Failed to read sysfs online CPUs: %s", str(e))
        return None

    def get_online_cpus_from_proc(self):
        """
        Get online CPU count from /proc/cpuinfo.
        """
        try:
            cpuinfo = genio.read_file("/proc/cpuinfo")
            return cpuinfo.count("processor")
        except Exception as e:
            self.log.warning("Failed to read /proc/cpuinfo: %s", str(e))
        return None

    def parse_ppc64_cpu_info(self):
        """
        Parse ppc64_cpu --info output to get detailed core and thread information.
        Returns a dictionary with core details.
        """
        result = {
            'cores': {},
            'total_cores': 0,
            'online_cores': [],
            'offline_cores': [],
            'actual_threads_per_core': {},
            'smt_mode': None,
            'inconsistent': False
        }

        try:
            info_output = process.system_output(
                "ppc64_cpu --info", shell=True).decode()
            lines = info_output.strip().splitlines()

            for line in lines:
                # Parse lines like "Core   0:    0*   1*   2*   3*   4*   5*   6*   7*"
                match = re.match(r'Core\s+(\d+):\s+(.*)', line)
                if match:
                    core_num = int(match.group(1))
                    threads_str = match.group(2).strip()
                    threads = threads_str.split()

                    # Count online threads (marked with *)
                    online_threads = sum(1 for t in threads if '*' in t)
                    result['cores'][core_num] = {
                        'threads': threads,
                        'online_threads': online_threads
                    }
                    result['actual_threads_per_core'][core_num] = online_threads

                    # Categorize cores
                    if online_threads > 0:
                        result['online_cores'].append(core_num)
                    else:
                        result['offline_cores'].append(core_num)

            result['total_cores'] = len(result['cores'])

            # Check consistency ONLY among ONLINE cores
            if result['online_cores']:
                online_cores_threads = {core: result['actual_threads_per_core'][core]
                                        for core in result['online_cores']}
                unique_thread_counts = set(online_cores_threads.values())

                if len(unique_thread_counts) > 1:
                    result['inconsistent'] = True
                    self.log.warning(
                        "INCONSISTENT SMT STATE among online cores!")
                    self.log.warning(
                        "Online cores thread counts: %s", online_cores_threads)
                elif len(unique_thread_counts) == 1:
                    result['smt_mode'] = list(unique_thread_counts)[0]

        except Exception as e:
            self.log.error("Failed to parse ppc64_cpu --info: %s", str(e))

        return result

    def verify_system_state(self, expected_smt=None, expected_cores_on=None):
        """
        Comprehensive system state verification.
        Validates SMT mode, core count, and CPU count consistency.
        """
        self.log.info("=" * 60)
        self.log.info("SYSTEM STATE VERIFICATION")
        self.log.info("=" * 60)

        # Get ppc64_cpu info
        info = self.parse_ppc64_cpu_info()

        # Get SMT mode
        smt_output = process.system_output(
            "ppc64_cpu --smt", shell=True).decode()
        current_smt = smt_output.strip().split("=")[-1].split()[-1]

        # Get cores on
        cores_output = process.system_output(
            "ppc64_cpu --cores-on", shell=True).decode()
        cores_on = int(cores_output.strip().split("=")[-1])

        # Get online CPUs from multiple sources
        lscpu_cpus = self.parse_lscpu_output()
        sysfs_cpus = self.get_online_cpus_from_sysfs()
        proc_cpus = self.get_online_cpus_from_proc()

        self.log.info("Current SMT mode: %s", current_smt)
        self.log.info("Cores online: %d", cores_on)
        self.log.info("Online CPUs (lscpu): %s", lscpu_cpus)
        self.log.info("Online CPUs (sysfs): %s", sysfs_cpus)
        self.log.info("Online CPUs (/proc/cpuinfo): %s", proc_cpus)
        self.log.info("Total cores detected: %d", info['total_cores'])
        self.log.info("Online cores: %s", info['online_cores'])
        self.log.info("Offline cores: %s", info['offline_cores'])

        # Validation
        validation_passed = True

        # Check if SMT mode matches expected
        if expected_smt is not None:
            if str(current_smt) != str(expected_smt):
                self.log.error("SMT mismatch! Expected: %s, Got: %s",
                               expected_smt, current_smt)
                validation_passed = False

        # Check if cores_on matches expected
        if expected_cores_on is not None:
            if cores_on != expected_cores_on:
                self.log.error("Cores mismatch! Expected: %d, Got: %d",
                               expected_cores_on, cores_on)
                validation_passed = False

        # Check consistency among online cores
        if info['inconsistent']:
            self.log.error(
                "INCONSISTENT SMT STATE detected among online cores!")
            validation_passed = False

        # Verify CPU count formula: Online CPUs = Online Cores × SMT threads
        if current_smt != 'off' and info['smt_mode']:
            expected_cpus = cores_on * info['smt_mode']
            if lscpu_cpus and lscpu_cpus != expected_cpus:
                self.log.error("CPU count mismatch! Expected: %d (cores=%d × smt=%d), Got: %d",
                               expected_cpus, cores_on, info['smt_mode'], lscpu_cpus)
                validation_passed = False

        # Cross-validate CPU counts from different sources
        cpu_counts = [c for c in [lscpu_cpus,
                                  sysfs_cpus, proc_cpus] if c is not None]
        if len(set(cpu_counts)) > 1:
            self.log.warning(
                "CPU count mismatch across sources: %s", cpu_counts)

        self.log.info("=" * 60)
        if validation_passed:
            self.log.info("✓ VALIDATION PASSED")
        else:
            self.log.error("✗ VALIDATION FAILED")
        self.log.info("=" * 60)

        return validation_passed

    def get_cores_info(self):
        """
        Get current cores information.
        """
        cores_output = process.system_output(
            "ppc64_cpu --cores-on", shell=True).decode()
        cores_on = int(cores_output.strip().split("=")[-1])

        cores_present_output = process.system_output("ppc64_cpu --cores-present",
                                                     shell=True).decode()
        cores_present = int(cores_present_output.strip().split()[-1])

        return {
            'cores_on': cores_on,
            'cores_present': cores_present
        }

    def test_smt_with_core_operations(self):
        """
        Test SMT changes with various core online/offline operations.
        Verifies that SMT changes work correctly with different core configurations.
        """
        self.log.info("Testing SMT operations with core hotplug")

        # Get total cores
        cores_info = self.get_cores_info()
        total_cores = cores_info['cores_present']

        # Test different core counts (10%, 25%, 50%, 75%, 100%)
        core_percentages = [10, 25, 50, 75, 100]
        test_cores = [max(1, int(total_cores * p / 100))
                      for p in core_percentages]

        smt_values = ['off', '2', '4', 'on']

        for num_cores in test_cores:
            self.log.info("\n" + "=" * 60)
            self.log.info("Testing with %d cores online", num_cores)
            self.log.info("=" * 60)

            # Set cores online
            process.system("ppc64_cpu --cores-on=%d" % num_cores, shell=True)

            for smt_val in smt_values:
                self.log.info("\nSetting SMT=%s with %d cores",
                              smt_val, num_cores)
                process.system("ppc64_cpu --smt=%s" % smt_val, shell=True)

                # Verify state
                if not self.verify_system_state(expected_cores_on=num_cores):
                    self.fail("Verification failed for cores=%d, SMT=%s" %
                              (num_cores, smt_val))

                time.sleep(0.5)

    def test_parallel_smt_core_stress(self):
        """
        Stress test with random SMT and core operations.
        Performs random operations and validates system state.
        """
        iterations = int(self.params.get('stress_iterations', default=20))
        self.log.info(
            "Running parallel SMT/core stress test with %d iterations", iterations)

        cores_info = self.get_cores_info()
        total_cores = cores_info['cores_present']

        smt_values = ['off', '2', '4', 'on']

        for i in range(iterations):
            self.log.info("\n" + "=" * 60)
            self.log.info("Stress Iteration %d/%d", i + 1, iterations)
            self.log.info("=" * 60)

            # Random operation choice
            operation = random.choice(['smt', 'cores', 'both'])

            if operation == 'smt':
                smt_val = random.choice(smt_values)
                self.log.info("Random SMT change: %s", smt_val)
                process.system("ppc64_cpu --smt=%s" % smt_val, shell=True)

            elif operation == 'cores':
                num_cores = random.randint(1, total_cores)
                self.log.info("Random core change: %d cores", num_cores)
                process.system("ppc64_cpu --cores-on=%d" %
                               num_cores, shell=True)

            else:  # both
                smt_val = random.choice(smt_values)
                num_cores = random.randint(1, total_cores)
                self.log.info("Random SMT=%s and cores=%d", smt_val, num_cores)

                # Get cores before SMT change
                cores_before = self.get_cores_info()

                process.system("ppc64_cpu --smt=%s" % smt_val, shell=True)

                # Verify cores didn't change due to SMT operation
                cores_after = self.get_cores_info()
                if cores_before['cores_on'] != cores_after['cores_on']:
                    self.fail("SMT change affected core count! Before: %d, After: %d" %
                              (cores_before['cores_on'], cores_after['cores_on']))

                process.system("ppc64_cpu --cores-on=%d" %
                               num_cores, shell=True)

            # Verify system state
            if not self.verify_system_state():
                self.fail("Verification failed at iteration %d" % (i + 1))

            time.sleep(0.3)

        self.log.info("\n✓ Stress test completed successfully!")

    def test_core_range_operations(self):
        """
        Test core operations using range syntax (cores-on=1,2,3,4).
        """
        self.log.info("Testing core range operations")

        cores_info = self.get_cores_info()
        total_cores = cores_info['cores_present']

        # Test with different core counts
        test_counts = [1, 2, min(4, total_cores), min(8, total_cores)]

        for count in test_counts:
            if count > total_cores:
                continue

            self.log.info("\nTesting with %d cores", count)

            # Online specific number of cores
            process.system("ppc64_cpu --cores-on=%d" % count, shell=True)

            # Verify
            cores_output = process.system_output("ppc64_cpu --cores-on",
                                                 shell=True).decode()
            actual_cores = int(cores_output.strip().split("=")[-1])

            if actual_cores != count:
                self.fail("Core count mismatch! Expected: %d, Got: %d" %
                          (count, actual_cores))

            # Verify with --info
            if not self.verify_system_state(expected_cores_on=count):
                self.fail("Verification failed for %d cores" % count)

    def test_all_smt_operations(self):
        """
        Test ALL SMT operations dynamically: off, 2, 3, 4, ..., max_smt, on.
        Covers all possible SMT states without hardcoded values.
        """
        self.log.info("=== Testing ALL SMT Operations (Dynamic) ===")

        for smt_val in self.all_smt_values:
            self.log.info("Setting SMT=%s", smt_val)

            cmd = "%s=%s" % (self.smt_str, smt_val)
            result = process.run(cmd, shell=True, ignore_status=True)

            if result.exit_status != 0:
                self.failures.append("Failed to set SMT=%s" % smt_val)
                continue

            time.sleep(1)

            # Verify the state
            expected_smt = smt_val if smt_val != 'on' else str(
                self.max_smt_value)
            if smt_val == 'off':
                expected_smt = 'off'

            if not self.verify_system_state(expected_smt=expected_smt):
                self.failures.append(
                    "Verification failed for SMT=%s" % smt_val)

            self.log.info("SMT=%s operation completed successfully\n", smt_val)

        if self.failures:
            self.fail("All SMT operations test failed: %s" % self.failures)

    def test_dynamic_core_operations(self):
        """
        Test core online/offline operations with dynamically generated scenarios.
        Tests with specific percentages and edge cases.
        """
        self.log.info("=== Testing Dynamic Core Operations ===")

        # Ensure all cores are online first
        process.system("ppc64_cpu --cores-on=all", shell=True)
        time.sleep(1)

        # Generate test scenarios dynamically
        test_scenarios = []

        # Add specific percentages
        for pct in [0.1, 0.25, 0.5, 0.75, 1.0]:
            cores_count = max(1, int(self.total_cores * pct))
            test_scenarios.append(
                (cores_count, f"{int(pct*100)}% cores online"))

        # Add edge cases
        test_scenarios.insert(0, (1, "Single core online"))
        if self.total_cores > 1:
            test_scenarios.insert(1, (2, "Two cores online"))

        # Remove duplicates
        seen = set()
        unique_scenarios = []
        for cores_count, description in test_scenarios:
            if cores_count not in seen and cores_count <= self.total_cores:
                seen.add(cores_count)
                unique_scenarios.append((cores_count, description))

        for cores_count, description in unique_scenarios:
            self.log.info("Test: %s (cores=%s)", description, cores_count)

            cmd = "ppc64_cpu --cores-on=%s" % cores_count
            result = process.run(cmd, shell=True, ignore_status=True)

            if result.exit_status != 0:
                self.failures.append("Failed to set cores-on=%s" % cores_count)
                continue

            time.sleep(1)

            if not self.verify_system_state(expected_cores_on=cores_count):
                self.failures.append(
                    "Verification failed for cores-on=%s" % cores_count)

            self.log.info("Core operation completed: %s\n", description)

        # Restore all cores
        process.system("ppc64_cpu --cores-on=all", shell=True)
        time.sleep(1)

        if self.failures:
            self.fail("Dynamic core operations test failed: %s" %
                      self.failures)

    def test_smt_core_interaction(self):
        """
        Test interaction between SMT and core operations.
        Validates that SMT changes don't affect core count and vice versa.
        """
        self.log.info("=== Testing SMT-Core Interaction ===")

        # Ensure clean start
        process.system("ppc64_cpu --cores-on=all", shell=True)
        process.system("ppc64_cpu --smt=on", shell=True)
        time.sleep(1)

        num_iterations = min(5, self.stress_iterations // 4)

        for iteration in range(num_iterations):
            self.log.info("Iteration %s/%s", iteration + 1, num_iterations)

            # Set specific core count
            test_core_count = max(1, self.total_cores // 2)
            process.system("ppc64_cpu --cores-on=%s" %
                           test_core_count, shell=True)
            time.sleep(1)

            cores_before = self.get_cores_info()['cores_on']

            # Test all SMT values
            for smt_val in self.all_smt_values:
                self.log.info("  Testing SMT=%s with %s cores",
                              smt_val, test_core_count)
                process.system("ppc64_cpu --smt=%s" %
                               smt_val, shell=True, ignore_status=True)
                time.sleep(0.5)

                # Verify cores didn't change
                cores_after = self.get_cores_info()['cores_on']
                if cores_before != cores_after:
                    self.failures.append(
                        "SMT=%s changed core count from %s to %s" %
                        (smt_val, cores_before, cores_after))

                # Verify system state
                expected_smt = smt_val if smt_val != 'on' else str(
                    self.max_smt_value)
                if smt_val == 'off':
                    expected_smt = 'off'

                self.verify_system_state(expected_smt=expected_smt,
                                         expected_cores_on=test_core_count)

            # Restore
            process.system("ppc64_cpu --cores-on=all", shell=True)
            time.sleep(1)

        if self.failures:
            self.fail("SMT-Core interaction test failed: %s" % self.failures)

    def test_random_stress(self):
        """
        Random stress test with all possible SMT states and core configurations.
        """
        if not self.run_random_stress:
            self.log.info("Skipping random stress test (disabled in config)")
            return

        self.log.info("=== Random Stress Test ===")

        # Ensure clean start
        process.system("ppc64_cpu --cores-on=all", shell=True)
        process.system("ppc64_cpu --smt=on", shell=True)
        time.sleep(self.sleep_after_smt_change)

        for iteration in range(self.random_iterations):
            self.log.info("Random iteration %s/%s",
                          iteration + 1, self.random_iterations)

            operation = random.choice(['smt', 'core_count', 'verify'])

            if operation == 'smt':
                smt_val = random.choice(self.all_smt_values)
                self.log.info("  -> Setting SMT=%s", smt_val)

                cores_before = self.get_cores_info()
                process.system("ppc64_cpu --smt=%s" % smt_val,
                               shell=True, ignore_status=True)
                time.sleep(0.3)

                cores_after = self.get_cores_info()
                if cores_before['cores_on'] != cores_after['cores_on']:
                    self.failures.append(
                        "SMT change affected core count: was %s, now %s" %
                        (cores_before['cores_on'], cores_after['cores_on']))

            elif operation == 'core_count':
                cores_count = random.randint(1, self.total_cores)
                self.log.info("  -> Setting cores-on=%s", cores_count)

                smt_before = self.get_current_smt()
                process.system("ppc64_cpu --cores-on=%s" % cores_count,
                               shell=True, ignore_status=True)
                time.sleep(0.3)

                smt_after = self.get_current_smt()
                if smt_before != smt_after:
                    self.failures.append(
                        "Core operation affected SMT: was %s, now %s" %
                        (smt_before, smt_after))

            elif operation == 'verify':
                self.log.info("  -> Comprehensive verification")
                if not self.verify_system_state():
                    self.failures.append(
                        "Verification failed at iteration %s" % (iteration + 1))

        self.log.info("Random stress test completed")

        if self.failures:
            self.fail("Random stress test failed: %s" % self.failures)

    def get_current_smt(self):
        """
        Get current SMT value.
        """
        try:
            current_smt_output = process.system_output(
                self.smt_str, shell=True).decode()
            current_smt = current_smt_output.strip().split("=")[-1].split()[-1]
            return current_smt
        except Exception as e:
            self.log.error("Failed to get current SMT: %s", str(e))
            return "unknown"

    def test_progressive_core_online_with_smt(self):
        """
        Progressive test: Start with minimal cores, perform all SMT operations,
        then progressively bring cores online and test SMT at each step.
        """
        self.log.info(
            "=== Testing Progressive Core Online with SMT Operations ===")

        if self.total_cores < 3:
            self.log.info("Skipping: Need at least 3 cores for this test")
            return

        # Start with minimal cores
        process.system("ppc64_cpu --cores-on=1", shell=True)
        time.sleep(1)

        # Test all SMT operations with 1 core
        self.log.info("Testing all SMT operations with 1 core online")
        for smt_val in self.all_smt_values:
            self.log.info("  Setting SMT=%s with 1 core", smt_val)
            process.system("ppc64_cpu --smt=%s" %
                           smt_val, shell=True, ignore_status=True)
            time.sleep(0.5)

            expected_smt = smt_val if smt_val != 'on' else str(
                self.max_smt_value)
            if smt_val == 'off':
                expected_smt = 'off'

            if not self.verify_system_state(expected_smt=expected_smt, expected_cores_on=1):
                self.failures.append(
                    "Verification failed for SMT=%s with 1 core" % smt_val)

        # Progressive core online with SMT testing
        self.log.info("Progressively bringing cores online and testing SMT")

        # Generate test core counts
        test_core_counts = []
        if self.total_cores >= 2:
            test_core_counts.append(2)
        if self.total_cores >= 3:
            test_core_counts.append(3)

        # Add percentage-based counts
        half_cores = max(2, self.total_cores // 2)
        three_quarter_cores = max(2, int(self.total_cores * 0.75))

        if half_cores not in test_core_counts:
            test_core_counts.append(half_cores)
        if three_quarter_cores not in test_core_counts:
            test_core_counts.append(three_quarter_cores)
        if self.total_cores not in test_core_counts:
            test_core_counts.append(self.total_cores)

        test_core_counts.sort()

        for core_count in test_core_counts:
            self.log.info("\n--- Testing with %s cores online ---", core_count)

            process.system("ppc64_cpu --cores-on=%s" % core_count, shell=True)
            time.sleep(1)

            cores_info = self.get_cores_info()
            actual_cores = cores_info['cores_on']

            self.log.info("Cores online: %s, Cores offline: %s",
                          actual_cores, cores_info['cores_present'] - actual_cores)

            # Test all SMT operations with current core count
            for smt_val in self.all_smt_values:
                self.log.info("  Testing SMT=%s with %s cores",
                              smt_val, actual_cores)

                process.system("ppc64_cpu --smt=%s" %
                               smt_val, shell=True, ignore_status=True)
                time.sleep(0.5)

                # Verify cores didn't change
                cores_after = self.get_cores_info()['cores_on']
                if cores_after != actual_cores:
                    self.failures.append(
                        "SMT=%s changed core count from %s to %s" %
                        (smt_val, actual_cores, cores_after))

                expected_smt = smt_val if smt_val != 'on' else str(
                    self.max_smt_value)
                if smt_val == 'off':
                    expected_smt = 'off'

                if not self.verify_system_state(expected_smt=expected_smt,
                                                expected_cores_on=actual_cores):
                    self.failures.append(
                        "Verification failed for SMT=%s with %s cores" %
                        (smt_val, actual_cores))

        # Restore all cores
        process.system("ppc64_cpu --cores-on=all", shell=True)
        time.sleep(1)

        if self.failures:
            self.fail("Progressive core online test failed: %s" %
                      self.failures)

    def test_specific_cores_offline_with_smt(self):
        """
        Advanced test: Randomly offline specific cores and perform SMT operations.
        Validates that offline cores remain offline after SMT changes.
        """
        self.log.info(
            "=== Testing Specific Cores Offline with SMT Operations ===")

        if self.total_cores < 5:
            self.log.info("Skipping: Need at least 5 cores for this test")
            return

        # Ensure clean start
        process.system("ppc64_cpu --cores-on=all", shell=True)
        process.system("ppc64_cpu --smt=on", shell=True)
        time.sleep(1)

        num_iterations = min(3, self.stress_iterations // 10)

        for iteration in range(num_iterations):
            self.log.info("\n" + "="*70)
            self.log.info("Iteration %s/%s: Specific Cores Offline with SMT",
                          iteration + 1, num_iterations)
            self.log.info("="*70)

            # Bring all cores online first
            process.system("ppc64_cpu --cores-on=all", shell=True)
            time.sleep(1)

            # Select cores to offline (20-40% of cores, excluding core 0)
            num_cores_to_offline = random.randint(
                max(2, int(self.total_cores * 0.2)),
                min(self.total_cores - 2, int(self.total_cores * 0.4))
            )

            available_cores = list(range(1, self.total_cores))
            cores_to_offline = random.sample(
                available_cores, num_cores_to_offline)

            self.log.info(
                "Randomly selected cores to offline: %s", cores_to_offline)

            # Offline the selected cores
            cores_list = ','.join(str(c) for c in sorted(cores_to_offline))
            cmd = "ppc64_cpu --offline-cores=%s" % cores_list
            result = process.run(cmd, shell=True, ignore_status=True)

            if result.exit_status != 0:
                self.log.warning("Failed to offline cores %s", cores_list)
                continue

            time.sleep(1)

            # Verify cores are offline
            cores_info = self.get_cores_info()
            actual_online_cores = cores_info['cores_on']

            self.log.info("After offlining: %s cores online",
                          actual_online_cores)

            # Perform all SMT operations with these offline cores
            self.log.info("Testing all SMT operations with offline cores")

            for smt_val in self.all_smt_values:
                self.log.info("  Testing SMT=%s", smt_val)

                process.system("ppc64_cpu --smt=%s" %
                               smt_val, shell=True, ignore_status=True)
                time.sleep(0.5)

                # Verify cores didn't change
                cores_after_smt = self.get_cores_info()
                cores_online_after = cores_after_smt['cores_on']

                if cores_online_after != actual_online_cores:
                    self.failures.append(
                        "SMT=%s changed online core count from %s to %s" %
                        (smt_val, actual_online_cores, cores_online_after))

                expected_smt = smt_val if smt_val != 'on' else str(
                    self.max_smt_value)
                if smt_val == 'off':
                    expected_smt = 'off'

                if not self.verify_system_state(expected_smt=expected_smt,
                                                expected_cores_on=cores_online_after):
                    self.failures.append(
                        "Verification failed for SMT=%s with specific cores offline" % smt_val)

        # Final cleanup
        process.system("ppc64_cpu --cores-on=all", shell=True)
        process.system("ppc64_cpu --smt=on", shell=True)
        time.sleep(1)

        if self.failures:
            self.fail("Specific cores offline test failed: %s" % self.failures)

    def tearDown(self):
        """
        Sets back SMT to original value as was before the test.
        """
        if hasattr(self, 'smt_str'):
            process.system_output("%s=%s" % (self.smt_str,
                                             self.curr_smt), shell=True)
            process.system_output("dmesg")
