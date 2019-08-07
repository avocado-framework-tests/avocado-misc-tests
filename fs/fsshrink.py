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
# Author: Praveen K Pandey <praveen@linux.vnet.ibm.com>
#

import os
import shutil

from avocado import Test
from avocado import main
from avocado.utils import process


class Fsshrink(Test):
    '''
    Test performs parallel shrinkers (unlink/rmdir)
    https://lkml.org/lkml/2018/5/2/885

    :avocado: tags=fs
    '''

    def clear_dmesg(self):
        process.run("dmesg -C ", sudo=True)

    def verify_dmesg(self):
        self.whiteboard = process.system_output("dmesg").decode()
        pattern = ['WARNING: CPU:', 'Oops',
                   'Segfault', 'soft lockup', 'Unable to handle']
        for fail_pattern in pattern:
            if fail_pattern in self.whiteboard:
                self.fail("Test Failed : %s in dmesg" % fail_pattern)

    def setUp(self):
        shutil.copy(self.get_data('test-shrink.sh'),
                    self.teststmpdir)

        self.clear_dmesg()

    def test(self):

        os.chdir(self.teststmpdir)
        if process.system('./test-shrink.sh', sudo=True, ignore_status=True,
                          timeout=900):
            self.fail("unlink/rmdir (shrink) test failed")

        self.verify_dmesg()


if __name__ == "__main__":
    main()
