#!/usr/bin/env python

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
