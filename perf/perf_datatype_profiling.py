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
import os
import re
from avocado import Test
from avocado.utils import distro, process, genio, cpu
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils.ssh import Session


class datatype_profiling(Test):
    """
    This is a test class for datatype profiling that checks datatype offset etc.
    """
    interface_directory = '/sys/devices/hv_gpci/interface'

    def setUp(self):
        '''
        Install the basic packages to support perf
        '''
        smm = SoftwareManager()
        detected_distro = distro.detect()
        if 'ppc64' not in detected_distro.arch:
            self.cancel('This test is not supported on %s architecture'
                        % detected_distro.arch)
        if 'PowerNV' in genio.read_file('/proc/cpuinfo'):
            self.cancel('This test is only supported on LPAR')
        process.run("dmesg -C")
        self.check_mem_event_availability()

    def run_cmd(self, cmd, user=None):
        """
        run command on SUT as root and non root user
        """
        if user == 'test':  # i.e., we are running as non root
            result = process.run(
                f"su - test -c '{cmd}'", shell=True, ignore_status=True)
        else:
            result = process.run(cmd, shell=True, ignore_status=True)
        output = result.stdout_text + result.stderr_text
        return output

    def check_mem_event_availability(self):
        try:
            output = self.run_cmd("perf mem record -e list", shell=True, text=True)
        except Exception as e:
            print(f"Command failed: {e}")
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

        try:
            kernel_version = self.run_cmd("uname -r").strip()
        except Exception:
            self.cancel("Failed to fetch kernel version using uname -r")
        try:
            distro = self.run_cmd("cat /etc/os-release").lower()
        except Exception:
            self.cancel("Could not determine Linux distribution")

        is_sles = "sles" in distro or "suse" in distro
        is_rhel = "rhel" in distro or "red hat" in distro

        # Define base package names (without versions)
        base_packages = [

        ]

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

        # Try versioned first, then fallback to unversioned
        missing = []
        for pkg in base_packages:
            versioned_pkg = f"{pkg}-{kernel_version}.ppc64le"
            unversioned_found = False

            # Try versioned package
            if self.run_cmd(f"rpm -q {versioned_pkg}").strip().endswith("is not installed"):
                # Try unversioned
                if self.run_cmd(f"rpm -q {pkg}").strip().endswith("is not installed"):
                    missing.append(pkg)

        if missing:
            self.cancel(f"Missing required packages: {', '.join(missing)}")


    def check_perf_report_headers(self, cmd):
        """
        Checks for expected headers in perf report output.
        """
        output = self.run_cmd(cmd)
        expected_headers = ["Symbol", "Data Type", "Data Type Offset"]
        for header in expected_headers:
            if header not in output:
                self.fail(f"Missing expected header '{header}' in perf report output")


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
                    self.fail(f"Missing expected header '{header}' in perf annotate insn stat output")

        # Now check for 'offset' and 'size' in each Annotate type block
        sections = output.split("Annotate type:")
        for section in sections[1:]:
            if "offset" not in section or "size" not in section:
                self.fail("Missing 'offset' or 'size' header in perf annotate output")


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

        self.check_dependencies()

        record_cmds = [
            "perf mem record -a sleep 10 > /tmp/perf_output.data",
            "perf record -a -e mem-loads sleep 5 > /tmp/perf_output.data",
            "perf record -c 1 -e mem-stores sleep 5 > /tmp/perf_output.data"
        ]

        for cmd in record_cmds:
            self.run_cmd(cmd)

            self.check_perf_report_headers("perf report -s symbol,type,typeoff")
            self.check_perf_annotate_headers( "perf annotate --data-type")
            self.check_perf_annotate_headers( "perf annotate --data-type --insn-stat", check_insn_stat=True)

    def tearDown(self):
        """
        tear down function to remove non root user.
        """
        process.run("dmesg -T")