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
# Based on code by Curt Wohlgemuth <curtw@google.com>
#   copyright 2009 Google
#   https://github.com/autotest/autotest-client-tests/tree/master/compilebench


import os

from avocado import Test
from avocado import main
from avocado.utils import archive
from avocado.utils import process


class Compilebench(Test):

    """
    Compilebench tries to age a filesystem by simulating some of the
    disk IO common in creating, compiling, patching, stating and
    reading kernel trees.
    """

    def setUp(self):
        """
        Extract compilebench
        Source:
         https://oss.oracle.com/~mason/compilebench/compilebench-0.6.tar.bz2
        """
        tarball = self.fetch_asset('https://oss.oracle.com/~mason/compilebench/compilebench-0.6.tar.bz2')
        archive.extract(tarball, self.workdir)
        cb_version = os.path.basename(tarball.split('.tar.')[0])
        self.sourcedir = os.path.join(self.workdir, cb_version)

    def test(self):
        """
        Run 'compilebench' with its arguments
        """
        initial_dirs = self.params.get('INITIAL_DIRS', default=10)
        runs = self.params.get('RUNS', default=30)

        args = []
        args.append('-D %s ' % self.sourcedir)
        args.append('-s %s ' % self.sourcedir)
        args.append('-i %d ' % initial_dirs)
        args.append('-r %d ' % runs)

        # Using python explicitly due to the compilebench current
        # shebang set to python2.4
        cmd = ('python %s/compilebench %s' % (self.sourcedir, " ".join(args)))
        process.run(cmd)


if __name__ == "__main__":
    main()
