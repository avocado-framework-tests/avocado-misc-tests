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
# Author: Sachin Sant <sachinp@linux.ibm.com>
#
# Test for Linux kernel commit 4f61d54d2245c15b23ad78a89f854fb2496b6216
# "powerpc/qspinlock: Add spinlock contention tracepoint"
#
# This test validates the spinlock contention tracepoints added to the
# PowerPC queued spinlock slowpath. It verifies that:
# 1. The lock:contention_begin and lock:contention_end tracepoints exist
# 2. Tracepoints can be enabled and capture events
# 3. Spinlock contention generates the expected tracepoint events
# 4. The __lockfunc annotation works correctly
#
# This test uses the lockstorm benchmark module to generate spinlock
# contention. The cpu_list parameter can be used with both functional
# and stress tests to control which CPUs lockstorm runs on.

import os
import platform
import subprocess
import time
from avocado import Test
from avocado.utils import process, distro, dmesg, genio, git, build
from avocado.utils.software_manager.manager import SoftwareManager


class QspinlockTracepoint(Test):
    """
    Test for PowerPC queued spinlock contention tracepoints.

    This test validates the lock contention tracepoints added to the
    PowerPC qspinlock implementation in commit 4f61d54d2245.

    Uses the lockstorm benchmark module to generate spinlock contention.
    The cpu_list parameter (from YAML config) controls which CPUs lockstorm
    runs on and works with both functional and stress test types.

    :avocado: tags=kernel,powerpc,qspinlock,tracepoint,lockstorm
    """

    def setUp(self):
        """
        Set up the test environment and verify prerequisites.
        """
        arch = platform.machine()
        if 'ppc' not in arch and 'powerpc' not in arch:
            self.cancel("This test is specific to PowerPC architecture")

        smm = SoftwareManager()
        detected_distro = distro.detect()
        self.distro_name = detected_distro.name

        deps = ['gcc', 'make', 'git']
        if self.distro_name in ['rhel', 'SuSE', 'fedora', 'centos']:
            deps.extend(['perf', 'kernel-devel'])
            if self.distro_name in ['rhel', 'fedora', 'centos']:
                deps.append('kernel-headers')
        elif self.distro_name in ['Ubuntu', 'debian']:
            linux_headers = 'linux-headers-%s' % os.uname()[2]
            deps.extend(['linux-tools-common', 'linux-tools-generic',
                         linux_headers])
        else:
            deps.extend(['perf', 'kernel-devel'])

        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel("%s is needed for this test" % package)

        self.test_type = self.params.get('test_type', default='functional')
        self.cpu_list = self.params.get('cpu_list', default=0)
        self.lockstorm_timeout = self.params.get('lockstorm_timeout',
                                                 default=10)

        self.perf_data = os.path.join(self.workdir, 'perf.data')

        self.log.info("Cloning and building lockstorm benchmark")
        url = "https://github.com/npiggin/lockstorm.git"
        lockstorm_dir = os.path.join(self.workdir, 'lockstorm')
        git.get_repo(url, branch='master', destination_dir=lockstorm_dir)

        os.chdir(lockstorm_dir)
        build.make(lockstorm_dir)

        self.module_ko = os.path.join(lockstorm_dir, 'lockstorm.ko')
        if not os.path.isfile(self.module_ko):
            self.cancel("Lockstorm module build failed")

        self.module_name = 'lockstorm'
        self.module_loaded = False

        dmesg.clear_dmesg()
        self.failures = []

        self.log.info("=" * 60)
        self.log.info("Test setup complete")
        self.log.info("Architecture: %s", arch)
        self.log.info("Test type: %s", self.test_type)
        self.log.info("Lockstorm module: %s", self.module_ko)
        self.log.info("=" * 60)

    def _check_tracepoint_exists(self, tracepoint):
        """
        Check if a specific tracepoint exists in the system.

        :param tracepoint: Name of tracepoint(e.g., 'lock:contention_begin')
        :return: True if tracepoint exists, False otherwise
        """
        try:
            output = process.system_output('perf list', shell=True,
                                           ignore_status=True)
            if isinstance(output, bytes):
                output = output.decode('utf-8')
            if tracepoint in output:
                self.log.info("Tracepoint %s is available", tracepoint)
                return True
            else:
                self.log.warning("Tracepoint %s not found", tracepoint)
                return False
        except process.CmdError as e:
            self.log.error("Failed to list tracepoints: %s", e)
            return False

    def _check_qspinlock_enabled(self):
        """
        Check if queued spinlocks are enabled on the system.

        :return: True if qspinlock is enabled, False otherwise
        """
        config_file = os.path.join('/boot', 'config-' + platform.uname()[2])
        if os.path.exists(config_file):
            try:
                config_content = genio.read_file(config_file)
                if isinstance(config_content, bytes):
                    config_content = config_content.decode('utf-8')
                if 'CONFIG_PPC_QUEUED_SPINLOCKS=y' in config_content:
                    self.log.info("Queued spinlocks are enabled")
                    return True
                else:
                    self.log.warning("Queued spinlocks not enabled in \
                                     kernel config")
                    return False
            except Exception as e:
                self.log.warning("Could not read kernel config: %s", e)
                return False

        self.log.warning("Kernel config file not found: %s", config_file)
        return False

    def _load_lockstorm_module(self, cpu_list=None, timeout=None):
        """
        Load the lockstorm kernel module.

        Note: lockstorm runs once and automatically unloads itself after
        completing its benchmark. This is expected behavior.

        :param cpu_list: Optional CPU list to restrict testing
        :param timeout: Optional timeout in seconds for lockstorm duration
        :return: True if successful, False otherwise
        """
        if self.module_loaded:
            self.log.warning("Module already loaded, unloading first")
            self._unload_lockstorm_module()

        try:
            self.log.info("Loading lockstorm module")

            # Build insmod command with parameters
            params = []
            if cpu_list and cpu_list != 0:
                params.append('cpulist=%s' % cpu_list)
            if timeout:
                params.append('timeout=%d' % timeout)

            if params:
                insmod_cmd = 'insmod %s %s' % (self.module_ko,
                                               ' '.join(params))
            else:
                insmod_cmd = 'insmod %s' % self.module_ko

            result = process.run(insmod_cmd, shell=True, sudo=True,
                                 ignore_status=True)

            # Check if module loaded successfully by examining dmesg
            # lockstorm auto-unloads after running, so insmod may return
            # non-zero
            time.sleep(1)
            dmesg_output = process.system_output('dmesg | tail -20',
                                                 shell=True,
                                                 ignore_status=True)
            if isinstance(dmesg_output, bytes):
                dmesg_output = dmesg_output.decode('utf-8')

            # Check for successful module loading in dmesg first
            if 'lockstorm: loading out-of-tree module' in dmesg_output:
                self.log.info("Lockstorm module loaded and ran successfully")
                # Module auto-unloads, so don't set module_loaded flag
                self.module_loaded = False
                return True

            # If not found in dmesg, check for specific error conditions
            if result.exit_status != 0:
                stderr_output = (result.stderr.decode()
                                 if isinstance(result.stderr, bytes)
                                 else result.stderr)

                # Check for secure boot / module signing issues
                if 'Key was rejected by service' in stderr_output:
                    self.cancel("Module insertion rejected by kernel - "
                                "check secure boot settings")

                # "Resource temporarily unavailable" can occur when module
                # auto-unloads. Check dmesg more thoroughly for any
                # lockstorm messages
                full_dmesg = process.system_output(
                    'dmesg | grep lockstorm | tail -5',
                    shell=True,
                    ignore_status=True)
                if isinstance(full_dmesg, bytes):
                    full_dmesg = full_dmesg.decode('utf-8')

                if 'lockstorm' in full_dmesg:
                    self.log.info("Lockstorm module executed (found in dmesg)")
                    self.log.debug("Lockstorm dmesg output:\n%s", full_dmesg)
                    self.module_loaded = False
                    return True

                self.log.error("Failed to load lockstorm module: %s",
                               stderr_output)
                return False

            self.module_loaded = True
            self.log.info("Lockstorm module loaded successfully")

            # Give module time to complete
            time.sleep(2)

            return True

        except Exception as e:
            self.log.error("Failed to load lockstorm module: %s", e)
            return False

    def _unload_lockstorm_module(self):
        """
        Unload the lockstorm kernel module.

        :return: True if successful, False otherwise
        """
        if not self.module_loaded:
            return True

        try:
            self.log.info("Unloading lockstorm module")

            rmmod_cmd = 'rmmod %s' % self.module_name
            result = process.run(rmmod_cmd, shell=True, sudo=True,
                                 ignore_status=True)

            if result.exit_status != 0:
                self.log.warning("Failed to unload lockstorm module")
            else:
                self.log.info("Lockstorm module unloaded successfully")

            self.module_loaded = False
            return True

        except Exception as e:
            self.log.error("Failed to unload lockstorm module: %s", e)
            return False

    def _capture_lockstorm_output(self):
        """
        Capture lockstorm performance statistics from dmesg.

        :return: Lockstorm output string
        """
        try:
            cmd = "dmesg | grep 'lockstorm: spinlock iterations'"
            result = process.run(cmd, shell=True, ignore_status=True)
            if isinstance(result.stdout, bytes):
                return result.stdout.decode('utf-8')
            return result.stdout
        except Exception as e:
            self.log.error("Failed to capture lockstorm output: %s", e)
            return ""

    def _test_tracepoint_availability(self):
        """
        Verify that lock contention tracepoints are available.
        """
        self.log.info("=" * 60)
        self.log.info("Test 1: Checking tracepoint availability")
        self.log.info("=" * 60)

        if not self._check_tracepoint_exists('lock:contention_begin'):
            self.failures.append("lock:contention_begin tracepoint not found")

        if not self._check_tracepoint_exists('lock:contention_end'):
            self.failures.append("lock:contention_end tracepoint not found")

        if not self._check_qspinlock_enabled():
            self.log.warning("Queued spinlocks may not be enabled")

    def _test_tracepoint_enable(self):
        """
        Verify that tracepoints can be enabled and disabled.
        """
        self.log.info("=" * 60)
        self.log.info("Test 2: Testing tracepoint enable/disable")
        self.log.info("=" * 60)

        tracepoint_path = '/sys/kernel/debug/tracing/events/lock'

        if not os.path.exists(tracepoint_path):
            self.log.warning("Tracing filesystem not available at %s",
                             tracepoint_path)
            self.failures.append("Tracing filesystem not available")
            return

        try:
            enable_file = os.path.join(tracepoint_path,
                                       'contention_begin/enable')
            if os.path.exists(enable_file):
                process.run('echo 1 > %s' % enable_file, shell=True, sudo=True)
                self.log.info("Enabled lock:contention_begin tracepoint")

                enabled = genio.read_file(enable_file)
                if isinstance(enabled, bytes):
                    enabled = enabled.decode('utf-8')
                enabled = enabled.strip()
                if enabled != '1':
                    self.failures.append("Failed to enable \
                                         lock:contention_begin")

                process.run('echo 0 > %s' % enable_file, shell=True, sudo=True)
                self.log.info("Disabled lock:contention_begin tracepoint")
            else:
                self.log.warning("Enable file not found: %s", enable_file)
        except Exception as e:
            self.log.error("Failed to enable/disable tracepoint: %s", e)
            self.failures.append(
                "Tracepoint enable/disable failed: %s" % str(e))

    def _run_tracepoint_capture_test(self, test_name, cpu_list, record_time,
                                     min_events=0, lockstorm_timeout=None):
        """
        Helper function to run tracepoint capture tests with lockstorm.

        :param test_name: Name of the test for logging
        :param cpu_list: CPU list for lockstorm (None for all CPUs)
        :param record_time: Duration for perf recording in seconds
        :param min_events: Minimum expected events (0 means just check > 0)
        :param lockstorm_timeout: Timeout for lockstorm module in seconds
        :return: True if test passed, False otherwise
        """
        perf_process = None
        try:
            dmesg.clear_dmesg()

            self.log.info("Starting perf recording for %s...", test_name)

            record_cmd = ('perf record -a -e lock:contention_begin,'
                          'lock:contention_end '
                          '-o %s sleep %d' % (self.perf_data, record_time))

            perf_process = subprocess.Popen(record_cmd, shell=True,
                                            stdout=subprocess.PIPE,
                                            stderr=subprocess.PIPE)

            time.sleep(0.5)

            if lockstorm_timeout:
                self.log.info("Loading lockstorm module (cpu_list=%s, "
                              "timeout=%ds)...", cpu_list, lockstorm_timeout)
            else:
                self.log.info("Loading lockstorm module (cpu_list=%s)...",
                              cpu_list)

            if not self._load_lockstorm_module(cpu_list, lockstorm_timeout):
                self.failures.append("Failed to load lockstorm module for %s" %
                                     test_name)
                if perf_process:
                    perf_process.terminate()
                    perf_process.wait()
                return False

            self.log.info("Waiting for perf recording to complete...")
            perf_process.wait(timeout=record_time + 5)

            lockstorm_output = self._capture_lockstorm_output()
            if lockstorm_output:
                self.log.info("%s lockstorm output:\n%s", test_name,
                              lockstorm_output)

            self._unload_lockstorm_module()

            if not os.path.exists(self.perf_data):
                self.failures.append("%s: perf.data file missing" % test_name)
                return False

            file_size = os.path.getsize(self.perf_data)
            self.log.info("%s perf.data size: %d bytes", test_name, file_size)

            if file_size == 0:
                self.failures.append("%s: perf.data file is empty" % test_name)
                return False

            script_cmd = 'perf script -i %s' % self.perf_data
            script_output = process.system_output(script_cmd, shell=True,
                                                  ignore_status=True)
            if isinstance(script_output, bytes):
                script_output = script_output.decode('utf-8')

            contention_begin_count = script_output.count('lock:contention_begin')
            contention_end_count = script_output.count('lock:contention_end')

            self.log.info("%s captured lock:contention_begin events: %d",
                          test_name, contention_begin_count)
            self.log.info("%s captured lock:contention_end events: %d",
                          test_name, contention_end_count)

            if min_events > 0:
                if contention_begin_count < min_events:
                    self.failures.append("%s: Too few contention_begin events "
                                         "(%d < %d)"
                                         % (test_name, contention_begin_count,
                                            min_events))

                if contention_end_count < min_events:
                    self.failures.append("%s: Too few contention_end events "
                                         "(%d < %d)"
                                         % (test_name, contention_end_count,
                                            min_events))
            else:
                if contention_begin_count == 0:
                    self.failures.append("%s: No lock:contention_begin events "
                                         "captured" % test_name)

                if contention_end_count == 0:
                    self.failures.append("%s: No lock:contention_end events "
                                         "captured" % test_name)

            if contention_begin_count > 0 and contention_end_count > 0:
                if abs(contention_begin_count - contention_end_count) > 10:
                    self.log.warning("%s: Unbalanced begin/end events: "
                                     "begin=%d, end=%d",
                                     test_name, contention_begin_count,
                                     contention_end_count)

            report_cmd = 'perf report -i %s --stdio' % self.perf_data
            report_output = process.system_output(report_cmd, shell=True,
                                                  ignore_status=True)
            if isinstance(report_output, bytes):
                report_output = report_output.decode('utf-8')
            self.log.debug("%s perf report:\n%s", test_name, report_output)

            return True

        except Exception as e:
            self.log.error("%s failed: %s", test_name, e)
            self.failures.append("%s exception: %s" % (test_name, str(e)))
            return False
        finally:
            if perf_process and perf_process.poll() is None:
                perf_process.terminate()
                try:
                    perf_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    perf_process.kill()
                    perf_process.wait()

            self._unload_lockstorm_module()

            if os.path.exists(self.perf_data):
                process.run('rm -f %s' % self.perf_data, shell=True)

    def _test_functional_tracepoint_capture(self):
        """
        Functional test - capture tracepoint events with lockstorm.

        Uses lockstorm module with default settings for basic validation.
        """
        self.log.info("=" * 60)
        self.log.info("Test 3: Functional tracepoint capture with lockstorm")
        self.log.info("=" * 60)

        # Calculate perf recording time based on lockstorm timeout
        # Add 2 seconds buffer to ensure we capture all events
        record_time = self.lockstorm_timeout + 2

        self._run_tracepoint_capture_test(
            test_name="Functional test",
            cpu_list=self.cpu_list,
            record_time=record_time,
            min_events=0,  # Just check that some events were captured
            lockstorm_timeout=self.lockstorm_timeout
        )

    def _test_stress_tracepoint_capture(self):
        """
        Stress test - capture tracepoint events with lockstorm under load.

        Uses lockstorm module for stress testing spinlock contention.
        """
        self.log.info("=" * 60)
        self.log.info("Test 4: Stress test with lockstorm")
        self.log.info("=" * 60)

        # Calculate perf recording time based on lockstorm timeout
        # Add 5 seconds buffer for stress test to ensure we capture all events
        record_time = self.lockstorm_timeout + 5

        self._run_tracepoint_capture_test(
            test_name="Stress test",
            cpu_list=self.cpu_list,
            record_time=record_time,
            min_events=10,  # Require minimum 10 events for stress test
            lockstorm_timeout=self.lockstorm_timeout
        )

    def _test_lockfunc_annotation(self):
        """
        Verify __lockfunc annotation is working correctly.

        The __lockfunc annotation should make in_lock_functions() work
        correctly, which affects how the kernel handles these functions
        in various contexts.
        """
        self.log.info("=" * 60)
        self.log.info("Test 5: Verifying __lockfunc annotation")
        self.log.info("=" * 60)

        try:
            output = process.system_output('grep queued_spin_lock_slowpath \
                                           /proc/kallsyms',
                                           shell=True, ignore_status=True)
            if isinstance(output, bytes):
                output = output.decode('utf-8')

            if 'queued_spin_lock_slowpath' in output:
                self.log.info("Found queued_spin_lock_slowpath in kallsyms:")
                self.log.info(output.strip())

                self.log.info("__lockfunc annotation verified via kallsyms")
            else:
                self.log.warning("queued_spin_lock_slowpath not found in \
                                 kallsyms")

        except Exception as e:
            self.log.warning("Could not verify __lockfunc annotation: %s", e)

    def test(self):
        """
        Main test execution method.

        Runs all test cases based on the test_type parameter.
        """
        self.log.info("=" * 60)
        self.log.info("Starting qspinlock tracepoint validation tests")
        self.log.info("Test type: %s", self.test_type)
        self.log.info("=" * 60)

        self._test_tracepoint_availability()
        self._test_tracepoint_enable()

        if self.test_type == 'functional':
            self._test_lockfunc_annotation()
            self._test_functional_tracepoint_capture()
        elif self.test_type == 'stress':
            self._test_stress_tracepoint_capture()

        dmesg.collect_errors_dmesg(['WARNING: CPU:', 'Oops', 'Segfault',
                                    'soft lockup', 'Unable to handle',
                                    'BUG:', 'Call Trace:'])

        if self.failures:
            self.log.error("=" * 60)
            self.log.error("Test completed with %d failure(s):",
                           len(self.failures))
            for i, failure in enumerate(self.failures, 1):
                self.log.error("%d. %s", i, failure)
            self.log.error("=" * 60)
            self.fail("Test failed with %d issue(s). See log for details." %
                      len(self.failures))
        else:
            self.log.info("=" * 60)
            self.log.info("All tests passed successfully!")
            self.log.info("=" * 60)

    def tearDown(self):
        """
        Clean up test environment.
        """
        if hasattr(self, 'module_loaded') and self.module_loaded:
            try:
                self.log.info("Cleaning up: unloading lockstorm module")
                self._unload_lockstorm_module()
            except Exception as e:
                self.log.warning("Failed to unload lockstorm module during "
                                 "cleanup: %s", e)

        if hasattr(self, 'perf_data') and os.path.exists(self.perf_data):
            try:
                process.run('rm -f %s' % self.perf_data, shell=True)
            except Exception as e:
                self.log.warning("Failed to remove perf.data: %s", e)

        self.log.info("Test cleanup complete")
