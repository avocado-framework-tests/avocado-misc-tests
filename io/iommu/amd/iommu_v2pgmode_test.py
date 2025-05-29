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
# Copyright: 2023 Advanced Micro Devices, Inc.
# Author: Dheeraj Kumar Srivastava <dheerajkumar.srivastava@amd.com>

"""
Validate 5 level page table support in v2 iommu page table mode
"""

import os
import platform
from avocado import Test
from avocado import skipUnless
from avocado.utils import cpu, process


def check_kernelconf(config_file, config):
    """
    check if kernel config 'config' is enable on not in 'config_file'

    :config_file: kernel config file path to check
    :config: kernel config to check if builtin or not
    return: bool
    """
    with open(config_file, "r") as kernel_config:
        for line in kernel_config:
            line = line.split("=")
            if len(line) != 2:
                continue
            if line[0].strip() == f"{config}":
                if line[1].strip() == 'y':
                    return True
    return False


def check_dmesg(string):
    """
    Check dmesg for 'string' in dmesg
    """
    cmd = f'dmesg | grep -i "{string}"'
    output = process.run(cmd, ignore_status=True, shell=True).stdout_text
    if output == "":
        cmd = f'journalctl -k -b | grep -i "{string}"'
        output = process.run(cmd, ignore_status=True, shell=True).stdout_text
        if output != "":
            return True
    else:
        return True
    return False


def check_v2pgtbl_mode(mode):
    '''
    Check if v2 page table is enabled in "mode" level of paging
    '''
    return check_dmesg(f'V2 page table enabled (Paging mode : {mode} level)')


class IommuPageTable(Test):
    '''
    Test v2 page table -
    1. Checks if host page table mode matches with iommu v2 page table mode
    '''
    @skipUnless('x86_64' in cpu.get_arch(),
                "This test runs on x86-64 platform.\
        If 5-level page table supported on other platform then\
        this condition can be removed")
    def setUp(self):
        '''
        Few checks and initialisation before test
        '''
        self.bits_to_pgmode = {'57': '5', '48': '4', '39': '3', '30': '2', '21': '1'}

        # Check if iommu is in translation
        if check_dmesg('AMD-Vi'):
            if not check_dmesg('iommu: Default domain type: Translated'):
                self.cancel("IOMMU is not in Translation mode")
        else:
            self.cancel("IOMMU is not enabled")

    def check_kernelconf_5lvl(self):
        """
        Check if kernel config 'CONFIG_X86_5LEVEL' enabled or not
        return: bool
        """

        kernel_version = platform.uname()[2]
        config_file = "/boot/config-" + kernel_version
        if os.path.exists(config_file):
            return check_kernelconf(config_file, "CONFIG_X86_5LEVEL")

        config_file = "/lib/modules/" + kernel_version + "/build/.config"
        if os.path.exists(config_file):
            return check_kernelconf(config_file, "CONFIG_X86_5LEVEL")

        self.log.info("Kernel config not found in '/boot/' and '/lib/modules/<uname -r>/build/'."
                      "Using VA bits in /proc/cpuinfo to derive cpu page table level")
        return False

    def test(self):
        '''
        Test if host page table mode matches with iommu v2 page table mode
        '''
        if check_dmesg('V2 page table enabled'):
            if (cpu.cpu_has_flags(["la57"]) and self.check_kernelconf_5lvl()):
                if check_v2pgtbl_mode("5"):
                    self.log.info("Host page table mode (5lvl) match with IOMMU V2 Page mode")
                else:
                    self.fail("Host page table mode (5lvl) does not match with IOMMU V2 Paging mode")
            else:
                if check_v2pgtbl_mode(self.bits_to_pgmode[cpu.get_va_bits()]):
                    self.log.info("Host page table mode match with IOMMU V2 Page mode")
                else:
                    self.fail("Host page table mode does does not match with IOMMU V2 Paging mode")
        else:
            self.cancel("IOMMU is in v1 page table")
