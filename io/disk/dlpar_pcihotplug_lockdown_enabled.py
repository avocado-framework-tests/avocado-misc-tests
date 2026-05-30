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
# Author: Maram Srimannarayana Murthy <msmurthy@linux.vnet.ibm.com>

"""
DLPAR and PCI Hotplug tests with Kernel Lockdown enabled.

This module provides automated testing for DLPAR (Dynamic Logical
Partitioning) and PCI hotplug operations with kernel security lockdown
enabled in integrity mode.
"""

import os
import re
from typing import Tuple

from avocado import Test
from avocado.utils import linux, process


class DlparPciHotplugLockdownEnabled(Test):
    """
    Test DLPAR and PCI Hotplug operations with kernel lockdown enabled.

    This test ensures kernel lockdown is enabled in integrity mode before
    executing DLPAR and PCI hotplug test suites. It aggregates results
    from both test suites and propagates status based on priority rules.

    :avocado: tags=privileged,security,lockdown,dlpar,pci,hotplug
    """

    # Constants for result tuple indices
    IDX_PASS = 0
    IDX_ERROR = 1
    IDX_FAIL = 2
    IDX_SKIP = 3
    IDX_WARN = 4
    IDX_INTERRUPT = 5
    IDX_CANCEL = 6

    # Regex pattern for parsing Avocado results
    RESULTS_PATTERN = (
        r'RESULTS\s+:\s+PASS\s+(\d+)\s+\|\s+ERROR\s+(\d+)\s+\|\s+'
        r'FAIL\s+(\d+)\s+\|\s+SKIP\s+(\d+)\s+\|\s+WARN\s+(\d+)\s+\|\s+'
        r'INTERRUPT\s+(\d+)\s+\|\s+CANCEL\s+(\d+)'
    )

    def setUp(self):
        """
        Verify and enable kernel lockdown before test execution.

        Checks if kernel lockdown is supported and not already enabled.
        Enables integrity lockdown mode if not active. Cancels test if
        lockdown is already enabled to avoid redundant execution.

        :raises TestCancel: If lockdown unsupported or already enabled
        :raises TestFail: If lockdown enablement fails
        """
        current_mode, is_enabled = linux.is_kernel_lockdown_enabled()

        if current_mode is None:
            self.cancel("Kernel lockdown not supported on this system")

        if is_enabled:
            self.cancel(
                "Kernel lockdown already enabled at system level. "
                "Test cancelled to avoid redundant execution."
            )

        self.log.info(
            "Current lockdown state: mode=%s, enabled=%s",
            current_mode, is_enabled
        )

        if not linux.enable_kernel_lockdown_integrity():
            self.fail("Failed to enable kernel lockdown in integrity mode")

        new_mode, new_enabled = linux.is_kernel_lockdown_enabled()
        self.log.info(
            "Lockdown enabled: mode=%s, enabled=%s", new_mode, new_enabled
        )

        if not new_enabled:
            self.fail("Lockdown enablement verification failed")

    def _get_test_paths(self, test_name: str) -> Tuple[str, str]:
        """
        Construct file paths for test script and YAML configuration.

        :param test_name: Name of the test ('dlpar' or 'pci_hotplug')
        :return: Tuple of (test_path, yaml_path)
        """
        base_dir = os.path.dirname(__file__)

        if test_name == 'dlpar':
            test_path = os.path.join(base_dir, '..', 'pci', 'dlpar.py')
        elif test_name == 'pci_hotplug':
            test_path = os.path.join(base_dir, '..', 'pci', 'pci_hotplug.py')
        else:
            raise ValueError(f"Unknown test name: {test_name}")

        yaml_path = os.path.join(
            base_dir,
            'dlpar_pcihotplug_lockdown_enabled.py.data',
            'dlpar_pcihotplug_lockdown.yaml'
        )

        return test_path, yaml_path

    def _parse_avocado_results(self, output: str) -> Tuple[int, ...]:
        """
        Parse Avocado test results from command output.

        :param output: Avocado command stdout text
        :return: Tuple of (pass, error, fail, skip, warn, interrupt, cancel)
        :raises TestFail: If results cannot be parsed
        """
        if "RESULTS" not in output:
            self.fail("No RESULTS line found in test output")

        results_match = re.search(self.RESULTS_PATTERN, output)
        if not results_match:
            self.fail("Failed to parse test results from output")

        return tuple(int(results_match.group(i)) for i in range(1, 8))

    def _log_test_results(self, test_name: str,
                          results: Tuple[int, ...]) -> None:
        """
        Log detailed test results summary.

        :param test_name: Name of the test suite
        :param results: Tuple of result counts
        """
        self.log.info("=" * 70)
        self.log.info("%s TEST RESULTS SUMMARY:", test_name.upper())
        self.log.info("  PASS: %d", results[self.IDX_PASS])
        self.log.info("  ERROR: %d", results[self.IDX_ERROR])
        self.log.info("  FAIL: %d", results[self.IDX_FAIL])
        self.log.info("  SKIP: %d", results[self.IDX_SKIP])
        self.log.info("  WARN: %d", results[self.IDX_WARN])
        self.log.info("  INTERRUPT: %d", results[self.IDX_INTERRUPT])
        self.log.info("  CANCEL: %d", results[self.IDX_CANCEL])
        self.log.info("=" * 70)

    def _run_test_suite(self, test_name: str,
                        display_name: str) -> Tuple[int, ...]:
        """
        Execute a test suite via subprocess and return results.

        :param test_name: Internal test name ('dlpar' or 'pci_hotplug')
        :param display_name: Display name for logging
        :return: Tuple of (pass, error, fail, skip, warn, interrupt, cancel)
        :raises TestCancel: If test files not found
        :raises TestFail: If results cannot be parsed
        """
        test_path, yaml_path = self._get_test_paths(test_name)

        if not os.path.exists(test_path):
            self.cancel(f"{display_name} test not found: {test_path}")

        if not os.path.exists(yaml_path):
            self.cancel(f"YAML config not found: {yaml_path}")

        cmd = (
            f"avocado run {test_path} "
            f"--mux-yaml {yaml_path} "
            f"--max-parallel-tasks=1 "
            f"--job-results-dir {self.logdir}"
        )

        self.log.info("=" * 70)
        self.log.info("STARTING %s TESTS WITH LOCKDOWN ENABLED",
                      display_name.upper())
        self.log.info("=" * 70)
        self.log.info("Command: %s", cmd)

        result = process.run(cmd, shell=True, ignore_status=True,
                             verbose=True)

        self.log.info("%s Output:\n%s", display_name, result.stdout_text)

        results = self._parse_avocado_results(result.stdout_text)
        self._log_test_results(display_name, results)

        return results

    def _run_dlpar_tests(self) -> Tuple[int, ...]:
        """
        Execute DLPAR test suite with kernel lockdown enabled.

        :return: Tuple of (pass, error, fail, skip, warn, interrupt, cancel)
        """
        return self._run_test_suite('dlpar', 'DLPAR')

    def _run_pci_hotplug_tests(self) -> Tuple[int, ...]:
        """
        Execute PCI hotplug test suite with kernel lockdown enabled.

        :return: Tuple of (pass, error, fail, skip, warn, interrupt, cancel)
        """
        return self._run_test_suite('pci_hotplug', 'PCI Hotplug')

    def _aggregate_results(self, dlpar_results: Tuple[int, ...],
                           pci_results: Tuple[int, ...]) -> Tuple[int, ...]:
        """
        Aggregate results from multiple test suites.

        :param dlpar_results: DLPAR test results tuple
        :param pci_results: PCI hotplug test results tuple
        :return: Aggregated results tuple
        """
        return tuple(dlpar_results[i] + pci_results[i] for i in range(7))

    def _determine_final_status(self, results: Tuple[int, ...]) -> None:
        """
        Determine and apply final test status based on aggregated results.

        Status priority: FAIL > ERROR > INTERRUPT > WARN > CANCEL > PASS
        SKIP results are ignored in status determination.

        :param results: Aggregated results tuple
        :raises TestFail: If any tests failed
        :raises TestError: If any tests errored or were interrupted
        :raises TestCancel: If all tests cancelled with no passes
        """
        total_pass = results[self.IDX_PASS]
        total_error = results[self.IDX_ERROR]
        total_fail = results[self.IDX_FAIL]
        total_warn = results[self.IDX_WARN]
        total_interrupt = results[self.IDX_INTERRUPT]
        total_cancel = results[self.IDX_CANCEL]

        if total_fail > 0:
            self.log.error("FINAL STATUS: FAIL")
            self.fail(
                f"Tests failed: FAIL={total_fail}, ERROR={total_error}, "
                f"INTERRUPT={total_interrupt}"
            )
        elif total_error > 0:
            self.log.error("FINAL STATUS: ERROR")
            self.error(f"Tests encountered errors: ERROR={total_error}")
        elif total_interrupt > 0:
            self.log.error("FINAL STATUS: INTERRUPT")
            self.error(f"Tests interrupted: INTERRUPT={total_interrupt}")
        elif total_warn > 0:
            self.log.warning("FINAL STATUS: WARN")
            self.log.warning(
                "Tests completed with warnings: WARN=%d", total_warn
            )
        elif total_cancel > 0 and total_pass == 0:
            self.log.info("FINAL STATUS: CANCEL")
            self.cancel(f"All tests cancelled: CANCEL={total_cancel}")
        else:
            self.log.info("FINAL STATUS: PASS")
            self.log.info("ALL TESTS COMPLETED SUCCESSFULLY WITH LOCKDOWN")

    def test_dlpar_and_pci_hotplug_with_lockdown(self):
        """
        Execute DLPAR and PCI hotplug tests with kernel lockdown enabled.

        This test method runs both DLPAR and PCI hotplug test suites
        sequentially with kernel lockdown enabled. Results are aggregated
        and final status is determined based on priority rules.

        Status propagation rules:
        - FAIL: If any test fails (highest priority)
        - ERROR: If any test errors (no failures)
        - INTERRUPT: If any test interrupted (no failures/errors)
        - WARN: If any test warns (no failures/errors/interrupts)
        - CANCEL: If all tests cancelled (no passes)
        - PASS: If all tests passed (lowest priority)
        - SKIP: Ignored in status determination

        :raises TestFail: If any subprocess test fails
        :raises TestError: If any subprocess test errors or is interrupted
        :raises TestCancel: If all subprocess tests are cancelled
        """
        self.log.info("\n" + "=" * 70)
        self.log.info("KERNEL LOCKDOWN ENABLED - RUNNING ALL TESTS")
        self.log.info("=" * 70 + "\n")

        # Execute test suites and collect results
        dlpar_results = self._run_dlpar_tests()
        pci_results = self._run_pci_hotplug_tests()

        # Aggregate and log results
        total_results = self._aggregate_results(dlpar_results, pci_results)

        self.log.info("\n" + "=" * 70)
        self.log.info("AGGREGATE TEST RESULTS:")
        self.log.info("  PASS: %d", total_results[self.IDX_PASS])
        self.log.info("  ERROR: %d", total_results[self.IDX_ERROR])
        self.log.info("  FAIL: %d", total_results[self.IDX_FAIL])
        self.log.info("  SKIP: %d", total_results[self.IDX_SKIP])
        self.log.info("  WARN: %d", total_results[self.IDX_WARN])
        self.log.info("  INTERRUPT: %d", total_results[self.IDX_INTERRUPT])
        self.log.info("  CANCEL: %d", total_results[self.IDX_CANCEL])
        self.log.info("=" * 70 + "\n")

        # Determine and apply final status
        self._determine_final_status(total_results)
