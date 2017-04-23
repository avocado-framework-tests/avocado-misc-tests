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
# Copyright: 2017 IBM
# Author: Pooja B Surya <pooja@linux.vnet.ibm.com>
# Based on code by Anton Blanchard <anton@samba.org>

# https://github.com/autotest/autotest-client-tests/tree/master/systemtap

import os

from avocado import Test
from avocado import main
from avocado.utils import build
from avocado.utils import process
from avocado.utils import git
from avocado.utils.software_manager import SoftwareManager


class Systemtap(Test):

    def setUp(self):
        smm = SoftwareManager()
        packages = ['make', 'gcc', 'systemtap', 'systemtap-runtime',
                    'elfutils', 'kernel-devel', 'kernel-debug',
                    'kernel-debuginfo', 'kernel-debug-debuginfo', 'dejagnu',
                    'elfutils-devel']
        for package in packages:
            if not smm.check_installed(package) and not smm.install(package):
                self.skip(' %s is needed for the test to be run' % package)
        git.get_repo('git://sourceware.org/git/systemtap.git',
                     destination_dir=self.srcdir)
        os.chdir(self.srcdir)
        process.run('./configure', ignore_status=True, sudo=True)
        build.make(self.srcdir)
        build.make(self.srcdir, extra_args='install')
        self.test_dir = os.path.join(self.srcdir, "testsuite")
        os.chdir(self.test_dir)
        # Run a simple systemtap script to make sure systemtap and the
        # kernel debuginfo packages are correctly installed
        script_result = process.run("PATH=%s/bin:$PATH stap -v /bin/true "
                                    "-e 'probe vfs.read { exit()"
                                    " }'", ignore_status=True, sudo=True,
                                    shell=True)
        self.log.info(script_result)
        if script_result.exit_status != 0:
            self.fail("simple systemtap test failed,"
                      "kernel debuginfo package may be missing")

    def test(self):
        build.make(self.srcdir, extra_args='installcheck')
        failed_tests = process.system_output("grep -w FAIL systemtap.sum",
                                             shell=True, ignore_status=True)
        if failed_tests:
            self.log.info(failed_tests)
            self.fail("Few tests faiiled,check log")


if __name__ == "__main__":
    main()
