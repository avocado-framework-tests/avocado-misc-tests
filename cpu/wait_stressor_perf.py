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
# Author: Samir M <samir@linux.ibm.com>
#
# Test Description:
# This test runs wait_stressor.c to generate load balancing stress
# and captures perf.data to analyze scheduler functions:
# - enqueue_task_fair
# - newidle_balance
# Expected: Both functions should consume less than 2.0% of cycles
# Note: This test is only applicable for SUSE Linux distributions

import os
import re

from avocado import Test
from avocado.utils import process, distro
from avocado.utils.software_manager.manager import SoftwareManager


class WaitStressorPerf(Test):
    """
    Test load balancing with wait_stressor and perf monitoring.
    Validates that enqueue_task_fair and newidle_balance consume
    less than 2.0% of CPU cycles.

    Note: This test is only applicable for SUSE Linux distributions.

    :avocado: tags=cpu,scheduler,perf,loadbalancing,suse
    """

    def setUp(self):
        """
        Setup test environment and dependencies
        Note: This test is only applicable for SUSE Linux distributions
        """
        distro_name = distro.detect().name
        if 'SuSE' not in distro_name and 'SUSE' not in distro_name:
            self.cancel(
                "This test is only applicable for SUSE Linux distributions")

        sm = SoftwareManager()
        deps = ['gcc', 'make', 'perf']
        for package in deps:
            if not sm.check_installed(package) and not sm.install(package):
                self.cancel("%s is needed for the test to be run" % package)

        self.duration = self.params.get('duration', default=30)
        self.threshold = self.params.get('threshold', default=2.0)

        source_file = os.path.join(os.path.dirname(__file__),
                                   'wait_stressor_perf.py.data',
                                   'wait_stressor.c')
        self.binary = os.path.join(self.teststmpdir, 'wait_stressor')
        self.perf_data = os.path.join(self.teststmpdir, 'perf.data')

        self.log.info("Compiling wait_stressor.c")
        compile_cmd = f"gcc -o {self.binary} {source_file} -Wall"
        result = process.run(compile_cmd, shell=True, ignore_status=True)
        if result.exit_status != 0:
            self.fail(
                f"Failed to compile wait_stressor.c: {result.stderr.decode()}")

    def test(self):
        """
        Main test execution:
        1. Start wait_stressor in background
        2. Run perf record to capture data
        3. Analyze perf report for target functions
        4. Validate cycle consumption is below threshold
        """
        self.log.info(f"Starting wait_stressor for {self.duration} seconds")
        stressor_cmd = f"timeout {self.duration} {self.binary}"
        stressor_process = process.SubProcess(stressor_cmd, shell=True)
        stressor_process.start()

        import time
        time.sleep(2)

        self.log.info("Recording perf data")
        perf_record_cmd = (
            f"perf record -a -g "
            f"-o {self.perf_data} -- sleep {self.duration - 3}"
        )

        try:
            result = process.run(
                perf_record_cmd, shell=True, ignore_status=True)
            if result.exit_status != 0:
                self.log.warning(
                    f"perf record warning: {result.stderr.decode()}")
        except Exception as e:
            self.log.error(f"perf record failed: {str(e)}")
            stressor_process.terminate()
            self.fail("Failed to record perf data")

        stressor_process.wait()

        self.log.info("Analyzing perf data for target scheduler functions")
        target_functions = ['enqueue_task_fair', 'newidle_balance']
        results = {}

        for func in target_functions:
            perf_report_cmd = (
                f"perf report -i {self.perf_data} --stdio --no-children "
                f"--symbol-filter={func} 2>/dev/null | head -20"
            )

            try:
                result = process.run(
                    perf_report_cmd, shell=True, ignore_status=True)
                if result.exit_status == 0:
                    output = result.stdout.decode()
                    self.log.debug(f"perf report output for {func}:\n{output}")

                    # Parse the output for this function
                    for line in output.splitlines():
                        if func in line and '%' in line:
                            # Match pattern like: "0.09%  swapper,
                            # [kernel.vmlinux]  [k] enqueue_task_fair"
                            match = re.match(r'\s*([\d.]+)%', line)
                            if match:
                                percentage = float(match.group(1))
                                results[func] = percentage
                                self.log.info(f"Found {func}: {percentage}%")
                                break
            except Exception as e:
                self.log.warning(
                    f"Failed to get perf report for {func}: {str(e)}")

        for func in target_functions:
            if func not in results:
                self.log.info(f"{func}: Not detected (< 0.01% or not called)")
                results[func] = 0.0

        self.log.info("=" * 60)
        self.log.info("RESULTS:")
        self.log.info("=" * 60)

        target_functions = ['enqueue_task_fair', 'newidle_balance']
        failures = []

        for func in target_functions:
            if func in results:
                percentage = results[func]
                status = "PASS" if percentage < self.threshold else "FAIL"
                self.log.info(f"{func}: {percentage}% [{status}]")

                if percentage >= self.threshold:
                    failures.append(
                        f"{func} consumed {percentage}% (threshold:\
                        {self.threshold}%)"
                    )
            else:
                self.log.warning(f"{func}: Not found in perf report")
                # Not finding the function might be acceptable if,
                # load is very low
                self.log.info(f"{func}: 0.00% [PASS - not detected]")

        self.log.info("=" * 60)
        self.log.info(f"Threshold: < {self.threshold}%")
        self.log.info("=" * 60)

        if failures:
            self.fail(
                f"Load balancing functions exceeded threshold:\n" +
                "\n".join(failures)
            )
        else:
            self.log.info("SUCCESS: All functions below threshold")

    def tearDown(self):
        """
        Cleanup test artifacts
        """
        # Clean up perf.data if it exists
        if hasattr(self, 'perf_data') and os.path.exists(self.perf_data):
            try:
                os.remove(self.perf_data)
            except Exception as e:
                self.log.warning(f"Failed to remove perf.data: {str(e)}")
