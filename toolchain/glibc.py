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
# Copyright: 2016 IBM
# Author: Santhosh G <santhog4@linux.vnet.ibm.com>

import os
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils import build
from avocado.utils import git
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import distro
from avocado.core import data_dir


class glibc(Test):
    def setUp(self):
        sm = SoftwareManager()
        detected_distro = distro.detect()
        deps = ['gcc', 'git', 'make', 'gawk']
        self.tmpdir = data_dir.get_tmp_dir()
        self.build_dir = self.params.get('build_dir', default=self.tmpdir)
        for package in deps:
            if package == 'git' and detected_distro.name == "SuSE":
                package = 'git-core'
            if not sm.check_installed(package) and not sm.install(package):
                self.error(package + ' is needed for the test to be run')
        git.get_repo('git://sourceware.org/git/glibc.git',
                     destination_dir=self.srcdir)
        os.chdir(self.build_dir)
        process.run(self.srcdir + '/configure --prefix=%s' % self.build_dir,
                    ignore_status=True, sudo=True)
        build.make(self.build_dir)

    def test(self):
        os.chdir(self.build_dir)
        ret = os.system('make check')
        logfile = os.path.join(self.logdir, "stdout")
        if ret != 0:
            self.fail("Glibc tests failed\nCheck logfile %s for more Info"
                      % logfile)

if __name__ == "__main__":
    main()
