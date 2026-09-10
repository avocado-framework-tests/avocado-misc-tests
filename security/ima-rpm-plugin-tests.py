#!/usr/bin/env python
# pylint: disable=invalid-name
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
# Copyright: 2026 IBM
# Author: Krishan Gopal Saraswat <krishang@linux.ibm.com>

"""
IMA RPM plugin tests: verify rpm-plugin-ima stamps IMA signatures on
installed files and evmctl can verify them against the kernel IMA keyring.
"""

import glob
from avocado import Test
from avocado.utils import linux_modules, process
from avocado.utils.software_manager.manager import SoftwareManager


class IMARPMPlugin(Test):
    """
    IMA RPM plugin tests: verify rpm-plugin-ima stamps IMA signatures on
    installed files and evmctl can verify them against the kernel IMA keyring.
    :avocado: tags=privileged,security,ima
    """

    def _check_kernel_config(self, config_option):
        """Append config_option to no_config list if not set in kernel."""
        ret = linux_modules.check_kernel_config(config_option)
        if ret == linux_modules.ModuleConfig.NOT_SET:
            self.no_config.append(config_option)

    def setUp(self):
        """Install dependencies, reinstall test binary, cache xattrs."""
        self.no_config = []
        self._check_kernel_config('CONFIG_IMA')
        self._check_kernel_config('CONFIG_IMA_APPRAISE')
        if self.no_config:
            self.cancel(f"Kernel config options not set: {self.no_config}")

        smm = SoftwareManager()
        for pkg in ['attr', 'rpm-plugin-ima', 'ima-evm-utils', 'keyutils']:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel(f'{pkg} is needed for the test to be run')

        self.test_binary = '/usr/bin/gcc'

        certs = sorted(glob.glob('/usr/share/doc/kernel-keys/*/ima.cer'))
        if not certs:
            self.cancel("No IMA certificate found under "
                        "/usr/share/doc/kernel-keys/*/ima.cer")
        self.ima_cert = certs[-1]

        reinstall_cmd = (
            f"{smm.backend.base_command}reinstall {self.test_binary}"
        )
        if process.system(reinstall_cmd, ignore_status=True):
            self.cancel(
                f"Failed to reinstall package owning {self.test_binary}"
            )

        self.xattrs = process.system_output(
            f"getfattr -m - -d {self.test_binary}",
            ignore_status=True, shell=True).decode()

    def tearDown(self):
        """Clean up: remove any IMA xattr stamped on the test binary."""
        process.system(
            f"setfattr -x security.ima {self.test_binary}",
            ignore_status=True, shell=True
        )

    def test_selinux_xattr_present(self):
        """Verify security.selinux xattr is present on the test binary."""
        if 'security.selinux' not in self.xattrs:
            self.fail(
                f"security.selinux xattr not found on {self.test_binary}"
            )

    def test_ima_xattr_present(self):
        """Verify security.ima xattr is written after reinstall
        with rpm-plugin-ima."""
        if 'security.ima' not in self.xattrs:
            self.fail(f"security.ima xattr not found on {self.test_binary} "
                      "after reinstall with rpm-plugin-ima")

    def test_ima_xattr_value(self):
        """Verify security.ima xattr carries a valid base64-encoded
        DER signature."""
        if 'security.ima=0s' not in self.xattrs:
            self.fail(
                f"security.ima xattr on {self.test_binary} is missing or "
                "not a base64-encoded signature (expected '0s' prefix)"
            )

    def test_ima_signature_verify(self):
        """Verify IMA signature on the test binary using evmctl
        and kernel ima.cer."""
        result = process.run(
            f"evmctl ima_verify -k {self.ima_cert} {self.test_binary}",
            ignore_status=True, shell=True)
        output = result.stdout_text + result.stderr_text
        if result.exit_status or 'verification is OK' not in output:
            self.fail(f"evmctl ima_verify failed for {self.test_binary}: "
                      f"{output.strip()}")

    def test_ima_keyring(self):
        """Verify .ima keyring exists and contains at least one
        asymmetric key."""
        result = process.run("keyctl show %keyring:.ima",
                             ignore_status=True, shell=True)
        output = result.stdout_text
        if result.exit_status or 'keyring: .ima' not in output:
            self.fail(".ima keyring not found.")
        if 'asymmetric' not in output:
            self.fail("No asymmetric key found in .ima keyring.")

    def test_secondary_trusted_keys_keyring(self):
        """Verify .secondary_trusted_keys keyring is populated
        with key hierarchy."""
        result = process.run("keyctl show %keyring:.secondary_trusted_keys",
                             ignore_status=True, shell=True)
        output = result.stdout_text
        if result.exit_status or 'asymmetric' not in output:
            self.fail("No asymmetric keys in .secondary_trusted_keys keyring.")
        if '.builtin_trusted_keys' not in output:
            self.fail(".builtin_trusted_keys not linked under "
                      ".secondary_trusted_keys keyring.")

    def test_dracut_integrity_module_disabled(self):
        """Verify dracut 98integrity module-setup.sh returns 255 (disabled)."""
        dracut_check = '/usr/lib/dracut/modules.d/98integrity/module-setup.sh'
        result = process.run(
            f"grep -q 'return 255' {dracut_check}",
            ignore_status=True, shell=True)
        if result.exit_status:
            self.fail(
                "dracut 98integrity module-setup.sh does not return 255;"
                " integrity module may be unexpectedly enabled in initramfs"
            )
