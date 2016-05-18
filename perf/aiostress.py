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
# Copyright: 2016 Red Hat, Inc
# Author: Amador Pahim <apahim@redhat.com>
#
# Based on code by Masoud Asgharifard Sharbiani <masouds@google.com>
#   copyright 2006 Google
#   https://github.com/autotest/autotest-client-tests/tree/master/aiostress


import os

from avocado import Test
from avocado import main
from avocado.utils import process


class Aiostress(Test):

    """
    aio-stress is a basic utility for testing the Linux kernel AIO api
    """

    def setUp(self):
        """
        Build 'aiostress'.
        Source:
         https://oss.oracle.com/~mason/aio-stress/aio-stress.c
        """
        aiostress = self.fetch_asset('https://oss.oracle.com/~mason/aio-stress/aio-stress.c')
        os.chdir(self.srcdir)
        # This requires libaio.h in order to build
        process.run('gcc -Wall -laio -lpthread -o aio-stress %s' % aiostress)

    def test(self):
        """
        Run aiostress
        """
        os.chdir(self.srcdir)
        # aio-stress needs a filename (foo) to run tests on.
        cmd = ('./aio-stress foo')
        process.run(cmd)


if __name__ == "__main__":
    main()
