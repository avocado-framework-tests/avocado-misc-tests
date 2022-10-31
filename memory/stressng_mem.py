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

    def tearDown(self):
        errors_in_dmesg = []
        pattern = ['WARNING: CPU:', 'Oops', 'Segfault', 'soft lockup',
                   'Unable to handle', 'ard LOCKUP']

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
