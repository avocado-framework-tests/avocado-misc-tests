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
# Copyright: 2025 IBM
# Author: Tejas Manhas <Tejas.Manhas1@ibm.com>
import re
from avocado import Test
from avocado.utils import distro, process, genio
from avocado.utils.software_manager.manager import SoftwareManager


class datatype_profiling(Test):
    """
    This is a test class for datatype profiling that checks datatype offset etc.
    """

    def setUp(self):
        '''
        Install the basic packages to support perf
        '''
        detected_distro = distro.detect()
        if 'ppc64' not in detected_distro.arch:
            self.cancel('This test is not supported on %s architecture'
                        % detected_distro.arch)
        if 'PowerNV' in genio.read_file('/proc/cpuinfo'):
            self.cancel('This test is only supported on LPAR')
        process.run("dmesg -C")
        self.check_mem_event_availability()
        self.check_dependencies()

    def run_cmd(self, cmd):
        """
        run command on SUT as root
        """

        result = process.run(cmd, shell=True, ignore_status=True)
        output = result.stdout_text + result.stderr_text
        return output

    def check_mem_event_availability(self):
        try:
            output = self.run_cmd(
                "perf mem record -e list")
        except Exception as e:
            self.log.info(f"Command failed: {e}")
            return False
        if not re.search(r"ldlat-loads\s*:\s*available", output):
            self.cancel("Required memory event 'ldlat-loads' not available")

        if not re.search(r"ldlat-stores\s*:\s*available", output):
            self.cancel("Required memory event 'ldlat-stores' not available")

    def check_dependencies(self):
        """
        Check if required debug packages for current kernel are installed
        and perf events are available.
        """

        detected_distro = distro.detect()
        is_rhel = False
        is_sles = False
        if "rhel" in detected_distro.name.lower():
            is_rhel = True
        if "suse" in detected_distro.name.lower():
            is_sles = True
        # Define base package names (without versions)
        base_packages = ["perf"]

        # Add debuginfo names based on distro
        if is_rhel:
            base_packages += [
                "kernel-tools-libs",
                "kernel-tools",
                "kernel-headers",
                "kernel-devel",
                "kernel",
                "kernel-core",
                "kernel-modules",
                "kernel-modules-extra",
                "kernel-modules-core",
                "kernel-debuginfo",
                "kernel-debug-debuginfo",
                "kernel-debuginfo-common-ppc64le"
            ]
        elif is_sles:
            base_packages += [
                "kernel-default-debuginfo",
                "kernel-debug-debuginfo",
                "kernel-default-devel",
                "kernel-devel",
                "kernel-default"
            ]
        else:
            self.cancel("Unsupported Linux distribution")

        smm = SoftwareManager()
        for package in base_packages:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

    def check_perf_report_headers(self, cmd):
        """
        Checks for expected headers in perf report output.
        """
        output = self.run_cmd(cmd)
        expected_headers = ["Symbol", "Data Type", "Data Type Offset"]
        for header in expected_headers:
            if header not in output:
                self.fail(
                    f"Missing expected header '{header}' in perf report output")

    def check_perf_annotate_headers(self, cmd, check_insn_stat=False):
        """
        Checks for expected headers in perf annotate output.
        """
        self.run_cmd(f"{cmd} > out")
        output = self.run_cmd("cat out")

        if check_insn_stat:
            # First check for Name/opcode, Good, Bad headers
            expected_insn_headers = ["Name/opcode", "Good", "Bad"]
            for header in expected_insn_headers:
                if header not in output:
                    self.fail(
                        f"Missing expected header '{header}' in perf annotate insn stat output")

        # Now check for 'offset' and 'size' in each Annotate type block
        sections = output.split("Annotate type:")
        for section in sections[1:]:
            if "offset" not in section or "size" not in section:
                self.fail(
                    "Missing 'offset' or 'size' header in perf annotate output")

    def test_datatype_profiling(self):
        """
        Test to verify perf data type profiling feature.
        Steps:
        1. Verify perf report headers.
        2. Verify perf annotate data type headers.
        3. Verify perf annotate instruction stats headers.
        Repeat above for:
            a. perf mem record -a sleep 10
            b. perf record -a -e mem-loads sleep 5
            c. perf record -c 1 -e mem-stores sleep 5
        """

        record_cmds = [
            "perf mem record -a -o /tmp/perf_output.data sleep 10",
            "perf record -a -e mem-loads -o /tmp/perf_output.data sleep 5",
            "perf record -c 1 -e mem-stores -o /tmp/perf_output.data sleep 5"
        ]

        for cmd in record_cmds:
            self.run_cmd(cmd)

            self.check_perf_report_headers(
                "perf report -i /tmp/perf_output.data -s symbol,type,typeoff")
            self.check_perf_annotate_headers(
                "perf annotate -i /tmp/perf_output.data --data-type")
            self.check_perf_annotate_headers(
                "perf annotate -i /tmp/perf_output.data --data-type --insn-stat",
                check_insn_stat=True)

    def tearDown(self):
        """
        tear down function to clear dmesg and data files.
        """
        process.run("dmesg -T")
        self.run_cmd("rm -rf /tmp/perf_output.data")
        self.run_cmd("rm -rf out")
