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
#
# Copyright: 2021 IBM
# Author: Kalpana Shetty <kalshett@in.ibm.com>

import os
import re

from avocado import Test
from avocado.utils import genio
from avocado.utils import linux_modules


class XIVE(Test):

    '''
    XIVE test cases

    :avocado: tags=cpu,power
    '''

    def setUp(self):
        if "ppc" not in os.uname()[4]:
            self.cancel("Test case is supported only on IBM Power Servers")

        cpu_info = genio.read_file("/proc/cpuinfo")
        if 'POWER9' in cpu_info:
            self.hw = "POWER9"
        elif 'POWER10' in cpu_info:
            self.hw = "POWER10"
        else:
            self.cancel("Unsupported processor family")

        mode = genio.read_file("/proc/interrupts")
        if 'XIVE' in mode:
            self.intr = 'XIVE'
        elif 'XICS' in mode:
            self.intr = 'XICS'
        else:
            self.fail("Unsupported Interrupt Mode")

        self.no_config_parameter = []

    def test_intr_mode(self):
        if self.intr == 'XIVE':
            self.log.info("%s Enabled System" % self.intr)
        elif self.intr == 'XICS':
            self.log.info("%s Enabled System" % self.intr)
        else:
            self.fail("System is not Enabled with XIVE or XICS")

    def test_storeEOI(self):
        self.log.info("HW: %s Mode: %s" % (self.hw, self.intr))
        if self.intr == 'XIVE':
            xive_path = "/sys/kernel/debug/powerpc/xive"
            # Kernel commit baed14de78b5 changed the debugfs file xive into a
            # directory. Add a check for the same.
            is_dir = os.path.isdir(xive_path)
            if not is_dir and not os.path.exists(xive_path):
                self.fail("Unexpected failure: XIVE specific information is "
                          "missing %s / %s" % (self.hw, self.intr))
            if is_dir:
                # If xive is a directory then read from store-eoi file
                xive_file = os.path.join(xive_path, "store-eoi")
                if os.path.exists(xive_file):
                    flags = genio.read_file(xive_file)

                    # store-eoi value can be enabled or disable via kernel
                    # command line or using sysfs debug directory.
                    match = re.search("Y", flags) or re.search("N", flags)
                else:
                    xive_file = os.path.join(xive_path, "interrupts")
                    if os.path.exists(xive_file):
                        flags = genio.read_file(xive_file)
                    else:
                        self.fail("Expected files not found.")
                    match = re.search("flags=S", flags)
            else:
                flags = genio.read_file(xive_path)
                match = re.search("flags=S", flags)

            self.log.info("MATCH = %s" % match)
            if match:
                self.log.info("storeEOI feature is available and 'S' flag "
                              "is present for %s / %s" % (self.hw, self.intr))
            else:
                self.fail("storeEOI feature 'S' flag is absent for "
                          "%s / %s" % (self.hw, self.intr))
        elif self.intr == 'XICS':
            self.cancel("storeEOI feature is not Available for %s / %s" %
                        (self.hw, self.intr))
        else:
            self.fail("storeEOI tests failed")

    def test_verify_xive_cmdline(self):
        pattern = "xive=on"
        retval = genio.is_pattern_in_file("/proc/cmdline", pattern)
        if retval:
            self.log.info("XIVE is enabled.")
        else:
            self.log.info("XIVE is not enabled.")

    def _check_kernel_config(self, config_parameter):
        ret = linux_modules.check_kernel_config(config_parameter)
        if ret == linux_modules.ModuleConfig.NOT_SET:
            self.no_config_parameter.append(config_parameter)

    def test_verify_xive_config(self):
        self._check_kernel_config('CONFIG_PPC_XIVE')
        self._check_kernel_config('CONFIG_PPC_XIVE_NATIVE')
        self._check_kernel_config('CONFIG_PPC_XIVE_SPAPR')

        if self.no_config_parameter:
            self.fail("XIVE Config parameters not enabled are : %s" %
                      self.no_config_parameter)
