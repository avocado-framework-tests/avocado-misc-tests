#! /usr/bin/env python

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
# Copyright: 2016 IBM
# Author: Balamuruhan S <bala24@linux.vnet.ibm.com>
#
# Based on code by Gregory P. Smith <gps@google.com>
#   copyright 2008 Google, Inc.
#   https://github.com/autotest/autotest-client-tests/tree/master/error_cleanup

from avocado import Test
from avocado import main


class error_cleanup(Test):
    """
    Raise an exception during tearDown()
    """

    def test(self):
        pass

    def tearDown(self):
        self.error("Test a bug in tearDown()")


if __name__ == "__main__":
    main()
