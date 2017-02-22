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
# Copyright: 2016 IBM
# Author: Pooja B Surya <pooja@linux.vnet.ibm.com>

import os

from avocado import Test
from avocado import main
from avocado.utils import build
from avocado.utils import process, archive
from avocado.utils import git
from avocado.utils.software_manager import SoftwareManager


class Openblas(Test):

    def setUp(self):
        sm = SoftwareManager()
        for package in ['libopenblas-base', 'libopenblas-dev', 'git',
                        'gfortran']:
            if not sm.check_installed(package) and not sm.install(package):
                self.error(package + ' is needed for the test to be run')
        git.get_repo('https://github.com/xianyi/OpenBLAS.git',
                     destination_dir=self.srcdir)
        os.chdir(self.srcdir)
        build.make(self.srcdir, extra_args='FC=gfortran')
        build.make(self.srcdir, extra_args='install')
        os.chdir("test/")

    def test(self):
        process.run("make", ignore_status=True, sudo=True)
        logfile = os.path.join(self.logdir, "stdout")
        failed_tests = process.system_output(
            "grep -w FAIL %s" % logfile, shell=True, ignore_status=True)
        if failed_tests:
            self.fail("test failed, Please check debug log for failed"
                      "test cases")


if __name__ == "__main__":
        main()
