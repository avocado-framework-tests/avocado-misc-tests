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
import pwd
import grp
from avocado import Test
from avocado.utils import dmesg, genio, linux_modules, distro


class vTPM(Test):
    """
    vTPM tests for Linux
    :avocado: tags=privileged,security,tpm
    """

    def setUp(self):
        detected_distro = distro.detect()
        device_tree_path = "/proc/device-tree/vdevice/"
        d_list = os.listdir(device_tree_path)
        vtpm = [i for i, item in enumerate(d_list) if item.startswith('vtpm@')]
        if not vtpm:
            self.cancel("vTPM not enabled.")
        self.vtpm_dev = d_list[vtpm[0]]
        vtpm_file = "%s%s" % (device_tree_path, self.vtpm_dev)
        compatible_file = "%s/compatible" % vtpm_file
        if os.path.exists(compatible_file):
            cvalue = genio.read_file(compatible_file).rstrip('\t\r\n\0')
            try:
                cvalue = cvalue.split(",")[1]
            except IndexError:
                self.fail("Malformed compatible file. Unable to determine TPM"
                          " version.")
            self.dev_details = {}
            if cvalue == "vtpm20":
                self.dev_details = {'/dev/tpm0': ['tss', 'root', 0o660],
                                    '/dev/tpmrm0': ['tss', 'tss', 0o660]}
            if detected_distro.name == "rhel" and \
               int(detected_distro.version) >= 10:
                self.dev_details = {'/dev/tpm0': ['tss', 'root', 0o660],
                                    '/dev/tpmrm0': ['root', 'tss', 0o660]}
            if cvalue == "vtpm":
                self.dev_details = {'/dev/tpm0': ['root', 'root', 0o600]}

            self.log.info("Detected vTPM device: %s" % self.vtpm_dev)
            self.log.info("Compatible file content: %s" % cvalue)
            self.log.info("Device nodes: %s" % self.dev_details.keys())
        else:
            self.fail("File 'compatible' not found, Can't determine"
                      "  version of TPM")

    def test_tpm_register(self):
        message = "tpm_ibmvtpm %s: CRQ initialization completed" % self.vtpm_dev
        output = dmesg.collect_errors_dmesg(message)
        if not len(output):
            self.skip("TPM initialized message not found, dmesg got cleared(?)")
        else:
            self.log.info("TPM initialized successfully.")

    def _check_kernel_config(self, config_option):
        ret = linux_modules.check_kernel_config(config_option)
        if ret == linux_modules.ModuleConfig.NOT_SET:
            self.no_config.append(config_option)

    def test_tpm_kconfig(self):
        no_config = []
        for kconfig in ['CONFIG_TCG_TPM', 'CONFIG_HW_RANDOM_TPM',
                        'CONFIG_TCG_IBMVTPM']:
            ret = linux_modules.check_kernel_config(kconfig)
            if ret == linux_modules.ModuleConfig.NOT_SET:
                no_config.append(kconfig)
        if no_config:
            self.fail("Config options not set are: %s" % no_config)

    def test_present_devices(self):
        no_device = []
        for device in self.dev_details.keys():
            if not os.path.exists(device):
                no_device.append(device)
        if no_device:
            self.fail("Device node(s) not found: %s" % no_device)

    def test_tpm_measurement(self):
        fn = "/sys/kernel/security/tpm0/binary_bios_measurements"
        if not os.path.exists(fn):
            self.fail("TPM binary bios measurements file not found.")
        # Following file contents can't read with genio.read API
        # contents of this file should be decoded with - Windows-1254
        contents = []
        with open(fn, "r", encoding="Windows-1254", errors='ignore') as f_obj:
            contents = [line.rstrip("\n") for line in f_obj.readlines()]
        if not contents:
            self.fail("TPM event log is empty")

    def test_proc_devices(self):
        tpm_found = False
        if "tpm" in genio.read_file('/proc/devices').rstrip('\t\r\n\0'):
            tpm_found = True
        if not tpm_found:
            self.fail("TPM not found in '/proc/devices'")

    def _check_file_mode(self, file_path, e_user, e_group, e_mode):
        # Get file stat
        file_stat = os.stat(file_path)

        # Get user name, group name and check for match
        user_name_match = (pwd.getpwuid(file_stat.st_uid).pw_name) == e_user
        group_name_match = (grp.getgrgid(file_stat.st_gid).gr_name) == e_group

        # Check if file mode matches expected mode
        is_mode_match = (file_stat.st_mode & 0o777) == e_mode

        return user_name_match, group_name_match, is_mode_match

    def test_stat_user_group(self):
        for device, details in self.dev_details.items():
            user, group, perm = details
            um, gm, mm = self._check_file_mode(device, user, group, perm)
            fail_case = []
            if not um:
                fail_case.append(user)
            if not gm:
                fail_case.append(group)
            if not mm:
                fail_case.append(perm)
            if fail_case:
                self.fail("Not matching value: %s for Device: %s"
                          % (fail_case, device))
