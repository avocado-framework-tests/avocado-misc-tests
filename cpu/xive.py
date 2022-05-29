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
                xive_path = "/sys/kernel/debug/powerpc/xive/store-eoi"

            flags = genio.read_file(xive_path)
            if is_dir:
                # store-eoi value can be enabled or disable via kernel command
                # line or using sysfs debug directory.
                match = re.search("Y", flags) or re.search("N", flags)
            else:
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
