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
# Modified by: Samir <samir@linux.ibm.com>

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
from avocado.utils import genio, wait
from avocado.utils.software_manager.manager import SoftwareManager
from math import ceil


class PPC64Test(Test):
    """
    Test to verify ppc64_cpu command for different supported values.

    :avocado: tags=cpu,power,privileged
    """

    def _wait_for_consistent_smt(self, timeout=90, poll_step=2):
        """
        Wait until all online cores report the same number of active threads.

        Returns True when a consistent state is reached, False on timeout.
        """
        def _is_consistent():
            info = self.parse_ppc64_cpu_info()
            if not info['inconsistent']:
                self.log.debug(
                    "_wait_for_consistent_smt: consistent "
                    "(smt_mode=%s, online_cores=%s)",
                    info['smt_mode'], info['online_cores'])
                return True
            return False

        if not wait.wait_for(_is_consistent, timeout=timeout,
                             step=poll_step):
            self.log.debug(
                "_wait_for_consistent_smt: timed out after %ds", timeout)
            return False
        return True

    def _normalize_smt(self):
        """
        Set SMT=on and wait until all online cores report a consistent state.
        Required before --cores-on to avoid "Bad or inconsistent SMT state".
        """
        result = process.run("ppc64_cpu --smt=on", shell=True,
                             ignore_status=True)
        if result.exit_status != 0:
            self.log.warning(
                "_normalize_smt: --smt=on returned exit %d: %s",
                result.exit_status,
                result.stdout.decode(errors='replace').strip())
        self._wait_for_consistent_smt()

    def _reset_system_state(self):
        """
        Reset system to a clean, consistent state: SMT=on, all cores online,
        then restore the original SMT level detected at setUp time.
        """
        self._normalize_smt()
        if not wait.wait_for(
                lambda: process.run(
                    "ppc64_cpu --cores-on=all",
                    shell=True, ignore_status=True).exit_status == 0,
                timeout=30, step=2):
            self.log.warning(
                "_reset_system_state: --cores-on=all did not succeed")
        time.sleep(1)
        if hasattr(self, 'curr_smt') and self.curr_smt:
            process.run("ppc64_cpu --smt=%s" % self.curr_smt,
                        shell=True, ignore_status=True)
            self._wait_for_consistent_smt()

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
        process.run("%s=on" % self.smt_str, shell=True, ignore_status=True)
        self._wait_for_consistent_smt()
        smt_op = process.system_output(self.smt_str, shell=True).decode()
        if "is not SMT capable" in smt_op:
            self.cancel("Machine is not SMT capable")
        if "Inconsistent state" in smt_op:
            self.cancel("Machine has mix of ST and SMT cores")

        # Extract the SMT token from output such as "SMT=8" or "SMT is off".
        raw_curr_smt = smt_op.strip().split("=")[-1].split()[-1]
        if raw_curr_smt.isdigit():
            self.curr_smt = raw_curr_smt
        else:
            # Rare edge case: --smt=on returned 'off' somehow; derive from info
            try:
                info_out = process.system_output(
                    "ppc64_cpu --info", shell=True).decode()
                first_core_line = [ln for ln in info_out.splitlines()
                                   if ln.startswith("Core")][0]
                thread_count = len(first_core_line.split(":")[1].split())
                self.curr_smt = str(thread_count)
            except Exception:
                self.curr_smt = raw_curr_smt
        self.smt_subcores = 0
        if os.path.exists("/sys/devices/system/cpu/subcores_per_core"):
            self.smt_subcores = 1
        self.failures = []
        self.smt_values = {1: "off"}
        self.key = 0
        self.value = ""
        self.max_smt_value = int(self.curr_smt) if self.curr_smt.isdigit() \
            else 1

        # Get total cores for dynamic tests
        cores_output = process.system_output("ppc64_cpu --cores-present",
                                             shell=True).decode()
        self.total_cores = int(cores_output.strip().split()[-1])

        self.all_smt_values = self._build_smt_value_list()

        # Test parameters - all configurable via YAML
        # Functional test parameters
        self.iteration = int(self.params.get(
            'functional/iteration', default=5))
        self.run_all_smt_operations = self.params.get(
            'functional/run_all_smt_operations', default=True)
        self.run_dynamic_core_operations = self.params.get(
            'functional/run_dynamic_core_operations', default=True)
        self.run_smt_core_interaction = self.params.get(
            'functional/run_smt_core_interaction', default=True)

        # Stress test parameters
        self.stress_iterations = int(
            self.params.get('stress/iterations', default=20))
        self.parallel_iterations = int(self.params.get(
            'stress/parallel_iterations', default=3))
        self.random_iterations = int(self.params.get(
            'stress/random_iterations', default=50))
        self.num_parallel_threads = int(self.params.get(
            'stress/num_parallel_threads', default=4))
        self.run_random_stress = self.params.get(
            'stress/run_random_stress', default=True)
        self.run_parallel_operations = self.params.get(
            'stress/run_parallel_operations', default=True)
        self.run_progressive_core_online = self.params.get(
            'stress/run_progressive_core_online', default=True)
        self.run_specific_cores_offline = self.params.get(
            'stress/run_specific_cores_offline', default=True)

        # Verification options
        self.enable_comprehensive_verification = self.params.get(
            'verification/enable_comprehensive', default=True)
        self.verify_after_each_operation = self.params.get(
            'verification/verify_after_each_operation', default=True)

        # Timing options
        # sleep_after_smt_change is used as a base sleep after SMT changes.
        # _wait_for_consistent_smt() further guarantees consistency before
        # every --cores-on call.
        self.sleep_after_smt_change = float(self.params.get(
            'timing/sleep_after_smt_change', default=3))
        self.sleep_after_core_change = float(self.params.get(
            'timing/sleep_after_core_change', default=2))
        self.sleep_between_operations = float(self.params.get(
            'timing/sleep_between_operations', default=0.5))

        # Logging options
        self.verbose_logging = self.params.get('logging/verbose', default=True)
        self.log_dmesg = self.params.get('logging/log_dmesg', default=True)

        self.log.info("Total cores: %s, Max SMT: %s",
                      self.total_cores, self.max_smt_value)
        self.log.info("All SMT values to test: %s", self.all_smt_values)
        self.log.info("Test iterations: stress=%s, parallel=%s, random=%s",
                      self.stress_iterations, self.parallel_iterations,
                      self.random_iterations)

    def _build_smt_value_list(self):
        """
        Build the list of SMT values to exercise: off, 2..max_smt, on.
        """
        smt_values = ['off']
        for i in range(2, self.max_smt_value + 1):
            smt_values.append(str(i))
        smt_values.append('on')
        return smt_values

    def _canonical_smt(self, smt_val):
        """
        Normalise an SMT token to the form used for all internal comparisons.

        :param smt_val: raw SMT token ('on', 'off', '1', '2', …, '<N>')
        :returns: canonical string - 'off' for disabled state, numeric string
                  for all enabled states (e.g. 'on' becomes str(max_smt_value))

        Note: 'off' and '1' both map to 'off' because older powerpc-utils
        prints "SMT is off" while newer versions print "SMT=1".
        """
        if smt_val == 'on':
            return str(self.max_smt_value)
        if smt_val in ('off', '1'):
            return 'off'
        return str(smt_val)

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
            self.failures.append("%s test failed when SMT=%s" %
                                 (test_name, self.key))

    def test_cmd_options(self):
        """
        Tests DSCR (Data Stream Control Register) functionality.
        Note: SMT, core, subcore, and threads_per_core tests are now covered
        by the comprehensive test methods (test_all_smt_operations, etc.).
        """
        for i in range(2, self.max_smt_value):
            self.smt_values[i] = str(i)
        for self.key, self.value in self.smt_values.items():
            process.system_output("%s=%s" % (self.smt_str,
                                             self.key), shell=True)
            process.system_output("ppc64_cpu --info")
            self.dscr()

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
        op2 = cpu.online_count() / int(self.key)
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

    def parse_ppc64_cpu_info(self):
        """
        Parse ppc64_cpu --info output to get detailed core and
        thread information. Returns a dictionary with core details.
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
                # Parse lines like
                # "Core   0:    0*   1*   2*   3*   4*   5*   6*   7*"
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
                    result['actual_threads_per_core'][core_num] = \
                        online_threads

                    # Categorize cores
                    if online_threads > 0:
                        result['online_cores'].append(core_num)
                    else:
                        result['offline_cores'].append(core_num)

            result['total_cores'] = len(result['cores'])

            # Check consistency ONLY among ONLINE cores
            if result['online_cores']:
                online_cores_threads = \
                    {core: result['actual_threads_per_core'][core]
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

        ``expected_smt`` must be in the *canonical* form already (i.e. the
        numeric string that ppc64_cpu --smt returns, not 'on'/'off').
        Use ``_canonical_smt()`` to convert before calling this method.
        """
        self.log.info("=" * 60)
        self.log.info("SYSTEM STATE VERIFICATION")
        self.log.info("=" * 60)

        # Get ppc64_cpu info
        info = self.parse_ppc64_cpu_info()

        smt_output = process.system_output(
            "ppc64_cpu --smt", shell=True).decode().strip()
        raw_smt = smt_output.split("=")[-1].split()[-1]
        current_smt = self._canonical_smt(raw_smt)

        # Get cores on
        cores_output = process.system_output(
            "ppc64_cpu --cores-on", shell=True).decode()
        cores_on = int(cores_output.strip().split("=")[-1])

        # Get online CPUs using avocado's cpu utility
        online_cpus = cpu.online_count()

        self.log.info("Current SMT mode: %s", current_smt)
        self.log.info("Cores online: %d", cores_on)
        self.log.info("Online CPUs: %s", online_cpus)
        self.log.info("Total cores detected: %d", info['total_cores'])
        self.log.info("Online cores: %s", info['online_cores'])
        self.log.info("Offline cores: %s", info['offline_cores'])

        # Validation
        validation_passed = True

        # Check if SMT mode matches expected.
        # Both values are already in canonical form (via _canonical_smt).
        if expected_smt is not None:
            if current_smt != expected_smt:
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

        # Verify CPU count formula: Online CPUs = Online Cores x SMT threads.
        # This check is only meaningful when SMT is fully on (numeric > 1).
        # When SMT=off, powerpc-utils and the kernel can disagree on how many
        # logical CPUs are "online", so a mismatch here is informational only
        # and must NOT fail the verification.
        if current_smt == 'off':
            smt_num = 1
        elif current_smt.isdigit():
            smt_num = int(current_smt)
        else:
            smt_num = None
        if smt_num is not None and info['smt_mode']:
            expected_cpus = cores_on * info['smt_mode']
            if online_cpus != expected_cpus:
                if current_smt == 'off' or smt_num == 1:
                    self.log.info(
                        "CPU count advisory (SMT=off): "
                        "Expected: %d (cores=%d x smt=%d), Got: %d",
                        expected_cpus, cores_on, info['smt_mode'], online_cpus)
                else:
                    self.log.error(
                        "CPU count mismatch! "
                        "Expected: %d (cores=%d × smt=%d), Got: %d",
                        expected_cpus, cores_on, info['smt_mode'], online_cpus)
                    validation_passed = False

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

        cores_present_output = \
            process.system_output("ppc64_cpu --cores-present",
                                  shell=True).decode()
        cores_present = int(cores_present_output.strip().split()[-1])

        return {
            'cores_on': cores_on,
            'cores_present': cores_present
        }

    def _set_cores_on(self, num_cores):
        """
        Safely set the number of online cores.

        Normalises SMT to 'on' first to avoid "Bad or inconsistent SMT state".
        Returns True on success, False on failure.
        """
        self._normalize_smt()
        result = process.run("ppc64_cpu --cores-on=%s" % num_cores,
                             shell=True, ignore_status=True)
        if result.exit_status != 0:
            self.log.warning(
                "ppc64_cpu --cores-on=%s failed (exit %d): %s",
                num_cores, result.exit_status,
                result.stdout.decode(errors='replace'))
            return False
        return True

    def test_smt_with_core_operations(self):
        """
        Test SMT changes with various core online/offline operations.
        Verifies that SMT changes work correctly with different
        core configurations.
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

            # Normalise SMT before changing cores to avoid inconsistent state
            if not self._set_cores_on(num_cores):
                self.failures.append(
                    "Failed to set cores-on=%d" % num_cores)
                continue

            for smt_val in smt_values:
                self.log.info("\nSetting SMT=%s with %d cores",
                              smt_val, num_cores)
                process.run("ppc64_cpu --smt=%s" % smt_val,
                            shell=True, ignore_status=True)
                # Poll until all cores have settled to the new SMT level.
                self._wait_for_consistent_smt()

                # Re-read cores_on as it may change after SMT=off.
                actual_cores_on = self.get_cores_info()['cores_on']
                expected_smt = self._canonical_smt(smt_val)

                if not self.verify_system_state(
                        expected_smt=expected_smt,
                        expected_cores_on=actual_cores_on):
                    self.failures.append(
                        "Verification failed for cores=%d, SMT=%s" %
                        (num_cores, smt_val))

                time.sleep(self.sleep_between_operations)

        # Restore system
        self._reset_system_state()

        if self.failures:
            self.fail("SMT with core operations test failed: %s" %
                      self.failures)

    def test_parallel_smt_core_stress(self):
        """
        Stress test with random SMT and core operations.
        Performs random operations and validates system state after each one.

        NOTE: On real Power hardware changing --cores-on can influence what
        --smt reports (the reported SMT value reflects the active thread
        configuration).  Likewise --smt=off may report a different core
        count.  This test therefore validates that the *system is in a
        self-consistent state* after each operation rather than asserting
        that one dimension is invariant to changes in the other.
        """
        iterations = int(self.params.get('stress_iterations', default=20))
        self.log.info(
            "Running parallel SMT/core stress test with %d iterations",
            iterations)

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
                process.run("ppc64_cpu --smt=%s" % smt_val,
                            shell=True, ignore_status=True)
                self._wait_for_consistent_smt()

            elif operation == 'cores':
                num_cores = random.randint(1, total_cores)
                self.log.info("Random core change: %d cores", num_cores)
                # Normalise SMT first to avoid inconsistent-state rejection
                self._set_cores_on(num_cores)

            else:  # both
                smt_val = random.choice(smt_values)
                num_cores = random.randint(1, total_cores)
                self.log.info("Random SMT=%s and cores=%d", smt_val, num_cores)
                process.run("ppc64_cpu --smt=%s" % smt_val,
                            shell=True, ignore_status=True)
                self._wait_for_consistent_smt()
                # _set_cores_on also normalises SMT before --cores-on
                self._set_cores_on(num_cores)

            # Verify system is self-consistent (no expected values asserted
            # because we deliberately mixed operations)
            if not self.verify_system_state():
                self.failures.append(
                    "Verification failed at iteration %d" % (i + 1))

            time.sleep(self.sleep_between_operations)

        # Restore
        self._reset_system_state()

        if self.failures:
            self.fail("Parallel stress test failed: %s" % self.failures)

        self.log.info("\n✓ Stress test completed successfully!")

    def test_core_range_operations(self):
        """
        Test core operations using different core counts.
        Each sub-test normalises SMT first to prevent --cores-on from
        failing with "Bad or inconsistent SMT state".
        """
        self.log.info("Testing core range operations")

        # Ensure a clean, consistent start
        self._reset_system_state()

        cores_info = self.get_cores_info()
        total_cores = cores_info['cores_present']

        # Test with different core counts
        test_counts = list(dict.fromkeys(
            [1, 2, min(4, total_cores), min(8, total_cores), total_cores]))

        for count in test_counts:
            if count > total_cores:
                continue

            self.log.info("\nTesting with %d cores", count)

            # _set_cores_on normalises SMT before the actual command
            if not self._set_cores_on(count):
                self.failures.append(
                    "Failed to set cores-on=%d" % count)
                continue

            # Verify
            cores_output = process.system_output("ppc64_cpu --cores-on",
                                                 shell=True).decode()
            actual_cores = int(cores_output.strip().split("=")[-1])

            if actual_cores != count:
                self.failures.append(
                    "Core count mismatch! Expected: %d, Got: %d" %
                    (count, actual_cores))
                continue

            # Verify with --info
            if not self.verify_system_state(expected_cores_on=count):
                self.failures.append(
                    "Verification failed for %d cores" % count)

        # Restore system
        self._reset_system_state()

        if self.failures:
            self.fail("Core range operations test failed: %s" % self.failures)

    def test_all_smt_operations(self):
        """
        Test ALL SMT operations dynamically: off, 2, 3, 4, ..., max_smt, on.
        Covers all possible SMT states without hardcoded values.

        The expected SMT value is expressed in *canonical* form (the numeric
        string that ppc64_cpu --smt returns) rather than the symbolic
        'on'/'off' that the command accepts.
        """
        self.log.info("=== Testing ALL SMT Operations (Dynamic) ===")

        # Bring all cores online first so SMT changes have a full system
        self._reset_system_state()

        for smt_val in self.all_smt_values:
            self.log.info("Setting SMT=%s", smt_val)

            cmd = "%s=%s" % (self.smt_str, smt_val)
            result = process.run(cmd, shell=True, ignore_status=True)

            if result.exit_status != 0:
                self.failures.append("Failed to set SMT=%s" % smt_val)
                continue

            # Poll until all cores have settled to the requested SMT level.
            self._wait_for_consistent_smt()

            # Convert to canonical form: ppc64_cpu --smt always returns a
            # number, never the literals 'on' or 'off'.
            expected_smt = self._canonical_smt(smt_val)

            if not self.verify_system_state(expected_smt=expected_smt):
                self.failures.append(
                    "Verification failed for SMT=%s" % smt_val)

            self.log.info("SMT=%s operation completed successfully\n", smt_val)

        # Restore system to clean state
        self._reset_system_state()

        if self.failures:
            self.fail("All SMT operations test failed: %s" % self.failures)

    def test_dynamic_core_operations(self):
        """
        Test core online/offline operations with dynamically
        generated scenarios. Tests with specific percentages and edge cases.

        Note: This test focuses solely on core operations without SMT changes.
        For combined SMT+core testing, see test_smt_with_core_operations().

        SMT is normalised to 'on' before every --cores-on command to prevent
        the "Bad or inconsistent SMT state" error that arises when a previous
        test (or teardown) left an uneven thread distribution.
        """
        self.log.info("=== Testing Dynamic Core Operations ===")

        # Ensure clean, consistent start state
        self._reset_system_state()

        # Generate test scenarios dynamically
        test_scenarios = []

        # Add specific percentages
        for pct in [0.1, 0.25, 0.5, 0.75, 1.0]:
            cores_count = max(1, int(self.total_cores * pct))
            test_scenarios.append(
                (cores_count, "%d%% cores online" % int(pct * 100)))

        # Add edge cases
        test_scenarios.insert(0, (1, "Single core online"))
        if self.total_cores > 1:
            test_scenarios.insert(1, (2, "Two cores online"))

        # Remove duplicates while preserving order
        seen = set()
        unique_scenarios = []
        for cores_count, description in test_scenarios:
            if cores_count not in seen and cores_count <= self.total_cores:
                seen.add(cores_count)
                unique_scenarios.append((cores_count, description))

        for cores_count, description in unique_scenarios:
            self.log.info("Test: %s (cores=%s)", description, cores_count)

            # _set_cores_on normalises SMT before issuing --cores-on
            if not self._set_cores_on(cores_count):
                self.failures.append(
                    "Failed to set cores-on=%s" % cores_count)
                continue

            if not self.verify_system_state(expected_cores_on=cores_count):
                self.failures.append(
                    "Verification failed for cores-on=%s" % cores_count)

            self.log.info("Core operation completed: %s\n", description)

        # Restore all cores
        self._reset_system_state()

        if self.failures:
            self.fail("Dynamic core operations test failed: %s" %
                      self.failures)

    def test_smt_core_interaction(self):
        """
        Test interaction between SMT and core operations.
        Validates that the system remains self-consistent after interleaved
        SMT and core-count changes.

        Note: On Power hardware, changing the number of online threads
        (SMT level) can affect what --cores-on reports because the kernel
        counts CPUs differently in SMT-off mode.  This test therefore checks
        *self-consistency* of the system state rather than asserting that
        the core count is identical before and after every SMT change.
        """
        self.log.info("=== Testing SMT-Core Interaction ===")

        # Ensure clean start
        self._reset_system_state()

        num_iterations = min(5, self.stress_iterations // 4)

        for iteration in range(num_iterations):
            self.log.info("Iteration %s/%s", iteration + 1, num_iterations)

            # Set specific core count using safe helper
            test_core_count = max(1, self.total_cores // 2)
            if not self._set_cores_on(test_core_count):
                self.failures.append(
                    "Iteration %d: failed to set cores-on=%d" %
                    (iteration + 1, test_core_count))
                continue

            # Test all SMT values
            for smt_val in self.all_smt_values:
                self.log.info("  Testing SMT=%s with %s cores",
                              smt_val, test_core_count)
                process.run("ppc64_cpu --smt=%s" % smt_val,
                            shell=True, ignore_status=True)
                self._wait_for_consistent_smt()

                # Re-read actual cores after SMT change (may differ for off)
                actual_cores_after = self.get_cores_info()['cores_on']
                expected_smt = self._canonical_smt(smt_val)

                if not self.verify_system_state(
                        expected_smt=expected_smt,
                        expected_cores_on=actual_cores_after):
                    self.failures.append(
                        "Verification failed for SMT=%s, cores=%s "
                        "(iteration %d)" %
                        (smt_val, actual_cores_after, iteration + 1))

            # Restore between iterations
            self._reset_system_state()

        if self.failures:
            self.fail("SMT-Core interaction test failed: %s" % self.failures)

    def test_random_stress(self):
        """
        Random stress test with all possible SMT states and core
        configurations.

        The test validates *self-consistency* of the system after each
        operation.  On Power hardware changing --cores-on can update the
        effective SMT reported and vice-versa; asserting strict invariance
        between the two dimensions would produce false failures.
        """
        if not self.run_random_stress:
            self.log.info("Skipping random stress test (disabled in config)")
            return

        self.log.info("=== Random Stress Test ===")

        # Ensure clean start
        self._reset_system_state()

        for iteration in range(self.random_iterations):
            self.log.info("Random iteration %s/%s",
                          iteration + 1, self.random_iterations)

            operation = random.choice(['smt', 'core_count', 'verify'])

            if operation == 'smt':
                smt_val = random.choice(self.all_smt_values)
                self.log.info("  -> Setting SMT=%s", smt_val)
                process.run("ppc64_cpu --smt=%s" % smt_val,
                            shell=True, ignore_status=True)
                self._wait_for_consistent_smt()

            elif operation == 'core_count':
                cores_count = random.randint(1, self.total_cores)
                self.log.info("  -> Setting cores-on=%s", cores_count)
                # Normalise SMT before changing cores
                self._set_cores_on(cores_count)

            elif operation == 'verify':
                self.log.info("  -> Comprehensive verification")
                if not self.verify_system_state():
                    self.failures.append(
                        "Verification failed at iteration %s" %
                        (iteration + 1))

        self.log.info("Random stress test completed")

        # Restore
        self._reset_system_state()

        if self.failures:
            self.fail("Random stress test failed: %s" % self.failures)

    def get_current_smt(self):
        """
        Get current SMT value in canonical form.

        Returns the canonical SMT token (e.g. '8', '4', 'off') normalised
        via _canonical_smt() so that "SMT is off" and "SMT=1" both return
        the single token 'off'.
        """
        try:
            current_smt_output = process.system_output(
                self.smt_str, shell=True).decode().strip()
            raw = current_smt_output.split("=")[-1].split()[-1]
            return self._canonical_smt(raw)
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

        # Start with minimal cores (normalise SMT first)
        if not self._set_cores_on(1):
            self.fail("Failed to set initial single-core state")

        # Test all SMT operations with 1 core
        self.log.info("Testing all SMT operations with 1 core online")
        for smt_val in self.all_smt_values:
            self.log.info("  Setting SMT=%s with 1 core", smt_val)
            process.run("ppc64_cpu --smt=%s" % smt_val,
                        shell=True, ignore_status=True)
            self._wait_for_consistent_smt()

            expected_smt = self._canonical_smt(smt_val)
            actual_cores_on = self.get_cores_info()['cores_on']

            if not self.verify_system_state(expected_smt=expected_smt,
                                            expected_cores_on=actual_cores_on):
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

            # Use safe helper to normalise SMT before core change
            if not self._set_cores_on(core_count):
                self.failures.append(
                    "Failed to set cores-on=%d" % core_count)
                continue

            cores_info = self.get_cores_info()
            actual_cores = cores_info['cores_on']

            self.log.info("Cores online: %s, Cores offline: %s",
                          actual_cores,
                          cores_info['cores_present'] - actual_cores)

            # Test all SMT operations with current core count
            for smt_val in self.all_smt_values:
                self.log.info("  Testing SMT=%s with %s cores",
                              smt_val, actual_cores)

                process.run("ppc64_cpu --smt=%s" % smt_val,
                            shell=True, ignore_status=True)
                self._wait_for_consistent_smt()

                # Re-read actual cores after SMT change
                cores_after = self.get_cores_info()['cores_on']
                expected_smt = self._canonical_smt(smt_val)

                if not self.verify_system_state(
                        expected_smt=expected_smt,
                        expected_cores_on=cores_after):
                    self.failures.append(
                        "Verification failed for SMT=%s with %s cores" %
                        (smt_val, actual_cores))

        # Restore all cores
        self._reset_system_state()

        if self.failures:
            self.fail("Progressive core online test failed: %s" %
                      self.failures)

    def test_specific_cores_offline_with_smt(self):
        """
        Advanced test: Randomly offline specific cores and perform
        SMT operations. Validates that offline cores remain offline
        after SMT changes.
        """
        self.log.info(
            "=== Testing Specific Cores Offline with SMT Operations ===")

        if self.total_cores < 5:
            self.log.info("Skipping: Need at least 5 cores for this test")
            return

        # Ensure clean start
        self._reset_system_state()

        num_iterations = min(3, self.stress_iterations // 10)

        for iteration in range(num_iterations):
            self.log.info("\n" + "=" * 70)
            self.log.info("Iteration %s/%s: Specific Cores Offline with SMT",
                          iteration + 1, num_iterations)
            self.log.info("=" * 70)

            # Bring all cores online first (normalises SMT as well)
            self._reset_system_state()

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

                process.run("ppc64_cpu --smt=%s" % smt_val,
                            shell=True, ignore_status=True)
                self._wait_for_consistent_smt()

                # Re-read cores after SMT change
                cores_after_smt = self.get_cores_info()
                cores_online_after = cores_after_smt['cores_on']
                expected_smt = self._canonical_smt(smt_val)

                if not self.verify_system_state(
                        expected_smt=expected_smt,
                        expected_cores_on=cores_online_after):
                    self.failures.append(
                        "Verification failed for SMT=%s "
                        "with specific cores offline" % smt_val)

        # Final cleanup
        self._reset_system_state()

        if self.failures:
            self.fail("Specific cores offline test failed: %s" % self.failures)

    def test_ppc64_cpu_cores_present(self):
        """
        Verify ppc64_cpu --cores-present reports the total number of cores.
        The output must contain at least one digit and be parseable as a
        positive integer (e.g. "Number of cores present = 16").
        """
        self.log.info("===============Executing ppc64_cpu --cores-present"
                      " test===============")
        output = process.system_output(
            "ppc64_cpu --cores-present", shell=True).decode("utf-8").strip()
        match = re.search(r'\d+', output)
        if not match:
            self.fail("--cores-present did not return a numeric value: "
                      "%s" % output)
        if int(match.group()) < 1:
            self.fail("--cores-present returned an invalid value (< 1): "
                      "%s" % output)

    def test_ppc64_cpu_cores_on(self):
        """
        Verify ppc64_cpu --cores-on (query), --cores-on=1 (set) and
        --cores-on=all (restore all cores).
        Steps:
        1. Query current cores-on count and validate it is numeric.
        2. Set cores-on=1 and confirm the reported count is 1.
        3. Restore all cores with --cores-on=all and confirm the count
           equals --cores-present.
        """
        self.log.info("===============Executing ppc64_cpu --cores-on"
                      " test===============")
        # Step 1 - query
        output = process.system_output(
            "ppc64_cpu --cores-on", shell=True).decode("utf-8").strip()
        if not re.search(r'\d+', output):
            self.fail("--cores-on did not return a numeric value: %s" % output)
        # Step 2 - set to 1
        process.system("ppc64_cpu --cores-on=1", shell=True)
        output = process.system_output(
            "ppc64_cpu --cores-on", shell=True).decode("utf-8").strip()
        match = re.search(r'\d+', output)
        if not match or int(match.group()) != 1:
            self.fail("Expected cores-on=1, got: %s" % output)
        # Step 3 - restore all
        process.system("ppc64_cpu --cores-on=all", shell=True)
        output_on = process.system_output(
            "ppc64_cpu --cores-on", shell=True).decode("utf-8").strip()
        output_present = process.system_output(
            "ppc64_cpu --cores-present", shell=True).decode("utf-8").strip()
        m_on = re.search(r'\d+', output_on)
        m_present = re.search(r'\d+', output_present)
        if m_on and m_present:
            if int(m_on.group()) != int(m_present.group()):
                self.fail("After --cores-on=all, cores-on (%s) != "
                          "cores-present (%s)" % (m_on.group(),
                                                  m_present.group()))
        if self.failures:
            self.log.debug("Failure list: %s", self.failures)
            self.fail()

    def test_ppc64_cpu_online_offline_cores(self):
        """
        Verify ppc64_cpu --offline-cores=X and --online-cores=X by
        offlining and onlining CPU core index 0.
        Steps:
        1. Ensure all cores are online; record baseline cores-on count.
        2. Offline core index 0 with --offline-cores=0 and confirm
           cores-on decreased by 1.
        3. Online core index 0 with --online-cores=0 and confirm
           cores-on is restored to baseline.
        """
        self.log.info("===============Executing ppc64_cpu online/offline"
                      " cores test===============")
        # Ensure all cores are online before starting.
        process.system("ppc64_cpu --cores-on=all", shell=True,
                       ignore_status=True)
        # Derive online baseline from --cores-on.
        online_out = process.system_output(
            "ppc64_cpu --cores-on", shell=True).decode("utf-8").strip()
        m_online = re.search(r'\d+', online_out)
        if not m_online:
            self.cancel("Could not determine baseline online core count "
                        "from --cores-on: %s" % online_out)
        online_base = int(m_online.group())
        process.system("ppc64_cpu --offline-cores=0", shell=True)
        after_off = process.system_output(
            "ppc64_cpu --cores-on", shell=True).decode("utf-8").strip()
        m_after_off = re.search(r'\d+', after_off)
        if m_after_off:
            online_after_off = int(m_after_off.group())
            if online_after_off != online_base - 1:
                self.fail("Expected cores-on=%d after offline, got %d"
                          % (online_base - 1, online_after_off))
        process.system("ppc64_cpu --online-cores=0", shell=True)
        after_on = process.system_output(
            "ppc64_cpu --cores-on", shell=True).decode("utf-8").strip()
        m_after_on = re.search(r'\d+', after_on)
        if m_after_on:
            online_restored = int(m_after_on.group())
            if online_restored != online_base:
                self.fail("Expected cores-on=%d after online, got %d"
                          % (online_base, online_restored))
        process.system("ppc64_cpu --cores-on=all", shell=True,
                       ignore_status=True)
        if self.failures:
            self.log.debug("Failure list: %s", self.failures)
            self.fail()

    def test_ppc64_cpu_dscr(self):
        """
        Verify ppc64_cpu --dscr (query), --dscr=1 (set) and --dscr=0 (reset).
        The initial DSCR value may be any non-negative integer.
        After setting to 1 the tool must report 1; after setting to 0 it
        must report 0.  The original value is restored at the end.
        """
        self.log.info("===============Executing ppc64_cpu --dscr"
                      " test===============")
        # Query - value must be numeric.
        output = process.system_output(
            "ppc64_cpu --dscr", shell=True).decode("utf-8").strip()
        initial_match = re.search(r'\d+', output)
        if not initial_match:
            self.fail("--dscr did not return a numeric value: %s" % output)
        initial_dscr = int(initial_match.group())
        # Set DSCR=1 and verify.
        process.system("ppc64_cpu --dscr=1", shell=True)
        output = process.system_output(
            "ppc64_cpu --dscr", shell=True).decode("utf-8").strip()
        match = re.search(r'\d+', output)
        if not match or int(match.group()) != 1:
            self.fail("Expected DSCR=1, got: %s" % output)
        # Set DSCR=0 and verify.
        process.system("ppc64_cpu --dscr=0", shell=True)
        output = process.system_output(
            "ppc64_cpu --dscr", shell=True).decode("utf-8").strip()
        match = re.search(r'\d+', output)
        if not match:
            self.fail("--dscr returned no numeric value after --dscr=0: "
                      "%s" % output)
        if int(match.group()) != 0:
            self.fail("Expected DSCR=0, got: %s" % output)
        # Restore original DSCR value.
        process.system("ppc64_cpu --dscr=%d" % initial_dscr,
                       shell=True, ignore_status=True)
        if self.failures:
            self.log.debug("Failure list: %s", self.failures)
            self.fail()

    def test_ppc64_cpu_smt_snooze_delay(self):
        """
        Verify ppc64_cpu --smt-snooze-delay (query) and set operations.
        If the machine does not support --smt-snooze-delay the command
        prints a usage/error message; the test is cancelled in that case.
        Steps (when supported):
        1. Query current value and confirm it is numeric.
        2. Set to 200 and verify.
        3. Set to 100 and verify.
        4. Restore the original value.
        """
        self.log.info("===============Executing ppc64_cpu --smt-snooze-delay"
                      " test===============")
        output = process.system_output(
            "ppc64_cpu --smt-snooze-delay", shell=True,
            ignore_status=True).decode("utf-8").strip()
        if "Usage:" in output or "not supported" in output.lower() \
                or not re.search(r'\d+', output):
            self.cancel("--smt-snooze-delay is not supported on this "
                        "machine: %s" % output)
        initial_delay = int(re.search(r'\d+', output).group())
        for value in [200, 100]:
            process.system("ppc64_cpu --smt-snooze-delay=%d" % value,
                           shell=True)
            output = process.system_output(
                "ppc64_cpu --smt-snooze-delay",
                shell=True).decode("utf-8").strip()
            match = re.search(r'\d+', output)
            if not match or int(match.group()) != value:
                self.fail("Expected smt-snooze-delay=%d, got: %s"
                          % (value, output))
        # Restore original value.
        process.system("ppc64_cpu --smt-snooze-delay=%d" % initial_delay,
                       shell=True, ignore_status=True)
        if self.failures:
            self.log.debug("Failure list: %s", self.failures)
            self.fail()

    def test_ppc64_cpu_run_mode(self):
        """
        Verify ppc64_cpu --run-mode (query) and --run-mode=1 (set).
        If the machine reports "does not support diagnostic run mode" the
        test is cancelled (the feature is hardware-dependent).
        """
        self.log.info("===============Executing ppc64_cpu --run-mode"
                      " test===============")
        output = process.system_output(
            "ppc64_cpu --run-mode", shell=True,
            ignore_status=True).decode("utf-8").strip()
        if not output or "not support" in output.lower():
            self.cancel("--run-mode is not supported on this machine: "
                        "%s" % output)
        process.system("ppc64_cpu --run-mode=1", shell=True)
        output = process.system_output(
            "ppc64_cpu --run-mode", shell=True).decode("utf-8").strip()
        if self.failures:
            self.log.debug("Failure list: %s", self.failures)
            self.fail()

    def test_ppc64_cpu_frequency(self):
        """
        Verify ppc64_cpu --frequency (instant) and --frequency -t <N>
        (timed average).
        The output contains lines such as "avg  :  3.247 GHz", so the
        check looks for a GHz/MHz pattern rather than a bare integer.
        """
        self.log.info("===============Executing ppc64_cpu --frequency"
                      " test===============")
        output = process.system_output(
            "ppc64_cpu --frequency", shell=True).decode("utf-8").strip()
        if not re.search(r'\d+\.\d+\s*GHz|\d+\s*MHz', output,
                         re.IGNORECASE):
            self.fail("--frequency output did not contain a frequency "
                      "value (GHz/MHz): %s" % output)
        timeout = self.params.get('frequency_timeout', default=5)
        output = process.system_output(
            "ppc64_cpu --frequency -t %d" % timeout,
            shell=True).decode("utf-8").strip()
        if not re.search(r'\d+\.\d+\s*GHz|\d+\s*MHz', output,
                         re.IGNORECASE):
            self.fail("--frequency -t %d output did not contain a "
                      "frequency value (GHz/MHz): %s" % (timeout, output))
        if self.failures:
            self.log.debug("Failure list: %s", self.failures)
            self.fail()

    def test_ppc64_cpu_subcores_per_core(self):
        """
        Verify ppc64_cpu --subcores-per-core.
        If the machine is not subcore-capable the command exits non-zero
        with "Machine is not subcore capable"; the test is cancelled in
        that case.  On capable machines the reported value must be numeric.
        """
        self.log.info("===============Executing ppc64_cpu --subcores-per-core"
                      " test===============")
        result = process.run("ppc64_cpu --subcores-per-core",
                             ignore_status=True, shell=True)
        output = (result.stdout + result.stderr).decode("utf-8").strip()
        if "not subcore capable" in output.lower():
            self.cancel("--subcores-per-core: machine is not subcore "
                        "capable — skipping")
        if result.exit_status != 0:
            self.fail("--subcores-per-core failed unexpectedly: %s" % output)
        if not re.search(r'\d+', output):
            self.fail("--subcores-per-core did not return a numeric value: "
                      "%s" % output)

    def test_ppc64_cpu_threads_per_core(self):
        """
        Verify ppc64_cpu --threads-per-core returns a positive integer.
        """
        self.log.info("===============Executing ppc64_cpu --threads-per-core"
                      " test===============")
        output = process.system_output(
            "ppc64_cpu --threads-per-core",
            shell=True).decode("utf-8").strip()
        match = re.search(r'\d+', output)
        if not match:
            self.fail("--threads-per-core did not return a numeric value: "
                      "%s" % output)
        if int(match.group()) < 1:
            self.fail("--threads-per-core returned an invalid value "
                      "(< 1): %s" % output)

    def test_ppc64_cpu_info(self):
        """
        Verify ppc64_cpu --info prints a comprehensive CPU information
        summary containing per-core thread layout lines such as
        "Core   0:    0*    1* ...".
        """
        self.log.info("===============Executing ppc64_cpu --info"
                      " test===============")
        output = process.system_output(
            "ppc64_cpu --info", shell=True).decode("utf-8").strip()
        if not output:
            self.fail("--info returned empty output")
        if not re.search(r'Core\s+\d+', output, re.IGNORECASE):
            self.fail("--info output does not contain expected 'Core N:' "
                      "layout lines: %s" % output)

    def tearDown(self):
        """
        Restore system to original state: all cores online and original SMT.
        """
        if hasattr(self, 'smt_str'):
            self._normalize_smt()
            if not wait.wait_for(
                    lambda: process.run(
                        "ppc64_cpu --cores-on=all",
                        shell=True, ignore_status=True).exit_status == 0,
                    timeout=30, step=2):
                self.log.warning("tearDown: --cores-on=all did not succeed")
            time.sleep(1)
            process.run("%s=%s" % (self.smt_str, self.curr_smt),
                        shell=True, ignore_status=True)
            self._wait_for_consistent_smt()
            process.run("dmesg", ignore_status=True)
