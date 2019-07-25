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
# Copyright: 2016 IBM
# Author: Venkat Rao B <vrbagal1@linux.vnet.ibm.com>

"""
Blkdiscard  is  used  to  discard  device  sectors.This is useful for
solid-state drivers (SSDs) and thinly-provisioned storage.
"""

import avocado
from avocado import Test
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import process, lv_utils
from avocado import main

# this block need to removed when test moved to python3
try:
    # Python 2
    xrange
except NameError:
    # Python 3, xrange is now named range
    xrange = range


class Blkdiscard(Test):

    """
    blkdiscard is used to discard device sectors.This is useful for
    solid-state drivers (SSDs) and thinly-provisioned storage.
    """

    def setUp(self):
        """
        Checks if the blkdiscard packages are installed or not.
        """
        smm = SoftwareManager()
        if not smm.check_installed("util-linux"):
            self.cancel("blkdiscard is needed for the test to be run")
        self.disk = self.params.get('disk', default='/dev/nvme0n1')
        cmd = 'ls %s' % self.disk
        if process.system(cmd, ignore_status=True) is not 0:
            self.cancel("%s does not exist" % self.disk)
        cmd = "blkdiscard -V"
        process.run(cmd)

    @avocado.fail_on
    def test(self):
        """
        Sectors are dicarded for the different values of OFFSET and LENGTH.
        """
        size = int(lv_utils.get_diskspace(self.disk))
        cmd = "blkdiscard %s -o 0 -v -l %d" % (self.disk, size)
        process.run(cmd, shell=True)
        cmd = "blkdiscard %s -o %d \
               -v -l %d" % (self.disk, size, size)
        process.run(cmd, shell=True)
        cmd = "blkdiscard %s -o %d -v -l 0" % (self.disk, size)
        process.run(cmd, shell=True)
        for i in xrange(2, 10, 2):
            for j in xrange(2, 10, 2):
                if (size / i) % 4096 == 0 and (size / j) % 4096 == 0:
                    cmd = "blkdiscard %s -o %d -l %d -v" \
                        % (self.disk, size / i, size / j)
                    process.system(cmd, shell=True)
                else:
                    cmd = "blkdiscard %s -o %d -l %d -v" \
                        % (self.disk, size / i, size / j)
                    if process.system(cmd, ignore_status=True,
                                      shell=True) == 0:
                        self.fail("Blkdiscard passed for the values which is, \
                            not aligned to 4096 but actually it should fail")


if __name__ == "__main__":
    main()
