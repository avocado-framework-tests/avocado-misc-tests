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
# Copyright: 2021 IBM.
# Author: Nageswara R Sastry <rnsastry@linux.ibm.com>

import os
from avocado import Test
from avocado.utils import dmesg, genio, linux_modules


class vTPM(Test):
    """
    vTPM tests for Linux
    :avocado: tags=privileged,security,tpm
    """
    def setUp(self):
        device_tree_path = "/proc/device-tree/vdevice/"
        d_list = os.listdir(device_tree_path)
        vtpm = [i for i, item in enumerate(d_list) if item.startswith('vtpm@')]
        if not vtpm:
            self.cancel("vTPM not enabled.")
        vtpm_file = "%s%s" % (device_tree_path, d_list[vtpm[0]])
        compatible_file = "%s/compatible" % vtpm_file
        if os.path.exists(compatible_file):
            self.cvalue = genio.read_file(compatible_file).rstrip('\t\r\n\0')
            self.cvalue = self.cvalue.split(",")[1]
            self.log.info("TPM version is %s" % self.cvalue)
        else:
            self.fail("Can't determine version of TPM")
        self.no_config = []
        self.no_device = []

    def test_TPM_register(self):
        output = dmesg.collect_errors_dmesg('tpm_ibmvtpm 30000003: CRQ initialization completed')
        if not len(output):
            self.skip("TPM initialized message not found, dmesg got cleared(?)")
        else:
            self.log.info("TPM intialized successfully.")

    def _check_kernel_config(self, config_option):
        ret = linux_modules.check_kernel_config(config_option)
        if ret == linux_modules.ModuleConfig.NOT_SET:
            self.no_config.append(config_option)

    def test_TPM_config(self):
        self._check_kernel_config('CONFIG_TCG_TPM')
        self._check_kernel_config('CONFIG_HW_RANDOM_TPM')
        self._check_kernel_config('CONFIG_TCG_IBMVTPM')
        if self.no_config:
            self.fail("Config options not set are: %s" % self.no_config)

    def _check_tpm_file(self, device):
        if not os.path.exists(device):
            self.no_device.append(device)
            return False
        return True

    def test_devices(self):
        tpm = self._check_tpm_file("/dev/tpm0")
        tpmrm = self._check_tpm_file("/dev/tpmrm0")
        if self.cvalue == "vtpm20":
            if not (tpm and tpmrm):
                self.fail("TPM2.0 expects two devices, not found %s"
                          % self.no_device)
        elif self.cvalue == "vtpm":
            if not tpm:
                self.fail("TPM1.2 expects '/dev/tpm0', the same was not found")

    def test_tpm_measurement(self):
        fn = "/sys/kernel/security/tpm0/binary_bios_measurements"
        if not os.path.exists(fn):
            self.fail("TPM binary bios measurements file not found.")

    def test_proc_devices(self):
        tpm_found = False
        if "tpm" in genio.read_file('/proc/devices').rstrip('\t\r\n\0'):
            tpm_found = True
        if not tpm_found:
            self.fail("TPM not found in '/proc/devices'")
