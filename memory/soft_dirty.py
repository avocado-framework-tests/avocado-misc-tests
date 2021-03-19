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
# Copyright: 2021 IBM
# Author: Harish <harish@linux.ibm.com>
#
# Based on code by:
# Author: Mohamed Alzayat <alzayat@mpi-sws.org>

import os

from avocado import Test
from avocado.utils import process
from avocado.utils.software_manager import SoftwareManager


class SoftDirtyBits(Test):
    '''
    Soft dirty bits test

    Causes at least one memory page to be dirtied, then scans /proc/pid/pagemap
    counting the soft-dirty bits. The test fails if this count is zero.
    Source: https://gist.githubusercontent.com/Zayat/3fa1f18388543dc1b9025aabf8
            f15b64/raw/b5049e4fc7a985c821320d22ca3e39d49dc7ea1a/test_sd_stability.c

    :avocado: tags=memory
    '''

    def setUp(self):
        '''
        Install dependency and fetch the source
        '''
        smm = SoftwareManager()
        if not smm.check_installed("gcc") and not smm.install("gcc"):
            self.cancel('gcc is needed for the test to be run')

        locations = ["https://gist.githubusercontent.com/Zayat/3fa1f18388543dc"
                     "1b9025aabf8f15b64/raw/b5049e4fc7a985c821320d22ca3e39d49d"
                     "c7ea1a/test_sd_stability.c"]
        self.src_file = self.fetch_asset("test_sd_stability.c",
                                         locations=locations, expire='7d')

    def test(self):
        '''
        Run soft dirty bits test
        '''
        os.chdir(self.workdir)
        if process.system("gcc %s -o test_sd_stable" %
                          self.src_file, shell=True, ignore_status=True):
            self.fail("Failed to build test case")

        if process.system("./test_sd_stable", shell=True, ignore_status=True):
            self.fail("Soft-dirty bits test failed, please check the logs!")
