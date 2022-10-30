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
from avocado.utils import dmesg
from avocado.utils import archive
from avocado.utils import build
from avocado.utils import process
from avocado.utils.software_manager.manager import SoftwareManager


class Stressngcpu(Test):
    """
    stress-ng testsuite

    Source: "https://github.com/ColinIanKing/stress-ng/archive/master.zip"

    Description:
    The purpose of this script is to run CPU stress tests using the
    stress-ng program

    """

    def read_line_with_matching_pattern(self, filename, pattern):
        matching_pattern = []
        with open(filename, 'r') as file_obj:
            for line in file_obj.readlines():
                if pattern in line:
                    matching_pattern.append(line.rstrip("\n"))
        return matching_pattern

    def setUp(self):
        smm = SoftwareManager()
        crt_stressors_list = ["bsearch", "context", "cpu", "crypt", "hsearch",
                              "longjmp", "lsearch", "matrix", "qsort", "str",
                              "stream", "tsearch", "vecmath", "wcs"]

        self.runtime = self.params.get("runtime", default=7200)
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

        # Clear the dmesg to capture the delta at the end of the test.
        dmesg.clear_dmesg()

    def test_cpu(self):
        # Add 10% to runtime; will forcefully terminate if stress-ng
        # fails to return in that time.
        end_time = ((self.runtime)*(11/10))

        cmd = "timeout -s 9 %s stress-ng --aggressive --verify --timeout %s" \
            " --metrics-brief --tz --times " % (end_time, self.runtime)

        loop_count = 0
        while (loop_count < len(self.crt_stressors)):
            cmd += "--%s 0 " % (self.crt_stressors[loop_count])
            loop_count = loop_count + 1

        return_code = process.system(cmd, ignore_status=True)
        self.log.info("Return code is %s", return_code)

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
