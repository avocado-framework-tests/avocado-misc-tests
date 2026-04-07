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
import fcntl
import struct
from avocado import Test
from avocado.utils import distro, genio, linux_modules, process, linux
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils import dmesg


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
        power_ver = ['POWER10', 'Power11']
        if not any(x in val for x in power_ver):
            self.cancel("LPAR on Power10 and above is required for this test.")
        # Checking whether lockdown enabled or not.
        self.lockdown_file = "/sys/kernel/security/lockdown"
        if not os.path.exists(self.lockdown_file):
            self.cancel("Lockdown not enabled, can't execute test(s)")
        lockdown = genio.read_file(self.lockdown_file).rstrip('\t\r\n\0')
        index1 = int(lockdown.index('[')) + 1
        index2 = int(lockdown.index(']'))
        sys_lockdown = lockdown[index1:index2]
        # Checking the Guest Secure Boot enabled or not.
        if not linux.is_os_secureboot_enabled():
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
        kclist = ['CONFIG_SECURITY_LOCKDOWN_LSM',
                  'CONFIG_SECURITY_LOCKDOWN_LSM_EARLY']
        if self.distro_version.version == '8':
            kclist = ['CONFIG_LOCK_DOWN_KERNEL']
        for kconfig in kclist:
            self._check_kernel_config(kconfig)
        if self.no_config:
            self.fail("Config options not set are: %s" % self.no_config)

    def test_lockdown_none(self):
        # Try changing the lockdown value to 'none'
        try:
            genio.write_one_line(self.lockdown_file, 'none')
        except PermissionError as err:
            if 'Operation not permitted' not in str(err):
                self.fail("Kernel Lockdown value changed to 'none'")
        except OSError as err:
            if 'Invalid argument' not in str(err):
                self.fail("Kernel Lockdown value changed to 'none'")

    def test_lockdown_mem(self):
        # Try read the values from /dev/mem
        try:
            genio.read_file("/dev/mem")
        except PermissionError as err:
            if 'Operation not permitted' not in str(err):
                self.fail("'/dev/mem' file access permitted.")

    def test_lockdown_debugfs(self):
        # Try read the values from sysfs file
        output = process.system_output('mount', ignore_status=True).decode()
        if 'debugfs' not in output:
            self.cancel("Skip this test as 'debugfs' not mounted.")
        dbg_file = "/sys/kernel/debug/powerpc/xive/store-eoi"
        if os.path.exists(dbg_file):
            try:
                genio.read_file(dbg_file)
            except PermissionError as err:
                if 'Operation not permitted' not in str(err):
                    self.fail("Access to %s permitted." % dbg_file)
        else:
            self.cancel("%s file not exist." % dbg_file)

    def test_lockdown_ioctl(self):
        # Clear dmesg log
        dmesg.clear_dmesg()
        # open file descriptor of /dev/ttyS0
        fd = os.open("/dev/ttyS0", os.O_RDWR)
        if fd == -1:
            self.cancel("Failed to open /dev/ttyS0")
        try:
            # Define the ioctl command and argument for configuring serial
            # port settings
            # TIOCSSERIAL is the ioctl command for setting serial port
            # parameters
            # The argument is a packed structure containing the desired
            # settings
            # The value 0x1002 is an example setting for the serial port
            # configuration
            TIOCSSERIAL = 0x541F
            arg = struct.pack('I', 0x1002)
            fcntl.ioctl(fd, TIOCSSERIAL, arg)
        except PermissionError as err:
            if 'Operation not permitted' not in str(err):
                self.fail("'/dev/ttyS0' file access permitted.")
        finally:
            os.close(fd)
        # Collect the dmesg messages
        dfile = dmesg.collect_dmesg()
        text = "Lockdown: avocado-runner-: reconfiguration of serial port IO is restricted; see man kernel_lockdown.7"
        try:
            # Check if the dmesg log contains the expected message
            # The dmesg log is read using the genio module
            # The log is split into lines for easier searching
            # The expected message is searched for in the log lines
            # If the message is not found, the test fails
            # The dmesg log file is removed after checking
            dmesg_output = genio.read_file(dfile).splitlines()
            counter = False
            for lines in dmesg_output:
                if text in lines:
                    counter = True
                    break
            if not counter:
                self.fail("Lockdown message not found in dmesg log.")
        except Exception as e:
            self.fail("Failed to read dmesg log: %s" % str(e))
        finally:
            os.remove(dfile)
