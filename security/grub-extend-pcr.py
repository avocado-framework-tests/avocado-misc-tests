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
