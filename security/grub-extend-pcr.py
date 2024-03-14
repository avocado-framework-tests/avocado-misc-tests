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
# Copyright: 2023 IBM
# Author: Nageswara R Sastry <rnsastry@linux.vnet.ibm.com>

import os
from avocado import Test
from avocado.utils import distro, genio, process
from avocado.utils.software_manager.manager import SoftwareManager


class GrubExtendPCR(Test):
    """
    Test case for testing grub extend PCR
    :avocado: tags=security,grub,tpm,pcr
    """

    def setUp(self):
        '''
        Install the basic packages
        '''
        # Check for basic utilities
        if 'POWER10' not in genio.read_file("/proc/cpuinfo"):
            self.cancel("Power10 LPAR is required to run this test.")
        device_tree_path = "/proc/device-tree/vdevice/"
        vtpm = [i for i, item in enumerate(os.listdir(device_tree_path)) if item.startswith('vtpm@')]
        if not vtpm:
            self.cancel("vTPM not enabled.")
        smm = SoftwareManager()
        deps = []
        detected_distro = distro.detect()
        if detected_distro.name in ['rhel', 'fedora', 'centos', 'redhat']:
            deps.extend(["tss2"])
        elif 'SuSE' in detected_distro.name:
            deps.extend(['ibmtss'])
        else:
            self.cancel("%s not supported for this test" %
                        detected_distro.name)
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

    def _run_pcrread(self, cmd):
        '''
        Run tsspcrread command, validate output
        Fail case:
        count 1 pcrUpdateCounter 39
        digest length 32
        00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
        00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
        '''
        output = process.system_output(cmd, ignore_status=True).decode().splitlines()
        if '00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00' in output:
            self.fail("%s Failed to give correct output." % cmd)

    def test_tsspcrread_8(self):
        self._run_pcrread("tsspcrread -ha 8")

    def test_tsspcrread_9(self):
        self._run_pcrread("tsspcrread -ha 9")

    def test_tsseventextend(self):
        '''
        Fail case:
        PCR 08: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
        PCR 09: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
        Run tsseventextend command, validate output
        '''
        cmd = "tsseventextend -if /sys/kernel/security/tpm0/binary_bios_measurements -sim -pcrmax 9"
        output = process.system_output(cmd, ignore_status=True).decode().splitlines()
        pcr8_value = pcr9_value = ""
        pcr8_flag = pcr9_flag = True
        for line in output:
            if 'PCR 08' in line:
                pcr8_value = line.split(":")[1]
            if 'PCR 09' in line:
                pcr9_value = line.split(":")[1]
        pcrval = "00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00"
        if pcrval in pcr8_value and pcrval in pcr9_value:
            pcr8_flag = pcr9_flag = False
        if not (pcr8_flag and pcr9_flag):
            self.fail("PCR 8 and/or PCR 9 not having correct values.")

    def test_boot_aggregate(self):
        '''
        Output validation for boot aggregate from two different files
        ascii_runtime_measurements and binary_bios_measurements
        '''
        ascii_file = "/sys/kernel/security/ima/ascii_runtime_measurements"
        binary_bios_file = "/sys/kernel/security/tpm0/binary_bios_measurements"
        if not os.path.exists(ascii_file):
            self.cancel("ascii_runtime_measurements files doesn't exist")
        if not os.path.exists(binary_bios_file):
            self.cancel("binary_bios_file file doesn't exist")
        ascii_output = genio.read_file(ascii_file).splitlines()
        ascii_output = ascii_output[0].split(" ")
        for att in ascii_output:
            if "sha" in att:
                arm_value = att.split(":")[-1]
                break
        cmd1 = "tsseventextend -if {0} -sim -pcrmax 9".format(binary_bios_file)
        tssevent_output = process.system_output(cmd1, ignore_status=True).decode().splitlines()[-1]
        tssevent_value = tssevent_output.split(":")[1].strip().replace(" ", "")
        if arm_value != tssevent_value:
            self.fail("Boot aggregate output not matched from ascii and binary measurements")
