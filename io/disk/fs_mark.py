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
# Copyright (C) 2003-2004 EMC Corporation
#
# fs_mark: Benchmark synchronous/async file creation
#
# Ported to avocado by Kalpana S Shetty <kalshett@in.ibm.com>
# Written by Ric Wheeler <ric@emc.com>
#   http://prdownloads.sourceforge.net/fsmark/fs_mark-3.3.tar.gz

import os

from avocado import Test
from avocado import main
from avocado.utils import archive
from avocado.utils import build
from avocado.utils import process


class fs_mark(Test):

    """
    The fs_mark program is meant to give a low level bashing to file
    systems. The write pattern that we concentrate on is heavily
    synchronous IO across mutiple directories, drives, etc.
    """

    def setUp(self):
        """
        fs_mark
        """

        tarball = self.fetch_asset('http://prdownloads.source'
                                   'forge.net/fsmark/fs_mark-3.3.tar.gz')
        archive.extract(tarball, self.srcdir)
        fs_version = os.path.basename(tarball.split('.tar.')[0])
        self.srcdir = os.path.join(self.srcdir, fs_version)
        os.chdir(self.srcdir)
        process.run('make')
        build.make(self.srcdir)

    def test(self):
        """
        Run fs_mark
        """
        os.chdir(self.srcdir)

        # Just provide a sample run parameters
        num_files = self.params.get('num_files', default='1024')
        size = self.params.get('size', default='1000')
        dir = self.params.get('dir', default='/var/tmp')
        cmd = ('./fs_mark -d %s -s %s -n %s' % (dir, size, num_files))
        process.run(cmd)

if __name__ == "__main__":
    main()
