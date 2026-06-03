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
# Modified by: Samir A Mulani <samir@linux.vnet.ibm.com>
#

import os
import errno
from avocado import Test
from avocado.utils import dmesg
from avocado.utils import archive
from avocado.utils import build
from avocado.utils import process
from avocado.utils.software_manager.manager import SoftwareManager

# Scheduling policy constants
SCHED_OTHER = 0
SCHED_FIFO = 1
SCHED_RR = 2
SCHED_BATCH = 3
SCHED_IDLE = 5
SCHED_DEADLINE = 6


class Stressngcpu(Test):
    """
    stress-ng testsuite
    Source: "https://github.com/ColinIanKing/stress-ng/archive/master.zip"
    Description:
    The purpose of this script is to run CPU stress tests using the
    stress-ng program
    """

    def check_policy_support(self, policy):
        """
        Check if a scheduling policy is supported by this kernel.
        Returns the policy  if supported, False otherwise.
        """
        # Mapping: policy → (priority, label)
        policy_map = {
            SCHED_OTHER:    (0, "other"),
            SCHED_BATCH:    (0, "batch"),
            SCHED_IDLE:     (0, "idle"),
            SCHED_FIFO:     (1, "fifo"),   # needs >0 priority
            SCHED_RR:       (1, "rr"),     # needs >0 priority
            SCHED_DEADLINE: (0, "deadline")  # handled specially
        }

        if policy not in policy_map:
            print(f"Invalid scheduling class: {policy}")
            return False

        priority, label = policy_map[policy]

        try:
            """
            For deadline, os.sched_param is a dummy
            (real params not exposed in Python)
            """
            param = os.sched_param(priority)

            os.sched_setscheduler(0, policy, param)
            return label
        except OSError as e:
            if e.errno == errno.EPERM:
                # Permission denied → policy exists but user isn't root
                return label
            elif e.errno == errno.EINVAL:
                # Policy not supported by kernel
                return False
            else:
                # Other errors (ESRCH, EFAULT, etc.)
                return False

    def read_line_with_matching_pattern(self, filename, pattern):
        matching_pattern = []
        with open(filename, 'r') as file_obj:
            for line in file_obj.readlines():
                if pattern in line:
                    matching_pattern.append(line.rstrip("\n"))
        return matching_pattern

    def setUp(self):
        self.sched_class_payload = []
        smm = SoftwareManager()
        crt_stressors_list = ["bsearch", "context", "cpu", "crypt", "hsearch",
                              "longjmp", "lsearch", "matrix", "qsort", "str",
                              "stream", "tsearch", "vecmath", "wcs"]

        self.runtime = self.params.get("runtime", default=7200)
        self.sched_runtime = self.params.get("sched_runtime", default="100")
        self.test_mode = self.params.get("test_mode", default="saturate")
        self.url = self.params.get("url", default="https://github.com/"
                                   "ColinIanKing/stress-ng/archive/master.zip")
        self.crt_stressors = self.params.get(
            "crt_stressors", default=crt_stressors_list)

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

        policies = [SCHED_OTHER, SCHED_BATCH, SCHED_IDLE, SCHED_FIFO,
                    SCHED_RR, SCHED_DEADLINE]
        for sched_policies in policies:
            sched_pol = self.check_policy_support(sched_policies)
            if sched_pol is not False:
                self.sched_class_payload.append(sched_pol)

        self.log.info("The currently booted Linux OS supports {%s} scheduling \
                policies." % (self.sched_class_payload))

        # Clear the dmesg to capture the delta at the end of the test.
        dmesg.clear_dmesg()

    def stress_sched_class(self, cmd):
        """
        Executes the given stress-ng command and returns its exit status.
        Parameters:
            cmd (str): The full stress-ng command to execute.

        Returns:
            int: The exit status code returned by the stress-ng command.
        """

        return_code = process.system(cmd, ignore_status=True)
        return return_code

    def stress_ng_status_check(self, return_code):
        """
        This function checks the return code of a stress-ng command execution
        to determine whether it succeeded or failed.

        Parameters:
            return_code (int): The exit status returned by the executed
            stress-ng command. A return code of 0 indicates success, while
            any non-zero value indicates failure.
        """

        self.log.info("=====================================================")
        if (return_code == 0):
            self.log.info("==> stress-ng CPU test passed!")
        else:
            if (return_code == 137):
                self.log.info("== > stress-ng CPU test timed out and was \
                        forcefully terminated!")
            else:
                self.log.info(
                    "==> stress-ng CPU test failed with result %s"
                    % (return_code))
        self.log.info("=====================================================")

    def test_cpu(self):
        """
        This function is responsible for stressing the system using a
        combination of stress-ng stressor threads, based on the specified
        test mode.

        The stressors are selected from a predefined list (e.g., "bsearch",
        "context","cpu", "crypt", "hsearch", "longjmp", "lsearch", "matrix",
        "qsort", "str","stream", "tsearch", "vecmath", "wcs") and are used
        to build a composite stress-ng command.

        The intensity and nature of the stress is controlled by the
        'test_mode' parameter (e.g., 'saturate', 'overload',
        'underutilize'), which determines how many worker threads to spawn
        per stressor.
        """

        num_cpus = os.cpu_count()
        stress_ng_threads = 0
        if self.test_mode == "saturate":
            stress_ng_threads = num_cpus
        elif self.test_mode == "overload":
            stress_ng_threads = num_cpus * 2
        elif self.test_mode == "underutilize":
            stress_ng_threads = num_cpus / 2

        cmd = ""

        if self.sched_class_payload:
            for sched_class in self.sched_class_payload:
                cmd = "stress-ng  --cpu %s --sched %s  --timeout %s \
                        --aggressive  --verify \
                        --metrics-brief --tz\
                        --times" % (stress_ng_threads, sched_class,
                                    self.sched_runtime)

                return_code = process.system(cmd, ignore_status=True)
                self.log.info("Return code is %s", return_code)
                self.stress_ng_status_check(return_code)

        cmd = "stress-ng --aggressive --verify \
                --timeout %s --metrics-brief \
                --tz --times " % (self.runtime)

        loop_count = 0
        while (loop_count < len(self.crt_stressors)):
            cmd += "--%s 0 " % (self.crt_stressors[loop_count])
            loop_count = loop_count + 1

        return_code = process.system(cmd, ignore_status=True)
        self.log.info("Return code is %s", return_code)
        self.stress_ng_status_check(return_code)

    def tearDown(self):
        """
        This function captures the output of `dmesg` and scans it for known
        error patterns in the system logs.
        """

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
