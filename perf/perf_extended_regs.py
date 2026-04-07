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
# Copyright: 2025 IBM.
# Author: Disha Goel <disgoel@linux.ibm.com>

import os
import re
import tempfile
from avocado import Test
from avocado.utils import process, distro, dmesg
from avocado.utils.software_manager.manager import SoftwareManager


class PerfExtendedRegs(Test):
    def setUp(self):
        smg = SoftwareManager()
        dist = distro.detect()
        if dist.name in ['Ubuntu']:
            linux_tools = "linux-tools-" + os.uname()[2]
            pkgs = [linux_tools, 'linux-tools-common']
        elif dist.name in ['debian']:
            pkgs = ['linux-perf']
        elif dist.name in ['centos', 'fedora', 'rhel', 'SuSE']:
            pkgs = ['perf']
        else:
            self.cancel("perf is not supported on %s" % dist.name)

        for pkg in pkgs:
            if not smg.check_installed(pkg) and not smg.install(pkg):
                self.cancel(f"Package {pkg} is missing/could not be installed")

        self.temp_file = tempfile.NamedTemporaryFile().name
        self.raw_file = '/tmp/raw_perf_dump.txt'
        self.platform_regs = self.get_platform_registers()
        self.available_regs = self.get_available_registers()
        dmesg.clear_dmesg()

    def run_cmd(self, cmd):
        if process.system(cmd, sudo=True, shell=True):
            self.fail(f"Failed to execute command {cmd}")

    def get_auxv_platforms(self):
        """Get AT_PLATFORM and AT_BASE_PLATFORM from auxv"""
        result = process.run("LD_SHOW_AUXV=1 /bin/true", sudo=True, shell=True)
        output = result.stdout.decode()

        at_platform, at_base_platform = None, None
        for line in output.splitlines():
            if 'AT_PLATFORM' in line:
                at_platform = line.split(':', 1)[-1].strip()
            elif 'AT_BASE_PLATFORM' in line:
                at_base_platform = line.split(':', 1)[-1].strip()

        if not at_platform or not at_base_platform:
            self.cancel("Could not determine AT_PLATFORM and AT_BASE_PLATFORM \
                        from auxv")

        return at_platform, at_base_platform

    def get_platform_registers(self):
        """Return list of expected registers based on platform"""
        at_platform, at_base_platform = self.get_auxv_platforms()

        COMPAT_REGS = ['r0', 'r1', 'r2', 'r3', 'r4', 'r5', 'r6', 'r7', 'r8',
                       'r9', 'r10', 'r11', 'r12', 'r13', 'r14', 'r15', 'r16',
                       'r17', 'r18', 'r19', 'r20', 'r21', 'r22', 'r23', 'r24',
                       'r25', 'r26', 'r27', 'r28', 'r29', 'r30', 'r31', 'nip',
                       'msr', 'orig_r3', 'ctr', 'link', 'xer', 'ccr', 'softe',
                       'trap', 'dar', 'dsisr', 'sier', 'mmcra']
        P9_REGS = ['mmcr0', 'mmcr1', 'mmcr2', 'pmc1', 'pmc2', 'pmc3', 'pmc4',
                   'pmc5', 'pmc6', 'sdar', 'siar']
        P10_REGS = P9_REGS + ['mmcr3', 'sier2', 'sier3']

        if at_platform == at_base_platform:
            if 'power9' in at_platform.lower():
                COMPAT_REGS += P9_REGS
            elif 'power10' in at_platform.lower():
                COMPAT_REGS += P10_REGS
        return COMPAT_REGS

    def get_available_registers(self):
        """Get the list of available registers reported by perf"""
        result = process.run('perf record -I?', ignore_status=True,
                             sudo=True, shell=True)
        output = result.stderr.decode()

        for line in output.splitlines():
            if 'available registers' in line:
                reg_part = line.split(':', 1)[-1]
                available_regs = set(reg_part.strip().split())
                if available_regs:
                    self.log.info(f"Detected available registers: {available_regs}")
                    return available_regs
        self.fail("No registers detected from 'perf record -I?' output")

    def extract_sampled_registers(self, raw_file):
        """Extract register values from perf report raw dump"""
        found_regs = {}

        if not os.path.exists(raw_file) or os.path.getsize(raw_file) == 0:
            self.fail("Raw file not created or is empty")

        with open(raw_file, 'r', encoding='utf-8', errors='ignore') as file:
            lines = file.readlines()

        collecting = False
        collecting_lines = []
        self.log.debug("=== RAW DUMP start ===")

        for line in lines:
            stripped = line.strip()
            if 'intr regs:' in stripped:
                collecting = True
                collecting_lines.append(stripped)
                continue
            if collecting:
                if stripped.startswith(".... "):
                    collecting_lines.append(stripped)
                    reg_match = re.match(
                        r'\.\.\.\. (\w+)\s+0x([0-9a-fA-F]+)', stripped)
                    if reg_match:
                        found_regs[reg_match.group(1)] = reg_match.group(2)
                else:
                    collecting = False
                    if stripped:
                        collecting_lines.append(stripped)

        for line in collecting_lines:
            self.log.debug(line)
        self.log.debug("=== RAW DUMP END ===")

        if not found_regs:
            self.fail("No registers were found in perf raw dump")

        return found_regs

    def verify_registers_sampled(self, target_regs, use_all=False):
        """Run perf record with selected registers and verify sampling"""
        if use_all:
            self.run_cmd(f'perf record -o {self.temp_file} -I ls')
            expected_regs = self.available_regs
        else:
            regs_str = ",".join(target_regs)
            self.run_cmd(f'perf record -o {self.temp_file} -I{regs_str} ls')
            expected_regs = set(target_regs)

        self.run_cmd(f'perf report -i {self.temp_file} -D > {self.raw_file}')

        found_regs = self.extract_sampled_registers(self.raw_file)
        missing_regs = expected_regs - set(found_regs.keys())
        extra_regs = set(found_regs.keys()) - expected_regs

        if missing_regs:
            self.fail(f"Some registers are missing in perf dump: {missing_regs}")
        if extra_regs:
            self.log.warning(f"Unexpected extra registers found: {extra_regs}")
        self.log.info(f"Registers found: {found_regs}")

    def test_extended_registers(self):
        """Run perf record validations with full and subset of registers"""
        self.verify_registers_sampled(self.available_regs, use_all=True)
        self.verify_registers_sampled(['sier', 'mmcra'])

    def tearDown(self):
        """Clean up temporary files"""
        for file_path in [self.temp_file, self.raw_file]:
            if os.path.exists(file_path):
                os.remove(file_path)
