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
# Copyright: 2018 IBM
# Author: Nageswara R Sastry <rnsastry@linux.vnet.ibm.com>

import os
import shutil
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils import build
from avocado.utils import distro
from avocado.utils.software_manager import SoftwareManager


class PowerTimeBaseBug(Test):
    '''
    PowerTimeBaseBug is based on valgrind. Valgrind is truncating
    output of __ppc_get_timebase value to 32 bit.

    This test case verify whether we have bug exist or not.

    :avocado: tags=toolchain,ppc64le
    '''

    def setUp(self):
        '''
        Check for required packages namely gcc, make, valgrind.
        Transfer the source file and make file.
        Compile
        '''
        smm = SoftwareManager()

        dist = distro.detect()
        if dist.arch != "ppc64le":
            self.cancel("Test is not applicable!!")
        deps = ['gcc', 'make', 'valgrind']
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

        self.log.info("Tranferring the files ...")
        shutil.copyfile(self.get_data('print_power_time_base.c'),
                        os.path.join(self.teststmpdir, 'print_power_time_base.c'))

        self.log.info("About to compile ...")
        shutil.copyfile(self.get_data('Makefile'),
                        os.path.join(self.teststmpdir, 'Makefile'))

        build.make(self.teststmpdir)

    def test(self):
        '''
        Execute the above compiled with and with out valgrind.
        Expected output should be of 64-bit value
        '''
        os.chdir(self.teststmpdir)
        for cmd in ['./print_power_time_base', 'valgrind ./print_power_time_base']:
            self.log.info("Running %s", cmd)
            cmd_output = process.system_output(cmd)
            self.log.info("Output of command %s=%s", cmd, cmd_output)
            for line in cmd_output.splitlines():
                if 'timebase' in line:
                    len_str = len(line.split('=')[1].lstrip())
                    if len_str <= 8:
                        self.fail('Test failed.')


if __name__ == "__main__":
    main()
