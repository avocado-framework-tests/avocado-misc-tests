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
from avocado.utils import linux_modules, distro


class KerelHardConfig(Test):
    """
    Kernel Hardening config options for Linux
    :avocado: tags=privileged,security,hardening
    """

    def _check_kernel_config(self, config_list, fail_msg):
        for config_option in config_list:
            ret = linux_modules.check_kernel_config(config_option)
            if ret == linux_modules.ModuleConfig.NOT_SET:
                self.no_config.append(config_option)
        if self.no_config:
            self.fail("%s: %s" % (fail_msg, self.no_config))

    def setUp(self):
        if distro.detect().version == '8' and distro.detect().name == "rhel":
            self.cancel("This test not applicable to RHEL8 series")
        self.no_config = []
        # Check the kernel config options

    def test_strict_read_write_execute(self):
        config_list = ['CONFIG_ARCH_HAS_STRICT_KERNEL_RWX',
                       'CONFIG_STRICT_KERNEL_RWX', 'CONFIG_STRICT_MODULE_RWX',
                       'CONFIG_ARCH_HAS_STRICT_MODULE_RWX']
        self._check_kernel_config(config_list,
                                  "Strict RWX kernel config options not set")
        self.log.info("Strict RWX kernel config options are set properly")

    def test_kernel_stack_protection(self):
        config_list = ['CONFIG_STACKPROTECTOR', 'CONFIG_STACKPROTECTOR_STRONG']
        self._check_kernel_config(config_list,
                                  "Kernel stack protection options not set")
        self.log.info("Kernel stack protection options are set properly")

    def test_aslr_enabled(self):
        if distro.detect().version == '9' and distro.detect().name == "rhel":
            self.cancel("This test not applicable to RHEL9 series")
        config_list = ['CONFIG_RANDOMIZE_KSTACK_OFFSET',
                       'CONFIG_RANDOMIZE_KSTACK_OFFSET_DEFAULT']
        self._check_kernel_config(config_list,
                                  "ASLR-related config options not set")
        self.log.info("ASLR-related config options are set properly")

    def test_kernel_heap_hardening(self):
        config_list = ['CONFIG_SLUB_DEBUG', 'CONFIG_SLAB_FREELIST_HARDENED']
        self._check_kernel_config(config_list,
                                  "Kernel heap hardening options not set")
        self.log.info("Kernel heap hardening options are set properly")

    def test_kernel_module_signing(self):
        config_list = ['CONFIG_MODULE_SIG_FORMAT', 'CONFIG_MODULE_SIG']
        self._check_kernel_config(config_list,
                                  "Kernel module signing options not set")
        self.log.info("Kernel module signing options are set properly")

    def test_kernel_lockdown_mode(self):
        config_list = ['CONFIG_SECURITY_LOCKDOWN_LSM',
                       'CONFIG_SECURITY_LOCKDOWN_LSM_EARLY']
        self._check_kernel_config(config_list,
                                  "Kernel lockdown mode options not set")
        self.log.info("Kernel lockdown mode options are set properly")

    def test_seccomp_enabled(self):
        config_list = ['CONFIG_SECCOMP', 'CONFIG_SECCOMP_FILTER']
        self._check_kernel_config(config_list, "Seccomp options not set")
        self.log.info("Seccomp options are set properly")

    def test_kernel_debugging_protections(self):
        config_list = ['CONFIG_DEBUG_INFO', 'CONFIG_DEBUG_KERNEL']
        self._check_kernel_config(config_list,
                                  "Debugging config options not set")
        self.log.info("Debugging config options are set properly")
