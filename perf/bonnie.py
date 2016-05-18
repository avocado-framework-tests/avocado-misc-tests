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
# Copyright: 2016 Red Hat, Inc.
# Author: Amador Pahim <apahim@redhat.com>
#
# Based on code by Martin J. Bligh <mbligh@google.com>
#   copyright 2006 Google
#   https://github.com/autotest/autotest-client-tests/tree/master/bonnie


import os

from avocado import Test
from avocado import main
from avocado.utils import archive
from avocado.utils import build
from avocado.utils import process


class Bonnie(Test):

    """
    Bonnie++ is a benchmark suite that is aimed at performing a number
    of simple tests of hard drive and file system performance.
    """

    def setUp(self):
        """
        Build bonnie++
        Source:
         http://www.coker.com.au/bonnie++/experimental/bonnie++-1.96.tgz
        """
        tarball = self.fetch_asset('http://www.coker.com.au/bonnie++/experimental/bonnie++-1.96.tgz')
        archive.extract(tarball, self.srcdir)
        self.srcdir = os.path.join(self.srcdir,
                                   os.path.basename(tarball.split('.tgz')[0]))
        os.chdir(self.srcdir)
        process.run('./configure')
        build.make(self.srcdir)

    def test(self):
        """
        Run 'bonnie' with its arguments
        """
        scratch_dir = self.params.get('scratch-dir', default=self.srcdir)
        uid_to_use = self.params.get('uid-to-use', default=None)
        number_to_stat = self.params.get('number-to-stat', default=2048)

        args = []
        args.append('-d %s' % scratch_dir)
        args.append('-n %s' % number_to_stat)
        if uid_to_use is not None:
            args.append('-u %s' % uid_to_use)

        cmd = ('%s/bonnie++ %s' % (self.srcdir, " ".join(args)))
        process.run(cmd)


if __name__ == "__main__":
    main()
