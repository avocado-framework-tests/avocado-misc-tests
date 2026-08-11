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
# Author: Pavithra Prakash <pavrampu@linux.ibm.com>

import os
import shutil
import multiprocessing
from avocado import Test
from avocado.utils import process, genio, distro, dmesg
from avocado.utils.software_manager.manager import SoftwareManager


class THPStressTest(Test):
    """
    Test Transparent Huge Pages (THP) by running
    memory-intensive workloads including kernel compilation, package management,
    and memory statistics monitoring. This stress test validates THP functionality
    under real-world conditions.

    :avocado: tags=memory,privileged,stress,thp
    """

    def setUp(self):
        """
        Setup test environment and install dependencies
        """
        self.original_thp_setting = None
        self.kernel_dir = None
        self.thp_enabled_file = '/sys/kernel/mm/transparent_hugepage/enabled'
        self.smm = SoftwareManager()
        self.detected_distro = distro.detect()
        self.log.info(f"Detected distribution: {self.detected_distro.name}")
        self.log.info(f"Distribution version: {self.detected_distro.version}")
        if self.detected_distro.name not in ['rhel', 'SuSE', 'sles']:
            self.cancel(f"This test only supports RHEL and SLES distributions. "
                        f"Current distribution: {self.detected_distro.name}")
        self.iterations = self.params.get('iterations', default=50)
        self.kernel_repo = self.params.get('kernel_repo',
                                           default='https://github.com/torvalds/linux.git')
        self.kernel_branch = self.params.get('kernel_branch', default='master')
        cpu_count = multiprocessing.cpu_count()
        self.make_jobs = self.params.get('make_jobs', default=cpu_count)
        self.log.info(f"Using {self.make_jobs} parallel make jobs (CPU count: {cpu_count})")
        self.kernel_dir = os.path.join(self.workdir, 'linux')
        if not os.path.exists(self.thp_enabled_file):
            self.cancel("Transparent Huge Pages not available on this system")
        self.log.info("Getting kernel build dependencies for distribution...")
        self.kernel_deps = self._get_kernel_dependencies()
        self.log.info(f"Kernel dependencies: {self.kernel_deps}")
        self.log.info("Installing kernel build dependencies...")
        for package in self.kernel_deps:
            if not self.smm.check_installed(package):
                if not self.smm.install(package):
                    self.log.warning(f"Failed to install {package}, continuing...")
        tools = ['git', 'bc', 'wget', 'curl']
        self.log.info(f"Checking required tools: {tools}")
        for tool in tools:
            if not self.smm.check_installed(tool):
                self.log.info(f"Installing {tool}...")
                if not self.smm.install(tool):
                    self.cancel(f'{tool} is required for the test but failed to install')
            else:
                self.log.info(f"{tool} is already installed")

    def _get_kernel_dependencies(self):
        """
        Get kernel build dependencies based on distribution
        """
        deps = []
        if self.detected_distro.name in ['rhel']:
            self.log.info("Detected RHEL distribution")
            deps = [
                'rpm-build', 'redhat-rpm-config', 'asciidoc', 'hmaccalc',
                'perl-ExtUtils-Embed', 'pesign', 'xmlto', 'audit-libs-devel',
                'binutils-devel', 'elfutils-devel', 'elfutils-libelf-devel',
                'ncurses-devel', 'newt-devel', 'numactl-devel',
                'pciutils-devel', 'python3-devel', 'zlib-devel',
                'bison', 'flex', 'openssl-devel', 'dwarves', 'gcc', 'make', 'bc'
            ]
        elif self.detected_distro.name in ['SuSE', 'sles']:
            self.log.info("Detected SLES distribution")
            deps = [
                'rpm-build', 'asciidoc', 'xmlto', 'audit-devel',
                'binutils-devel', 'elfutils', 'libelf-devel',
                'ncurses-devel', 'libnuma-devel', 'pciutils-devel',
                'python3-devel', 'zlib-devel', 'bison', 'flex',
                'libopenssl-devel', 'dwarves', 'gcc', 'make', 'bc'
            ]
        else:
            self.cancel(f"Unsupported distribution: {self.detected_distro.name}")
        return deps

    def _enable_thp(self):
        """
        Enable Transparent Huge Pages for all circumstances
        """
        self.log.info("Phase 1: Enabling Transparent Huge Pages")
        try:
            self.original_thp_setting = genio.read_file(self.thp_enabled_file).strip()
            self.log.info(f"Original THP setting: {self.original_thp_setting}")
        except Exception as e:
            self.log.warning(f"Could not read original THP setting: {e}")
        try:
            genio.write_file(self.thp_enabled_file, 'always')
            self.log.info("THP enabled with 'always' setting")
        except Exception as e:
            self.fail(f"Failed to enable THP: {e}")
        current_setting = genio.read_file(self.thp_enabled_file).strip()
        self.log.info(f"Current THP setting: {current_setting}")
        if '[always]' not in current_setting:
            self.fail("THP was not enabled successfully")
        self.log.info("THP verification successful")

    def _get_memory_stats(self):
        """
        Get current THP statistics from /proc/vmstat
        """
        stats = {}
        thp_stats_dir = '/sys/kernel/mm/transparent_hugepage'
        if os.path.exists(thp_stats_dir):
            stats['thp_enabled'] = genio.read_file(
                os.path.join(thp_stats_dir, 'enabled')).strip()
        try:
            result = process.run("cat /proc/vmstat | grep -i thp",
                                 shell=True, ignore_status=True)
            if result.exit_status == 0:
                for line in result.stdout_text.splitlines():
                    parts = line.split()
                    if len(parts) >= 2:
                        stats[parts[0]] = parts[1]
        except Exception as e:
            self.log.warning(f"Could not read THP stats from /proc/vmstat: {e}")
        return stats

    def _verify_thp_counters_increased(self, stats_before, stats_after, iteration):
        """
        Verify that THP counters increased during the iteration
        Only warns if counters don't increase, doesn't fail the test
        """
        counters_to_check = ['thp_migration_success', 'thp_fault_alloc']
        for counter in counters_to_check:
            before_val = int(stats_before.get(counter, 0))
            after_val = int(stats_after.get(counter, 0))
            if after_val > before_val:
                increase = after_val - before_val
                self.log.info(f"{counter}: {before_val} -> {after_val} (increased by {increase})")
            elif after_val == before_val:
                self.log.warning(f"{counter}: {before_val} -> {after_val} (no change in iteration {iteration + 1})")
            else:
                self.log.warning(f"{counter}: {before_val} -> {after_val} (decreased in iteration {iteration + 1})")

    def _setup_kernel_source(self):
        """
        Download and setup kernel source
        """
        self.log.info("Phase 2: Setting up kernel source")
        if self.kernel_dir and os.path.exists(self.kernel_dir):
            self.log.info(f"Kernel directory exists, removing: {self.kernel_dir}")
            shutil.rmtree(self.kernel_dir)
        self.log.info(f"Cloning kernel from {self.kernel_repo}")
        clone_cmd = f"git clone --depth 1 --branch {self.kernel_branch} {self.kernel_repo} {self.kernel_dir}"
        result = process.run(clone_cmd, shell=True, ignore_status=True, timeout=3600)
        if result.exit_status != 0:
            self.fail(f"Failed to clone kernel repository: {result.stderr}")
        if not os.path.exists(self.kernel_dir):
            self.fail("Kernel directory was not created")
        self.log.info("Kernel source downloaded successfully")
        os.chdir(self.kernel_dir)
        self.log.info("Running make oldconfig")
        oldconfig_cmd = "yes '' | make oldconfig"
        result = process.run(oldconfig_cmd, shell=True, ignore_status=True, timeout=600)
        if result.exit_status != 0:
            self.log.warning(f"make oldconfig returned non-zero: {result.exit_status}")
        self.log.info("Kernel configuration completed")

    def _run_stress_iteration(self, iteration):
        """
        Run a single stress test iteration with kernel compilation and package updates
        """
        self.log.info(f"=== Iteration {iteration + 1}/{self.iterations} ===")
        stats_before = self._get_memory_stats()
        self.log.info(f"Memory stats before iteration: {stats_before}")
        if not self.kernel_dir:
            self.fail("Kernel directory not initialized")
        os.chdir(self.kernel_dir)
        self.log.info("Running make clean")
        result = process.run("make clean", shell=True, ignore_status=True, timeout=600)
        if result.exit_status != 0:
            self.log.warning(f"make clean failed: {result.stderr}")
        self.log.info(f"Running make -j{self.make_jobs}")
        make_cmd = f"make -j{self.make_jobs}"
        result = process.run(make_cmd, shell=True, ignore_status=True, timeout=7200)
        if result.exit_status != 0:
            self.log.warning(f"Kernel compilation failed at iteration {iteration + 1}: {result.stderr}")
            self.log.warning("Continuing with package manager operations despite compilation failure")
        else:
            self.log.info("Kernel compilation successful")
        self.log.info("Cleaning package manager cache")
        if self.detected_distro.name in ['rhel']:
            clean_cmd = "yum clean all"
        elif self.detected_distro.name in ['SuSE', 'sles']:
            clean_cmd = "zypper clean --all"
        else:
            clean_cmd = "yum clean all"
        result = process.run(clean_cmd, shell=True, ignore_status=True, sudo=True, timeout=300)
        if result.exit_status != 0:
            self.log.warning(f"Clean command failed: {result.stderr}")
        self.log.info("Checking for package updates")
        if self.detected_distro.name in ['rhel']:
            update_cmd = "yum check-update"
        elif self.detected_distro.name in ['SuSE', 'sles']:
            update_cmd = "zypper refresh"
        else:
            update_cmd = "yum check-update"
        result = process.run(update_cmd, shell=True, ignore_status=True, sudo=True, timeout=600)
        # Note: yum check-update returns 100 if updates are available, 0 if none
        # zypper refresh returns 0 on success
        if self.detected_distro.name in ['rhel']:
            if result.exit_status not in [0, 100]:
                self.log.warning(f"Update check returned unexpected status: {result.exit_status}")
        elif self.detected_distro.name in ['SuSE', 'sles']:
            if result.exit_status != 0:
                self.log.warning(f"Zypper refresh returned non-zero: {result.exit_status}")
        stats_after = self._get_memory_stats()
        self.log.info(f"Memory stats after iteration: {stats_after}")
        self._verify_thp_counters_increased(stats_before, stats_after, iteration)
        self.log.info(f"Iteration {iteration + 1} completed successfully")

    def test(self):
        """
        Main test execution
        """
        self._enable_thp()
        initial_stats = self._get_memory_stats()
        self.log.info(f"Initial memory statistics: {initial_stats}")
        self._setup_kernel_source()
        self.log.info(f"Phase 3: Running {self.iterations} stress test iterations")
        self.log.info("Each iteration includes: kernel compilation + package updates")
        failed_iterations = []
        for i in range(self.iterations):
            try:
                self._run_stress_iteration(i)
            except Exception as e:
                self.log.error(f"Iteration {i + 1} failed: {str(e)}")
                failed_iterations.append(i + 1)
                continue
        final_stats = self._get_memory_stats()
        self.log.info(f"Final memory statistics: {final_stats}")
        self.log.info("Checking dmesg for kernel errors...")
        error_patterns = ['Call Trace', 'BUG:', 'WARNING:', 'Oops', 'segfault', 'soft lockup']
        errors = dmesg.collect_errors_dmesg(error_patterns)
        if errors:
            self.log.error(f"Kernel errors detected in dmesg: {errors}")
            self.fail(f"Test failed due to kernel errors in dmesg: {errors}")
        if failed_iterations:
            self.fail(f"Test failed at iterations: {failed_iterations}")
        else:
            self.log.info(f"All {self.iterations} iterations completed successfully")
            self.log.info("THP stress test validated successfully under memory-intensive workloads")

    def tearDown(self):
        """
        Cleanup and restore original settings
        """
        if self.original_thp_setting and os.path.exists(self.thp_enabled_file):
            try:
                setting = self.original_thp_setting
                for option in ['always', 'madvise', 'never']:
                    if f'[{option}]' in setting:
                        genio.write_file(self.thp_enabled_file, option)
                        self.log.info(f"Restored THP setting to: {option}")
                        break
            except Exception as e:
                self.log.warning(f"Could not restore THP setting: {e}")
        if self.kernel_dir and os.path.exists(self.kernel_dir):
            self.log.info("Cleaning up kernel source directory")
            try:
                shutil.rmtree(self.kernel_dir)
            except Exception as e:
                self.log.warning(f"Could not remove kernel directory: {e}")
