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
from avocado.utils import linux_modules


class KerelHardConfig(Test):
    """
    Kernel Hardening config options for Linux
    :avocado: tags=privileged,security,hardening
    """
    def _check_kernel_config(self, config_option):
        ret = linux_modules.check_kernel_config(config_option)
        if ret == linux_modules.ModuleConfig.NOT_SET:
            self.no_config.append(config_option)

    def setUp(self):
        self.no_config = []
        # Check the kernel config options

    def test(self):
        config_list = ['CONFIG_ARCH_HAS_STRICT_KERNEL_RWX',
                       'CONFIG_STRICT_KERNEL_RWX', 'CONFIG_STRICT_MODULE_RWX',
                       'CONFIG_ARCH_HAS_STRICT_MODULE_RWX']
        for config in config_list:
            self._check_kernel_config(config)
        if self.no_config:
            self.fail("Config options not set are: %s" % self.no_config)
