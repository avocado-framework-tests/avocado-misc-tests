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
from avocado.utils import process, dmesg


class Fsshrink(Test):
    '''
    Test performs parallel shrinkers (unlink/rmdir)
    https://lkml.org/lkml/2018/5/2/885

    :avocado: tags=fs
    '''

    def setUp(self):
        shutil.copy(self.get_data('test-shrink.sh'),
                    self.teststmpdir)
        dmesg.clear_dmesg()

    def test(self):

        os.chdir(self.teststmpdir)
        if process.system('./test-shrink.sh', sudo=True, ignore_status=True,
                          timeout=900):
            self.fail("unlink/rmdir (shrink) test failed")
        dmesg.collect_errors_dmesg(['WARNING: CPU:', 'Oops', 'Segfault',
                                    'soft lockup', 'Unable to handle'])
