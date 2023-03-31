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
# Copyright: 2023 IBM.
# Author: Nageswara R Sastry <rnsastry@linux.ibm.com>

import os
from avocado import Test
from avocado.utils import distro, genio, linux_modules, process
from avocado.utils.software_manager.manager import SoftwareManager


class kernelLockdown(Test):
    """
    Kernel Lockdown tests for Linux
    :avocado: tags=privileged,security,lockdown
    """

    def setUp(self):
        '''
        Kernel lockdown and Guest Secure boot support is available only on
        Power10 LPAR.
        '''
        self.distro_version = distro.detect()
        smm = SoftwareManager()
        deps = []
        if self.distro_version.name in ['rhel', 'redhat']:
            deps.extend(['powerpc-utils-core'])
        if self.distro_version.name in ['SuSE']:
            deps.extend(['powerpc-utils'])
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        val = genio.read_file("/proc/cpuinfo")
        if 'POWER10' not in val:
            self.cancel("Power10 LPAR is required to run this test.")
        # Checking whether lockdown enabled or not.
        self.lockdown_file = "/sys/kernel/security/lockdown"
        if not os.path.exists(self.lockdown_file):
            self.cancel("Lockdown not enabled, can't execute test(s)")
        lockdown = genio.read_file(self.lockdown_file).rstrip('\t\r\n\0')
        index1 = int(lockdown.index('[')) + 1
        index2 = int(lockdown.index(']'))
        sys_lockdown = lockdown[index1:index2]
        # Checking the Guest Secure Boot enabled or not.
        cmd = "lsprop  /proc/device-tree/ibm,secure-boot"
        output = process.system_output(cmd, ignore_status=True).decode()
        if '00000002' not in output:
            self.cancel("Secure boot is not enabled.")
        # List required for kernel configuration check.
        self.no_config = []

    def _check_kernel_config(self, config_option):
        # Helper function to check kernel config options
        ret = linux_modules.check_kernel_config(config_option)
        if ret == linux_modules.ModuleConfig.NOT_SET:
            self.no_config.append(config_option)

    def test_check_kernel_config(self):
        # Checking the required kernel config options for lockdown
        self._check_kernel_config('CONFIG_SECURITY_LOCKDOWN_LSM')
        self._check_kernel_config('CONFIG_SECURITY_LOCKDOWN_LSM_EARLY')
        self._check_kernel_config('CONFIG_LSM')
        if self.no_config:
            self.fail("Config options not set are: %s" % self.no_config)

    def test_lockdown_none(self):
        # Try changing the lockdown value to 'none'
        try:
            genio.write_one_line(self.lockdown_file, 'none')
        except IOError as err:
            if 'Operation not permitted' not in str(err):
                self.fail("Kernel Lockdown value changed to 'none'")

    def test_lockdown_mem(self):
        # Try read the values from /dev/mem
        try:
            genio.read_file("/dev/mem")
        except IOError as err:
            if 'Operation not permitted' not in str(err):
                self.fail("'/dev/mem' file access permitted.")

    def test_lockdown_debugfs(self):
        if self.distro_version.name == "SuSE":
            self.cancel("This test not supported on SuSE")
        # Try read the values from sysfs file
        output = process.system_output('mount', ignore_status=True).decode()
        if 'debugfs' not in output:
            self.cancel("Skip this test as 'debugfs' not mounted.")
        dbg_file = "/sys/kernel/debug/powerpc/xive"
        if os.path.exists(dbg_file):
            try:
                genio.read_file(dbg_file)
            except IOError as err:
                if 'Operation not permitted' not in str(err):
                    self.fail("Access to %s permitted." % dbg_file)
        else:
            self.cancel("%s file not exist." % dbg_file)
