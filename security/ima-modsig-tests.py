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
# Copyright: 2022 IBM.
# Author: Nageswara R Sastry <rnsastry@linux.ibm.com>

from avocado import Test
from avocado.utils import linux_modules, process, distro, genio, linux
from avocado.utils.software_manager.manager import SoftwareManager


class IMAmodsig(Test):
    """
    ima-modsig tests for Linux
    :avocado: tags=privileged,security,ima
    """

    def _check_kernel_config(self, config_option):
        ret = linux_modules.check_kernel_config(config_option)
        if ret == linux_modules.ModuleConfig.NOT_SET:
            self.no_config.append(config_option)

    def setUp(self):
        if distro.detect().version == '8':
            self.cancel("This test not applicable to RHEL8 series")
        # Check for basic utilities
        smm = SoftwareManager()
        for package in ['keyutils']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        self.no_config = []
        # Check the kernel config options
        self._check_kernel_config('CONFIG_IMA_APPRAISE_MODSIG')
        self._check_kernel_config('CONFIG_MODULE_SIG')
        if self.no_config:
            self.cancel("Config options not set are: %s" % self.no_config)
        self.ima_cmd = "keyctl list %:.ima"
        self.builtin_cmd = "keyctl list %:.builtin_trusted_keys"

    def _run_cmd(self, cmd):
        key_list = []
        output = process.system_output(cmd, ignore_status=True,
                                       shell=True).decode("utf-8")
        for line in output.splitlines():
            if 'asymmetric' in line:
                key_list.append(line.split(':')[3])
        return key_list

    def test_ima_signing_key(self):
        """
        Check if ima signing key is available in the keyring
        """
        output_list = self._run_cmd(self.ima_cmd)
        if not output_list:
            self.fail("No keys found in 'ima' keyring.")
        self.log.info("Keys found in 'ima' keyring.")

    def test_builtin_trusted_keys(self):
        """
        Check if builtin trusted keys are available in the keyring
        """
        output_list = self._run_cmd(self.builtin_cmd)
        if not output_list:
            self.fail("No keys found in 'builtin_trusted_keys' keyring.")
        self.log.info("Keys found in 'builtin_trusted_keys' keyring.")

    def test_ima_builtin_trusted_keys(self):
        """
        Check if ima signing key is available in builtin trusted keys
        """
        output1_list = self._run_cmd(self.ima_cmd)
        output2_list = self._run_cmd(self.builtin_cmd)
        found = 0
        for key in output1_list:
            if key in output2_list:
                found += 1
        if not found:
            self.fail("'ima' Signing key not available in"
                      "'builtin_trusted_keys'.")
        self.log.info("'ima' Signing key available in"
                      "'builtin_trusted_keys' keyring.")

    def test_ima_policy_with_secure_boot_enabled(self):
        """
        Check if IMA policy is loaded with secure boot enabled
        """
        # Checking the Guest Secure Boot enabled or not.
        if not linux.is_os_secureboot_enabled():
            self.cancel("Secure boot is not enabled.")
        output = genio.read_file("/sys/kernel/security/ima/policy")
        if not output:
            self.fail("IMA policy not loaded with secure boot enabled.")
        self.log.info("IMA policy loaded with secure boot enabled.")
        if 'appraise' not in output or 'modsig' not in output:
            self.fail(
                "IMA policy not loaded 'appraise' or 'modsig' with secure boot enabled.")
        self.log.info(
            "IMA policy loaded 'appraise' or 'modsig' with secure boot enabled.")

    def test_ima_keyring_integrity(self):
        """
        Check if IMA keyring integrity is compromised
        """
        output = process.system_output(
            self.ima_cmd, ignore_status=True, shell=True).decode("utf-8")
        if "tampered" in output:
            self.fail("IMA keyring integrity is compromised.")
        self.log.info("IMA keyring integrity is not compromised.")
