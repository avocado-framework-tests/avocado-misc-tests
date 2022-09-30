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
from avocado.utils import linux_modules, process
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

    def _run_cmd(self, cmd):
        key_list = []
        output = process.system_output(cmd, ignore_status=True,
                                       shell=True).decode("utf-8")
        for line in output.splitlines():
            if 'asymmetric' in line:
                key_list.append(line.split(':')[3])
        return key_list

    def test(self):
        output1_list = self._run_cmd("keyctl list %:.ima")
        output2_list = self._run_cmd("keyctl list %:.builtin_trusted_keys")
        found = 0
        for key in output1_list:
            if key in output2_list:
                found += 1
        if not found:
            self.fail("Signing key not available in"
                      "'ima' and 'builtin_trusted_keys'.")
