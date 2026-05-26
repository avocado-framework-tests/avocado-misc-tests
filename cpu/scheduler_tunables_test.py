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
# Author: Samir <samir@linux.ibm.com>

"""
Test suite for Linux CFS scheduler tunables testing.
FOCUSED ON TOP 4 VERIFIABLE TUNABLES ONLY.

This test validates the 4 most important CFS scheduler tunables:
1. base_slice_ns - Controls the base time slice for CFS scheduler
2. sched_migration_cost_ns - Controls task migration cost threshold
3. sched_nr_migrate - Controls number of tasks to migrate at once
4. sched_schedstats - Enables scheduler statistics (required for verification)
"""

import os
import time
from avocado import Test
from avocado.utils import process, cpu, genio
from avocado.utils.software_manager.manager import SoftwareManager


class SchedulerTunablesTest(Test):
    """
    Test Linux scheduler tunables - TOP 4 VERIFIABLE TUNABLES.
    Validates scheduler behavior with different tunable configurations.

    :avocado: tags=cpu,scheduler,tunables,privileged
    """

    NS_TO_MS = 1_000_000
    MIN_BASE_SLICE_NS = 750000
    MIN_MIGRATION_COST_NS = 50000

    def setUp(self):
        """
        Setup test environment and verify scheduler support.
        """
        self.sm = SoftwareManager()

        required_packages = ['stress-ng', 'perf']
        for package in required_packages:
            if not self.sm.check_installed(package):
                if not self.sm.install(package):
                    self.cancel(f"Failed to install {package}")

        self.total_cpus = cpu.online_count()
        self.log.info("Total online CPUs: %d", self.total_cpus)

        self.test_duration = int(self.params.get('test_duration', default=10))

        configured_workers = self.params.get('stress_workers', default=0)
        if not configured_workers:
            # Cap at reasonable limit to prevent resource exhaustion on small
            # LPARs
            # Use 4x CPUs for systems with <= 8 CPUs, 8x for larger systems
            multiplier = 4 if self.total_cpus <= 8 else 8
            self.stress_workers = self.total_cpus * multiplier
            self.log.info(
                "Auto-calculating stress workers: %d (%dx %d CPUs)",
                self.stress_workers, multiplier, self.total_cpus)
        else:
            self.stress_workers = int(configured_workers)
            self.log.info("Using configured stress workers: %d",
                          self.stress_workers)

        self.original_tunables = {}

        if not os.path.ismount('/sys/kernel/debug'):
            self.log.warning("debugfs not mounted at /sys/kernel/debug")
            self.log.info("Attempting to mount debugfs...")
            try:
                result = process.run(
                    'mount -t debugfs none /sys/kernel/debug',
                    shell=True, sudo=True, ignore_status=True)
                if result.exit_status != 0:
                    self.cancel(
                        "Failed to mount debugfs. This is required for "
                        "base_slice_ns tunable access.")
                else:
                    self.log.info("Successfully mounted debugfs")
            except Exception as e:
                self.cancel(
                    f"Could not mount debugfs: {str(e)}. This is required "
                    "for base_slice_ns tunable access.")
        else:
            self.log.info("debugfs is mounted at /sys/kernel/debug")

        self.log.info("\n" + "=" * 70)
        self.log.info("TEST CONFIGURATION - TOP 4 TUNABLES")
        self.log.info("=" * 70)
        self.log.info("  Duration: %d seconds", self.test_duration)
        self.log.info("  Workers: %d", self.stress_workers)
        self.log.info("  CPUs: %d", self.total_cpus)
        self.log.info("=" * 70)

        self._check_and_save_tunables()

    def _get_tunable_path(self, tunable_name):
        """
        Get the correct path for a tunable.
        Returns the first existing path, or None if not found.

        Note: These paths are standard across major Linux distributions
        (RHEL, SLES, Ubuntu) for kernel 5.x and above.
        """
        tunable_paths = {
            'base_slice_ns': [
                '/sys/kernel/debug/sched/base_slice_ns',
            ],
            'sched_migration_cost_ns': [
                '/proc/sys/kernel/sched_migration_cost_ns',
                '/sys/kernel/debug/sched/migration_cost_ns',
            ],
            'sched_nr_migrate': [
                '/proc/sys/kernel/sched_nr_migrate',
                '/sys/kernel/debug/sched/nr_migrate',
            ],
            'sched_schedstats': [
                '/proc/sys/kernel/sched_schedstats',
            ],
        }

        paths = tunable_paths.get(tunable_name, [])
        for path in paths:
            if os.path.exists(path):
                return path
        return None

    def _check_and_save_tunables(self):
        """
        Check availability and save original values of top 4 tunables.
        """
        self.log.info("\n--- Checking Top 4 Scheduler Tunables ---")

        tunables = [
            'base_slice_ns',
            'sched_migration_cost_ns',
            'sched_nr_migrate',
            'sched_schedstats',
        ]

        for tunable_name in tunables:
            tunable_path = self._get_tunable_path(tunable_name)
            if tunable_path:
                try:
                    value = genio.read_file(tunable_path).strip()
                    self.original_tunables[tunable_path] = value
                    self.log.info("  ✓ %s = %s", tunable_name, value)
                except Exception as e:
                    self.log.warning(
                        "  ⚠ Failed to read %s: %s", tunable_name, str(e))
            else:
                self.log.warning("  ✗ %s NOT FOUND", tunable_name)

        self.log.info("=" * 70)

    def _set_tunable(self, tunable_name, value):
        """
        Set a scheduler tunable value.
        """
        tunable_path = self._get_tunable_path(tunable_name)
        if not tunable_path:
            self.fail(f"Tunable {tunable_name} not found")

        try:
            genio.write_file(tunable_path, str(value))
            self.log.info("Set %s = %s", tunable_name, value)
        except Exception as e:
            self.log.error("Failed to set %s: %s", tunable_name, str(e))
            self.fail(f"Failed to set {tunable_name}: {str(e)}")

    def _get_tunable(self, tunable_name):
        """
        Get current value of a scheduler tunable.
        """
        tunable_path = self._get_tunable_path(tunable_name)
        if not tunable_path:
            return None

        try:
            return genio.read_file(tunable_path).strip()
        except Exception as e:
            self.log.error("Failed to read %s: %s", tunable_name, str(e))
            return None

    def _log_tunable_change(self, name, old_val, new_val, unit='ns'):
        """
        Log tunable value change with appropriate unit conversion.

        Args:
            name: Name of the tunable
            old_val: Original value
            new_val: New value
            unit: Unit type ('ns' for nanoseconds, 'tasks' for task count)
        """
        if unit == 'ns':
            self.log.info(
                '  %s: %d -> %d (%.2f ms -> %.2f ms)',
                name, old_val, new_val,
                old_val / self.NS_TO_MS, new_val / self.NS_TO_MS)
        else:
            self.log.info('  %s: %d -> %d %s', name, old_val, new_val, unit)

    def _compare_and_log_metrics(self, baseline_metrics, test_metrics,
                                 metric_name, display_name):
        """
        Compare and log metric changes between baseline and test.

        Args:
            baseline_metrics: Dictionary of baseline metrics
            test_metrics: Dictionary of test metrics
            metric_name: Key name of the metric to compare
            display_name: Human-readable name for logging

        Returns:
            Percentage change if baseline > 0, None otherwise
        """
        baseline_val = baseline_metrics.get(metric_name, 0)
        test_val = test_metrics.get(metric_name, 0)

        self.log.info('\n%s:', display_name)
        self.log.info('  Baseline: %d', baseline_val)
        self.log.info('  Test: %d', test_val)

        if baseline_val > 0:
            change_pct = ((test_val - baseline_val) / baseline_val) * 100
            self.log.info('  Change: %+.1f%%', change_pct)
            return change_pct
        return None

    def _restore_tunables(self):
        """
        Restore original tunable values.
        """
        self.log.info("\n--- Restoring Original Tunables ---")
        for tunable_path, value in self.original_tunables.items():
            try:
                genio.write_file(tunable_path, value)
                self.log.info("  Restored %s = %s", tunable_path, value)
            except Exception as e:
                self.log.warning("  Failed to restore %s: %s",
                                 tunable_path, str(e))

    def _build_stress_command(self, workload_type, duration):
        """
        Build stress-ng command based on workload type.

        Args:
            workload_type: Type of workload (cpu, context-switch, fork, mixed)
            duration: Duration in seconds

        Returns:
            Tuple of (stress_command, log_message)
        """
        if workload_type == 'cpu':
            return (
                f"stress-ng --cpu {self.stress_workers} --timeout {duration}s",
                "Running CPU-bound workload (tests base_slice_ns)"
            )
        elif workload_type == 'context-switch':
            workers = min(self.stress_workers, self.total_cpus * 4)
            return (
                f"stress-ng --switch {workers} --timeout {duration}s",
                "Running context-switch workload (tests migration_cost_ns)"
            )
        elif workload_type == 'fork':
            workers = min(self.stress_workers // 2, 64)
            return (
                f"stress-ng --fork {workers} --timeout {duration}s",
                "Running fork workload (tests sched_nr_migrate)"
            )
        elif workload_type == 'mixed':
            cpu_workers = self.stress_workers // 2
            io_workers = self.stress_workers // 4
            return (
                f"stress-ng --cpu {cpu_workers} --io {io_workers} "
                f"--timeout {duration}s",
                "Running mixed CPU+I/O workload"
            )
        else:
            return (
                f"stress-ng --cpu {self.stress_workers} --timeout {duration}s",
                f"Running default workload"
            )

    def _parse_perf_rate(self, rate_str):
        """
        Parse a rate value from perf stat output.

        Args:
            rate_str: Numeric rate string as output by perf (e.g., "423.717",
                      "1.5"). Note: The SI unit suffix (e.g., "M/sec") is a
                      separate token in perf output and is NOT handled here.
                      This function returns the raw numeric value as-is.

        Returns:
            Float: the numeric value parsed from rate_str, or 0.0 on error.
        """
        try:
            return float(rate_str)
        except (ValueError, AttributeError):
            return 0.0

    def _parse_perf_output(self, perf_output):
        """
        Parse perf stat output and extract metrics.

        Args:
            perf_output: Raw perf stat output string

        Returns:
            Dictionary of parsed metrics
        """
        metrics = {
            'context_switches': 0,
            'cs_per_second': 0.0,
            'cpu_migrations': 0,
            'migrations_per_second': 0.0,
            'page_faults': 0,
            'task_clock_ms': 0.0,
            'cpus_utilized': 0.0,
            'branch_misses': 0,
            'branch_miss_rate': 0.0,
            'branches': 0,
            'cpu_cycles': 0,
            'instructions': 0,
            'insn_per_cycle': 0.0,
            'time_elapsed': 0.0
        }

        for line in perf_output.split('\n'):
            line = line.strip()

            if 'context-switches' in line:
                parts = line.split()
                metrics['context_switches'] = int(parts[0].replace(',', ''))
                for i, part in enumerate(parts):
                    if '/sec' in part and i > 0:
                        rate_str = parts[i-1]
                        metrics['cs_per_second'] = self._parse_perf_rate(
                            rate_str)

            elif 'cpu-migrations' in line:
                parts = line.split()
                metrics['cpu_migrations'] = int(parts[0].replace(',', ''))
                for i, part in enumerate(parts):
                    if '/sec' in part and i > 0:
                        rate_str = parts[i-1]
                        metrics['migrations_per_second'] = \
                            self._parse_perf_rate(rate_str)

            elif 'page-faults' in line:
                parts = line.split()
                metrics['page_faults'] = int(parts[0].replace(',', ''))

            elif 'task-clock' in line:
                parts = line.split()
                metrics['task_clock_ms'] = float(parts[0].replace(',', ''))
                for i, part in enumerate(parts):
                    if 'CPUs' in part and i > 0:
                        metrics['cpus_utilized'] = float(parts[i-1])

            elif 'branch' in line:
                # Parse branch-related metrics using position-based approach
                # Perf format: "<count> <event-name> # <description>"
                # Example 1: "603,989,146  branches  #  423.717 M/sec"
                # Example 2: "13,838,135   branch-misses #
                # 2.29% of all  branches"
                parts = line.split()
                if len(parts) >= 2 and parts[0].replace(',', '').isdigit():
                    count = int(parts[0].replace(',', ''))
                    # Second column is the actual event name
                    event_name = parts[1]

                    # Check the actual event name (second column),
                    # not the description
                    if event_name == 'branch-misses':
                        metrics['branch_misses'] = count
                        # Extract percentage if present in description
                        for i, part in enumerate(parts):
                            if '%' in part:
                                metrics['branch_miss_rate'] = float(
                                    part.replace('%', ''))
                    elif event_name == 'branches':
                        metrics['branches'] = count

            elif 'cpu-cycles' in line:
                parts = line.split()
                metrics['cpu_cycles'] = int(parts[0].replace(',', ''))

            elif 'instructions' in line:
                parts = line.split()
                metrics['instructions'] = int(parts[0].replace(',', ''))
                for i, part in enumerate(parts):
                    if 'instructions' in part and i > 1:
                        try:
                            metrics['insn_per_cycle'] = float(parts[i-1])
                        except (ValueError, IndexError):
                            pass

            elif 'seconds time elapsed' in line:
                parts = line.split()
                metrics['time_elapsed'] = float(parts[0])

        return metrics

    def _log_metrics(self, metrics):
        """
        Log scheduler metrics in a formatted way.

        Args:
            metrics: Dictionary of metrics to log
        """
        self.log.info("\n" + "=" * 70)
        self.log.info("SCHEDULER METRICS (via perf stat)")
        self.log.info("=" * 70)
        self.log.info(
            "Context switches: %d (%.1f cs/sec)",
            metrics['context_switches'], metrics['cs_per_second'])
        self.log.info(
            "CPU migrations: %d (%.1f migrations/sec)",
            metrics['cpu_migrations'],
            metrics['migrations_per_second'])
        self.log.info("Page faults: %d", metrics['page_faults'])
        self.log.info("Task clock: %.2f ms (%.1f CPUs utilized)",
                      metrics['task_clock_ms'], metrics['cpus_utilized'])
        self.log.info("Instructions per cycle: %.2f",
                      metrics['insn_per_cycle'])
        self.log.info("Time elapsed: %.2f seconds",
                      metrics['time_elapsed'])

        if metrics['context_switches'] > 0:
            migrations_per_1k_cs = (
                metrics['cpu_migrations'] * 1000.0 /
                metrics['context_switches'])
            self.log.info("\nDerived Metrics:")
            self.log.info(
                "  Migrations per 1000 context switches: %.2f",
                migrations_per_1k_cs)
            # Sanity check: ratio should be reasonable for all system sizes
            if migrations_per_1k_cs > 1000:
                self.log.warning(
                    "  ⚠ Unusually high migration ratio - may indicate "
                    "system instability")

        self.log.info("=" * 70)

    def _run_workload_single(self, duration=None, workload_type='cpu'):
        """
        Run a single iteration of workload with perf stat.
        Internal method - use _run_workload() for averaged results.
        """
        if duration is None:
            duration = self.test_duration

        stress_cmd, log_msg = self._build_stress_command(
            workload_type, duration)
        self.log.info(log_msg)

        perf_cmd = (
            f"perf stat -e context-switches,cpu-migrations,page-faults,"
            f"task-clock,branch-misses,branches,cpu-cycles,instructions "
            f"{stress_cmd}")
        self.log.info("Command: %s", perf_cmd)

        try:
            result = process.run(perf_cmd, shell=True, ignore_status=True)
            perf_output = result.stderr.decode() if result.stderr else ""

            metrics = self._parse_perf_output(perf_output)
            self._log_metrics(metrics)

            return {
                'success': result.exit_status == 0,
                'metrics': metrics,
                'raw_output': perf_output
            }

        except Exception as e:
            self.log.error("Workload with perf failed: %s", str(e))
            return {
                'success': False,
                'metrics': {},
                'raw_output': str(e)
            }

    def _run_workload(self, duration=None, workload_type='cpu', iterations=10):
        """
        Run workload multiple times and return AVERAGE metrics.

        This reduces noise and provides more reliable measurements.
        Default: 10 iterations

        Returns dict with:
        - success: bool
        - metrics: dict with averaged values
        - all_runs: list of individual run metrics
        - std_dev: standard deviation for key metrics

        Note: Iterations use short duration stress tests to prevent OOM.
        Each iteration is independent and releases resources before the next.
        """
        if duration is None:
            duration = self.test_duration

        self.log.info(
            "\n--- Running %d iterations for reliable metrics ---", iterations)
        self.log.info(
            "Using short duration (%ds) per iteration to prevent resource "
            "exhaustion", duration)

        all_runs = []
        successful_runs = 0

        for i in range(iterations):
            self.log.info("Iteration %d/%d...", i + 1, iterations)
            result = self._run_workload_single(duration, workload_type)

            if result['success']:
                all_runs.append(result['metrics'])
                successful_runs += 1
            else:
                self.log.warning("Iteration %d failed", i + 1)

        if successful_runs == 0:
            return {
                'success': False,
                'metrics': {},
                'all_runs': [],
                'std_dev': {}
            }

        avg_metrics = {}
        std_dev = {}

        metric_keys = all_runs[0].keys() if all_runs else []

        for key in metric_keys:
            values = [run[key] for run in all_runs if key in run]
            if values:
                avg_metrics[key] = sum(values) / len(values)

                if key in ['context_switches', 'cpu_migrations',
                           'page_faults']:
                    mean = avg_metrics[key]
                    variance = sum(
                        (x - mean) ** 2 for x in values) / len(values)
                    std_dev[key] = variance ** 0.5

        self.log.info("\n" + "=" * 70)
        self.log.info("AVERAGED METRICS (%d successful runs)", successful_runs)
        self.log.info("=" * 70)
        self.log.info("Context switches: %.0f (±%.0f)",
                      avg_metrics.get('context_switches', 0),
                      std_dev.get('context_switches', 0))
        self.log.info("CPU migrations: %.0f (±%.0f)",
                      avg_metrics.get('cpu_migrations', 0),
                      std_dev.get('cpu_migrations', 0))
        self.log.info("Page faults: %.0f (±%.0f)",
                      avg_metrics.get('page_faults', 0),
                      std_dev.get('page_faults', 0))
        self.log.info("Task clock: %.2f ms",
                      avg_metrics.get('task_clock_ms', 0))
        self.log.info("Instructions per cycle: %.2f",
                      avg_metrics.get('insn_per_cycle', 0))

        if avg_metrics.get('context_switches', 0) > 0:
            migrations_per_1k = (
                avg_metrics.get('cpu_migrations', 0) * 1000.0 /
                avg_metrics['context_switches'])
            self.log.info(
                "Migrations per 1000 context switches: %.2f",
                migrations_per_1k)

        self.log.info("=" * 70)

        return {
            'success': True,
            'metrics': avg_metrics,
            'all_runs': all_runs,
            'std_dev': std_dev,
            'successful_runs': successful_runs,
            'total_runs': iterations
        }

    def test_01_baseline(self):
        """
        Test 1: Verify scheduler behavior with default tunables.
        Tests that scheduler works correctly with system default values.
        """
        self.log.info("\n" + "=" * 70)
        self.log.info("TEST 1: DEFAULT TUNABLES Verification")
        self.log.info("=" * 70)

        self.log.info("\nCurrent tunable values:")
        baseline_base_slice = self._get_tunable('base_slice_ns')
        baseline_migration_cost = self._get_tunable('sched_migration_cost_ns')
        baseline_nr_migrate = self._get_tunable('sched_nr_migrate')
        baseline_schedstats = self._get_tunable('sched_schedstats')

        self.log.info("  base_slice_ns = %s", baseline_base_slice)
        self.log.info("  sched_migration_cost_ns = %s",
                      baseline_migration_cost)
        self.log.info("  sched_nr_migrate = %s", baseline_nr_migrate)
        self.log.info("  sched_schedstats = %s", baseline_schedstats)

        workload_type = self.params.get(
            'workload_type', path='/tests/baseline/*', default='mixed')

        self.log.info("\nRunning workload with DEFAULT tunables...")
        result = self._run_workload(workload_type=workload_type)

        if result['success']:
            metrics = result['metrics']

            self.log.info("\n--- VALIDATION: Default Tunable Behavior ---")
            self.log.info("Context switches: %d",
                          metrics.get('context_switches', 0))
            self.log.info("CPU migrations: %d",
                          metrics.get('cpu_migrations', 0))

            if metrics.get('context_switches', 0) > 0:
                self.log.info(
                    "✓ Context switches detected (scheduler is working)")
            else:
                self.fail("No context switches detected - scheduler may not "
                          "be functioning correctly")

            if metrics.get('cpu_migrations', 0) > 0:
                self.log.info(
                    "✓ CPU migrations detected (load balancing is working)")
            else:
                self.fail("No CPU migrations detected - load balancing may "
                          "not be functioning correctly")

            self.baseline_metrics = metrics
            self.log.info("\n✓ Default tunables test completed successfully")
            self.log.info(
                "✓ Baseline metrics stored for comparison in other tests")
        else:
            self.fail("Baseline test failed")

    def test_02_low_latency(self):
        """
        Test 2: Low latency configuration (reduced base_slice_ns and
        migration_cost_ns).
        VALIDATION: Collect baseline BEFORE changing, then AFTER changing,
        and compare.
        """
        self.log.info("\n" + "=" * 70)
        self.log.info("TEST 2: LOW LATENCY Configuration")
        self.log.info("=" * 70)

        baseline_base_slice = self._get_tunable('base_slice_ns')
        baseline_migration_cost = self._get_tunable('sched_migration_cost_ns')

        if baseline_base_slice and baseline_migration_cost:
            self.log.info("\n--- STEP 1: Baseline (Default Tunables) ---")
            self.log.info("Current tunables:")
            self.log.info(
                "  base_slice_ns: %d (%.2f ms)",
                int(baseline_base_slice),
                int(baseline_base_slice) / self.NS_TO_MS)
            self.log.info(
                "  migration_cost_ns: %d (%.2f ms)",
                int(baseline_migration_cost),
                int(baseline_migration_cost) / self.NS_TO_MS)

            workload_type = self.params.get(
                'workload_type', path='/tests/low_latency/*', default='cpu')
            base_slice_factor = float(self.params.get(
                'base_slice_ns_factor',
                path='/tests/low_latency/tunables/*',
                default=0.25))
            migration_cost_factor = float(self.params.get(
                'migration_cost_ns_factor',
                path='/tests/low_latency/tunables/*',
                default=0.10))

            self.log.info("\nRunning workload with DEFAULT tunables...")
            baseline_result = self._run_workload(workload_type=workload_type)

            if not baseline_result['success']:
                self.fail("Baseline workload failed")

            self.log.info("\n--- STEP 2: Low Latency (Modified Tunables) ---")
            low_base_slice = max(
                self.MIN_BASE_SLICE_NS,
                int(float(baseline_base_slice) * base_slice_factor))
            low_migration_cost = max(
                self.MIN_MIGRATION_COST_NS,
                int(float(baseline_migration_cost) * migration_cost_factor))

            self.log.info("Setting low latency tunables:")
            self._log_tunable_change('base_slice_ns',
                                     int(baseline_base_slice), low_base_slice)
            self._log_tunable_change('migration_cost_ns',
                                     int(baseline_migration_cost),
                                     low_migration_cost)

            self._set_tunable('base_slice_ns', low_base_slice)
            self._set_tunable('sched_migration_cost_ns', low_migration_cost)
            time.sleep(2)

            self.log.info("\nRunning workload with LOW LATENCY tunables...")
            test_result = self._run_workload(workload_type=workload_type)

            if test_result['success']:
                self.log.info("\n" + "=" * 70)
                self.log.info("VALIDATION: Comparing Baseline vs Low Latency")
                self.log.info("=" * 70)

                cs_change = self._compare_and_log_metrics(
                    baseline_result['metrics'], test_result['metrics'],
                    'context_switches', 'Context Switches')

                if cs_change and cs_change > 0:
                    self.log.info(
                        '  ✓ EXPECTED: More context switches with '
                        'smaller time slices')
                elif cs_change is not None:
                    self.log.warning('  ⚠ UNEXPECTED: Fewer context switches')

                self._compare_and_log_metrics(
                    baseline_result['metrics'], test_result['metrics'],
                    'cpu_migrations', 'CPU Migrations')

                self.log.info("=" * 70)

            if test_result['success']:
                self.log.info("\n✓ Low latency test completed successfully")
            else:
                self.fail("Low latency test failed")
        else:
            self.cancel("Required tunables not available")

    def test_03_high_throughput(self):
        """
        Test 3: High throughput configuration (increased base_slice_ns
        and migration_cost_ns).
        VALIDATION: Collect baseline BEFORE changing, then AFTER changing,
        and compare.
        """
        self.log.info("\n" + "=" * 70)
        self.log.info("TEST 3: HIGH THROUGHPUT Configuration")
        self.log.info("=" * 70)

        baseline_base_slice = self._get_tunable('base_slice_ns')
        baseline_migration_cost = self._get_tunable('sched_migration_cost_ns')

        if baseline_base_slice and baseline_migration_cost:
            self.log.info("\n--- STEP 1: Baseline (Default Tunables) ---")
            self.log.info("Current tunables:")
            self.log.info(
                "  base_slice_ns: %d (%.2f ms)",
                int(baseline_base_slice),
                int(baseline_base_slice) / self.NS_TO_MS)
            self.log.info(
                "  migration_cost_ns: %d (%.2f ms)",
                int(baseline_migration_cost),
                int(baseline_migration_cost) / self.NS_TO_MS)

            workload_type = self.params.get(
                'workload_type',
                path='/tests/high_throughput/*',
                default='context-switch')
            base_slice_factor = float(self.params.get(
                'base_slice_ns_factor',
                path='/tests/high_throughput/tunables/*',
                default=3.0))
            migration_cost_factor = float(self.params.get(
                'migration_cost_ns_factor',
                path='/tests/high_throughput/tunables/*',
                default=2.0))

            self.log.info("\nRunning workload with DEFAULT tunables...")
            baseline_result = self._run_workload(workload_type=workload_type)

            if not baseline_result['success']:
                self.fail("Baseline workload failed")

            self.log.info(
                "\n--- STEP 2: High Throughput (Modified Tunables) ---")
            high_base_slice = int(
                float(baseline_base_slice) * base_slice_factor)
            high_migration_cost = int(
                float(baseline_migration_cost) * migration_cost_factor)

            self.log.info("Setting high throughput tunables:")
            self._log_tunable_change('base_slice_ns',
                                     int(baseline_base_slice), high_base_slice)
            self._log_tunable_change('migration_cost_ns',
                                     int(baseline_migration_cost),
                                     high_migration_cost)

            self._set_tunable('base_slice_ns', high_base_slice)
            self._set_tunable('sched_migration_cost_ns', high_migration_cost)

            time.sleep(2)

            self.log.info(
                "\nRunning workload with HIGH THROUGHPUT tunables...")
            test_result = self._run_workload(workload_type=workload_type)

            if test_result['success']:
                self.log.info("\n" + "=" * 70)
                self.log.info(
                    "VALIDATION: Comparing Baseline vs High Throughput")
                self.log.info("=" * 70)

                cs_change = self._compare_and_log_metrics(
                    baseline_result['metrics'], test_result['metrics'],
                    'context_switches', 'Context Switches')

                if cs_change and cs_change < 0:
                    self.log.info(
                        '  ✓ EXPECTED: Fewer context switches with '
                        'larger time slices')
                elif cs_change is not None:
                    self.log.warning('  ⚠ UNEXPECTED: More context switches')

                self._compare_and_log_metrics(
                    baseline_result['metrics'], test_result['metrics'],
                    'cpu_migrations', 'CPU Migrations')

                self.log.info("=" * 70)

            if test_result['success']:
                self.log.info(
                    "✓ High throughput test completed successfully")
            else:
                self.fail("High throughput test failed")
        else:
            self.cancel(
                "Required tunables not available for high throughput test")

    def test_04_migration_behavior(self):
        """
        Test 4: Test migration behavior with different sched_nr_migrate values.
        VALIDATION: Higher nr_migrate may show different migration patterns.
        """
        self.log.info("\n" + "=" * 70)
        self.log.info("TEST 4: MIGRATION BEHAVIOR Test")
        self.log.info("=" * 70)

        baseline_nr_migrate = self._get_tunable('sched_nr_migrate')

        if baseline_nr_migrate:
            workload_type = self.params.get(
                'workload_type',
                path='/tests/migration_behavior/*',
                default='fork')
            nr_migrate_factor = float(self.params.get(
                'nr_migrate_factor',
                path='/tests/migration_behavior/tunables/*',
                default=2.0))

            self.log.info("\n--- STEP 1: Baseline (Default Tunables) ---")
            self.log.info("  sched_nr_migrate = %s", baseline_nr_migrate)

            self.log.info("\nRunning workload with DEFAULT tunables...")
            baseline_result = self._run_workload(workload_type=workload_type)

            if not baseline_result['success']:
                self.fail("Baseline workload failed")

            self.log.info(
                "\n--- STEP 2: Aggressive Migration (Modified Tunable) ---")
            aggressive_nr_migrate = min(
                128, int(float(baseline_nr_migrate) * nr_migrate_factor))

            self.log.info("Setting aggressive migration:")
            self._log_tunable_change('sched_nr_migrate',
                                     int(baseline_nr_migrate),
                                     aggressive_nr_migrate, unit='tasks')
            self.log.info(
                "  Higher value = more tasks migrated at once = "
                "better load balancing")

            self._set_tunable('sched_nr_migrate', aggressive_nr_migrate)

            time.sleep(2)

            self.log.info("\nRunning migration test workload...")
            result = self._run_workload(workload_type=workload_type)

            if result['success']:
                self.log.info("\n--- VALIDATION: Tunable Impact ---")

                self._compare_and_log_metrics(
                    baseline_result['metrics'], result['metrics'],
                    'cpu_migrations', 'CPU Migrations')

                self.log.info(
                    "sched_nr_migrate controls how many tasks are "
                    "migrated per load balancing operation")
                self.log.info(
                    "Higher value can improve load distribution but "
                    "may increase overhead")
                self.log.info(
                    "✓ Migration behavior test completed successfully")
            else:
                self.fail("Migration behavior test failed")
        else:
            self.cancel("sched_nr_migrate tunable not available")

    def tearDown(self):
        """
        Cleanup: Restore original tunables.
        """
        self._restore_tunables()
        self.log.info("\n" + "=" * 70)
        self.log.info("TEST SUITE COMPLETED")
        self.log.info("=" * 70)
