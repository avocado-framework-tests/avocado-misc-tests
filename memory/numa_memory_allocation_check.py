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
# Author: Pavithra Prakash <pavrampu@linux.ibm.com>
#


import re
from avocado import Test
from avocado.utils import process


class NumaMemoryAllocationCheck(Test):
    """
    Verify that numactl reports full allocated memory.

    This test verifies the bug where on Linux LPAR, the last NUMA node has half
    memory compared to other NUMA nodes (Samsung PoC issue).

    The test compares 'Desired Memory' from lparstat -i with total memory from
    'free -m' to ensure all allocated memory is properly reported by the system.

    :avocado: tags=memory,numa,lpar,powerpc,allocation
    """

    def test_numa_full_memory_allocation(self):
        """
        Verify that numactl reports full allocated memory by comparing
        lparstat 'Desired Memory' with 'free -m' total memory.
        """

        result = process.run('which lparstat', ignore_status=True, shell=True)
        if result.exit_status != 0:
            self.cancel("lparstat command not found - test only applicable on PowerPC LPAR systems")

        self.log.info("Starting NUMA memory allocation verification test...")
        self.log.info("Verifying bug: Last NUMA node has half memory compared to other NUMA nodes")

        try:
            lparstat_output = process.run('lparstat -i', shell=True, sudo=True)
            lparstat_lines = lparstat_output.stdout_text.split('\n')

            desired_memory_mb = None
            for line in lparstat_lines:
                if 'Desired Memory' in line:
                    # Extract memory value - format can be "Desired Memory : XXXXX" (in MB) or "Desired Memory : XXXXX MB"
                    match = re.search(r':\s*(\d+)', line)
                    if match:
                        desired_memory_mb = int(match.group(1))
                        self.log.info("Desired Memory from lparstat: %d MB" % desired_memory_mb)
                        break

            if desired_memory_mb is None:
                self.fail("Could not extract 'Desired Memory' from lparstat -i output")

        except Exception as e:
            self.fail("Failed to get lparstat output: %s" % str(e))

        try:
            free_output = process.run('free -m', shell=True)
            free_lines = free_output.stdout_text.split('\n')

            total_memory_mb = None
            for line in free_lines:
                if line.startswith('Mem:'):

                    parts = line.split()
                    if len(parts) >= 2:
                        total_memory_mb = int(parts[1])
                        self.log.info("Total Memory from free -m: %d MB" % total_memory_mb)
                        break

            if total_memory_mb is None:
                self.fail("Could not extract total memory from 'free -m' output")

        except Exception as e:
            self.fail("Failed to get free output: %s" % str(e))

        # Compare the values with a tolerance of 3% to account for rounding and system overhead
        tolerance_percent = 3.0
        difference = abs(desired_memory_mb - total_memory_mb)
        tolerance_mb = int(desired_memory_mb * tolerance_percent / 100)

        self.log.info("=" * 60)
        self.log.info("Memory Allocation Verification Results:")
        self.log.info("Desired Memory (lparstat): %d MB" % desired_memory_mb)
        self.log.info("Total Memory (free -m): %d MB" % total_memory_mb)
        self.log.info("Difference: %d MB (Tolerance: %d MB)" % (difference, tolerance_mb))
        self.log.info("=" * 60)

        if difference > tolerance_mb:
            self.fail("NUMA memory allocation bug detected! Desired Memory (%d MB) differs from "
                      "Total Memory (%d MB) by %d MB, which exceeds tolerance of %d MB. "
                      "This may indicate the last NUMA node has incorrect memory allocation." %
                      (desired_memory_mb, total_memory_mb, difference, tolerance_mb))
        else:
            self.log.info("SUCCESS: Memory values match within acceptable tolerance")
            self.log.info("NUMA memory allocation is correct - all nodes report proper memory")
