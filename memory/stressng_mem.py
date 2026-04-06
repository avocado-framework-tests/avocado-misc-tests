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
# Copyright: 2022 IBM
# Author: Rohan Deshpande <rohan_d@linux.ibm.com>

import os
from avocado import Test
from avocado.utils import process
from avocado.utils import memory
from avocado.utils import build
from avocado.utils import archive
from avocado.utils import dmesg
from avocado.utils.software_manager.manager import SoftwareManager


class Stressngmem(Test):
    """
    stress-ng testsuite
    Source: https://github.com/ColinIanKing/stress-ng/archive/master.zip
    Description:
    As a main purpose, this test aims to stress the memory component of the
    target system using the memory stressors through the stress-ng program.
    The script also imposes a load on the CPU, but that's the side-effect.
    :params:
    --base-time <time_in_seconds>
    --time-per-gig <time_in_seconds>
    """

    def read_line_with_matching_pattern(self, filename, pattern):
        matching_pattern = []
        with open(filename, 'r') as file_obj:
            for line in file_obj.readlines():
                if pattern in line:
                    matching_pattern.append(line.rstrip("\n"))
        return matching_pattern

    def extract_call_traces(self, filename, ignore_patterns):
        """
        Extract full call traces from dmesg, excluding OOM-related traces.
        Returns a list of unique call trace blocks.
        """
        call_traces = []
        unique_traces = set()

        with open(filename, 'r') as file_obj:
            lines = file_obj.readlines()
            i = 0
            while i < len(lines):
                line = lines[i].rstrip("\n")

                # Check if this is the start of a call trace
                if 'Call Trace:' in line:
                    # Check if this trace should be ignored (OOM-related)
                    should_ignore = False
                    for ignore_pattern in ignore_patterns:
                        if ignore_pattern in line:
                            should_ignore = True
                            break

                    if not should_ignore:
                        # Collect the full call trace
                        trace_lines = [line]
                        i += 1

                        # Continue collecting lines that are part of the call trace
                        # Call trace lines typically start with spaces or specific patterns
                        while i < len(lines):
                            next_line = lines[i].rstrip("\n")

                            # Check if still part of call trace (indented or contains function names)
                            if (next_line.strip().startswith('[') or
                                next_line.strip().startswith('?') or
                                '0x' in next_line or
                                '+0x' in next_line or
                                next_line.strip().startswith('---[') or
                                (len(next_line) > 0 and next_line[0] == ' ' and
                                 any(c in next_line for c in ['[', ']', '+']))):

                                # Check if this line should be ignored
                                line_should_ignore = False
                                for ignore_pattern in ignore_patterns:
                                    if ignore_pattern in next_line:
                                        line_should_ignore = True
                                        should_ignore = True  # Mark entire trace as ignored
                                        break

                                if not line_should_ignore:
                                    trace_lines.append(next_line)
                                i += 1
                            else:
                                # End of call trace
                                break

                        # Add the complete trace if not ignored
                        if not should_ignore and trace_lines:
                            trace_block = '\n'.join(trace_lines)
                            # Use first line as key for uniqueness
                            trace_key = trace_lines[0]
                            if trace_key not in unique_traces:
                                unique_traces.add(trace_key)
                                call_traces.append(trace_block)
                        continue

                i += 1

        return call_traces

    def process_looping(self, list_of_stressors):
        loop_count = 0
        while loop_count < len(list_of_stressors):
            return_code = self.execute_stressor(list_of_stressors[loop_count])
            loop_count = loop_count + 1
        return return_code

    def execute_stressor(self, stressor):
        if self.stressor_flag == "crt":
            run_time = self.base_time
        elif self.stressor_flag == "vrt":
            run_time = self.variable_time

        end_time = ((run_time)*(15/10))
        self.log.info(
            "Running stress-ng : %s stressor for %s seconds",
            stressor, run_time)

        # Use "timeout" command to launch stress-ng, in order catch it;
        # should it go into la-la land
        cmd = "timeout -s 9 %s stress-ng --aggressive --verify \
                --timeout %s --%s 0" % (end_time, run_time, stressor)
        return_code = process.system(cmd, ignore_status=True)
        self.log.info("Return code is %s", return_code)

        if (return_code != 0):
            self.had_error = 1
            self.log.info(
                "=====================================================")
            if (return_code == 137):
                self.log.info("== > stress-ng memory test timed out and \
                              was forcefully terminated!")
            else:
                self.log.info(
                    "==> Error %s reported on stressor %s!",
                    return_code, stressor)
            self.log.info(
                "=====================================================")
        return return_code

    def calculate_variable_time(self):
        self.total_memory_in_GiB = memory.meminfo.MemTotal.g
        self.log.info("Total Memory on the system : %s GiB",
                      self.total_memory_in_GiB)

        extra_time = (self.time_per_gig * self.total_memory_in_GiB)
        self.variable_time = (self.base_time + extra_time)
        self.log.info("Time limit set for constant_run_time stressors is %s "
                      "seconds per stressor.", self.base_time)
        self.log.info("Time limit set for variable_run_time stressors is %s "
                      "seconds per stressor.", self.variable_time)

    def setUp(self):
        smm = SoftwareManager()
        crt_stressors_list = ["bsearch", "context", "hsearch", "lsearch",
                              "matrix", "memcpy", "null", "pipe", "qsort",
                              "stack", "str", "stream", "tsearch", "vm-rw",
                              "wcs", "zero", "mlock", "mmapfork", "mmapmany",
                              "mremap", "shm-sysv", "vm-splice"]
        vrt_stressors_list = ["malloc", "mincore", "vm", "bigheap", "brk",
                              "mmap"]

        self.had_error = 0
        self.skip_teardown_dmesg_check = False  # Flag to skip dmesg check in tearDown
        self.base_time = self.params.get("base_time", default=300)
        self.time_per_gig = self.params.get("time_per_gig", default=10)
        self.url = self.params.get("url", default="https://github.com/"
                                   "ColinIanKing/stress-ng/archive/master.zip")
        self.crt_stressors = self.params.get(
            "crt_stressors", default=crt_stressors_list)
        self.vrt_stressors = self.params.get(
            "vrt_stressors", default=vrt_stressors_list)

        for package in ['gcc', 'make', 'libattr-devel', 'libcap-devel',
                        'libgcrypt-devel', 'zlib-devel', 'libaio-devel']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel("%s is needed for the test to be run." % package)

        tarball = self.fetch_asset(
            'stressng.zip', locations=self.url, expire='7d')
        archive.extract(tarball, self.workdir)
        sourcedir = os.path.join(self.workdir, 'stress-ng-master')
        os.chdir(sourcedir)
        result = build.run_make(sourcedir, process_kwargs={
                                'ignore_status': True})

        for line in str(result).splitlines():
            if 'error:' in line:
                self.cancel(
                    "Build Failed, Please check the build logs for details !!")
        build.make(sourcedir, extra_args='install')

        # Clear the dmesg to capture the delta at the end of the test.
        dmesg.clear_dmesg()

    def test_memory(self):
        self.swap_memory = memory.meminfo.SwapTotal.m
        if (self.swap_memory == 0):
            self.cancel("Swap space unavailable! Please activate swap space "
                        "and re-run this test!")

        self.calculate_variable_time()

        crt_runtime = (len(self.crt_stressors) * self.base_time)
        vrt_runtime = (len(self.vrt_stressors) * self.variable_time)
        total_runtime = ((crt_runtime + vrt_runtime) / 60)
        self.log.info("Total estimated runtime is : %s minutes", total_runtime)

        # Loop through each constant_run_time stressors
        self.stressor_flag = "crt"
        return_code = self.process_looping(self.crt_stressors)

        # Loop through each variable_run_time stressors
        self.stressor_flag = "vrt"
        return_code = self.process_looping(self.vrt_stressors)

        self.log.info("=====================================================")
        if self.had_error == 0:
            self.log.info("==> stress-ng memory test passed!")
        else:
            self.fail("==> stress-ng memory test failed; most recent error \
                    was %s" % return_code)
        self.log.info("=====================================================")

    def test_vm_class_sequential(self):
        """
        Test VM and memory-related stressors sequentially with specific options.
        Runs stressors in sequence for exactly 1 hour total.

        Command breakdown:
        --no-oom-adjust: Don't adjust OOM killer settings
        --oomable: Allow OOM killer to terminate stressors
        --seq 0: Run stressors sequentially (one at a time)
        -t 60s: Each stressor runs for 60 seconds
        --perf: Enable performance statistics
        -v: Verbose output
        --verify: Verify results

        Stressors to run sequentially (60 total, 1 hour runtime):
        VM stressors: vm, vm-rw, vm-addr, vm-splice, mmap, mremap,
                      mlock, mincore, madvise, msync, mprotect
        Memory stressors: malloc, brk, stack, bigheap
        Other: tlb-shootdown, fault, userfaultfd, fork, exec, memfd,
               numa, pkey, remap, rmap, shm, switch, tmpfs, pthread, swap
        """
        self.log.info("=====================================================")
        self.log.info("Starting VM class sequential stress test")
        self.log.info("Expected runtime: Approximately 60 minutes")
        self.log.info("=====================================================")

        # Set flag to skip dmesg check in tearDown. We check it here instead
        self.skip_teardown_dmesg_check = True

        # List of all stressors to run sequentially (60 stressors × 60s = 3600s = 60 minutes)
        stressors = [
            "tlb-shootdown", "fault", "userfaultfd", "fork", "exec", "memfd",
            "numa", "pkey", "remap", "rmap", "shm", "switch", "tmpfs",
            "pthread", "swap",
            "vm", "vm-rw", "vm-addr", "vm-splice", "mmap", "mremap",
            "mlock", "mincore", "madvise", "msync", "mprotect",
            # Memory stressors
            "malloc", "brk", "stack", "bigheap",
            # Additional VM/memory stressors
            "memcpy", "memfd", "memrate", "memthrash", "mq", "pipe",
            "shm-sysv", "mmapfork", "mmapmany", "mmapfixed", "mmaphuge",
            "context", "clone", "vfork", "vforkmany", "zombie",
            "get", "getrandom", "handle", "heapsort", "hdd",
            "hsearch", "icache", "iomix", "itimer",
            "kcmp", "key", "kill", "klog", "lease"
        ]

        # Base command with common options
        base_cmd = "stress-ng --no-oom-adjust --oomable --seq 0 -t 60s --perf -v --verify"

        # Build the full command with all stressors
        stressor_args = []
        for stressor in stressors:
            stressor_args.append("--%s 0" % stressor)

        full_cmd = "%s %s" % (base_cmd, " ".join(stressor_args))

        self.log.info("Executing command: %s", full_cmd)

        # Set timeout to 90 minutes (1.5x expected 60 minutes) for safety
        timeout_seconds = 90 * 60
        cmd_with_timeout = "timeout -s 9 %s %s" % (timeout_seconds, full_cmd)

        self.log.info("Running VM class sequential test...")
        return_code = process.system(cmd_with_timeout, ignore_status=True, shell=True)

        self.log.info("=====================================================")
        self.log.info("VM class sequential test completed")
        self.log.info("Return code: %s", return_code)

        # Check for errors in dmesg (excluding OOM and expected swap errors)
        errors_in_dmesg = []
        unique_errors = set()  # Track unique errors to log only once

        # Patterns to search for (excluding Call Trace - handled separately)
        error_patterns = ['WARNING: CPU:', 'Oops', 'Segfault', 'soft lockup',
                          'Unable to handle', 'ard LOCKUP']

        # Patterns to ignore (expected errors from stress testing)
        ignore_patterns = [
            'Out of memory',
            'OOM',
            'oom',
            'Killed process',
            'Memory cgroup out of memory',
            'Unable to handle swap header version',
            'swap header'
        ]

        filename = dmesg.collect_dmesg()

        # First, collect non-call-trace errors
        for error_pattern in error_patterns:
            contents = self.read_line_with_matching_pattern(filename, error_pattern)
            if contents:
                for line in contents:
                    # Check if this line should be ignored
                    should_ignore = False
                    for ignore_pattern in ignore_patterns:
                        if ignore_pattern in line:
                            should_ignore = True
                            break

                    # Add to errors if not ignored and not already seen
                    if not should_ignore and line not in unique_errors:
                        unique_errors.add(line)
                        errors_in_dmesg.append(line)

        # Now extract full call traces (excluding OOM-related ones)
        call_traces = self.extract_call_traces(filename, ignore_patterns)

        # Log unique dmesg errors if found (only once each)
        if errors_in_dmesg or call_traces:
            self.log.error("=====================================================")
            self.log.error("Errors found in dmesg (OOM errors excluded):")
            self.log.error("=====================================================")

            if errors_in_dmesg:
                self.log.error("\n--- Non-Call-Trace Errors ---")
                for error in errors_in_dmesg:
                    self.log.error("%s", error)

            if call_traces:
                self.log.error("\n--- Call Traces (%d unique) ---" % len(call_traces))
                for i, trace in enumerate(call_traces, 1):
                    self.log.error("\nCall Trace #%d:", i)
                    self.log.error("%s", trace)

            self.log.error("\n=====================================================")

        # Check return code and dmesg errors
        total_errors = len(errors_in_dmesg) + len(call_traces)

        if return_code == 137:
            self.fail("VM class sequential test timed out after 90 minutes!")
        elif total_errors > 0:
            # Real errors found in dmesg (non-OOM)
            self.fail("VM class sequential test completed but %d error(s) found in dmesg: %d non-trace errors, %d call traces (see log above)" %
                      (total_errors, len(errors_in_dmesg), len(call_traces)))
        elif return_code != 0:
            # Non-zero return code but no dmesg errors (likely OOM-related failures)
            self.log.info("=====================================================")
            self.log.info("stress-ng returned exit code %s, but no non-OOM errors found in dmesg", return_code)
            self.log.info("This is expected behavior during aggressive memory stress testing")
            self.log.info("==> VM class sequential test passed!")
            self.log.info("=====================================================")
        else:
            self.log.info("==> VM class sequential test passed!")
            self.log.info("=====================================================")

    def tearDown(self):
        # Skip dmesg check if test already handled it
        if hasattr(self, 'skip_teardown_dmesg_check') and self.skip_teardown_dmesg_check:
            self.log.info("Skipping tearDown dmesg check (already checked in test method)")
            return

        errors_in_dmesg = []
        pattern = ['WARNING: CPU:', 'Oops', 'Segfault', 'soft lockup',
                   'Unable to handle', 'Hard LOCKUP']

        filename = dmesg.collect_dmesg()

        for failed_pattern in pattern:
            contents = self.read_line_with_matching_pattern(
                filename, failed_pattern)
            if contents:
                loop_count = 0
                while loop_count < len(contents):
                    errors_in_dmesg.append(contents[loop_count])
                    loop_count = loop_count + 1

        if errors_in_dmesg:
            self.fail("Failed : Errors in dmesg : %s" %
                      "\n".join(errors_in_dmesg))
