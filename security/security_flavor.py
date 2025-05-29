#!/usr/bin/env python
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
# Copyright: 2024 IBM
# Author: Krishan Gopal Saraswat <krishang@linux.vnet.ibm.com>

import os
from avocado import Test
from avocado.utils import process, genio


class SecurityFlavor(Test):
    '''
    LPAR's security flavor
    '''
    def test_security_flavor(self):
        '''
        Security flavor values according to IBM support page
        0 Speculative execution fully enabled
        1 Speculative execution controls to mitigate user-to-kernel attacks
        2 Speculative execution controls to mitigate user-to-kernel and
        user-to-user side-channel attacks
        '''
        if not os.path.isfile("/proc/powerpc/lparcfg"):
            self.cancel("lparcfg file doesn't exist")
        lparcfg = "/proc/powerpc/lparcfg"
        cmd = "lparstat -x"

        lparcfg_output = genio.read_file(lparcfg).splitlines()
        for lines in lparcfg_output:
            if "security_flavor" in lines:
                lparcfg_value = lines.strip().split("=")[-1]
                break
        lparstat_output = process.system_output(cmd, ignore_status=True).decode()
        lparstat_value = lparstat_output.split(":")[-1].strip()

        if lparcfg_value != lparstat_value:
            self.fail("LPAR security flavor values are not matching")
