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
from avocado.utils import distro


class Systemtap(Test):

    """
    This test runs upstream systemtap tests
    """

    def setUp(self):
        smm = SoftwareManager()
        detected_distro = distro.detect()
        # TODO: Add debs for Ubuntu.
        if detected_distro.name == "Ubuntu":
            self.cancel("Skip the test  for ubuntu as debs needs to be"
                        "added in packages")
        packages = ['make', 'gcc', 'systemtap', 'systemtap-runtime',
                    'elfutils', 'kernel-devel', 'dejagnu']
        # FIXME: "redhat" as the distro name for RHEL is deprecated
        # on Avocado versions >= 50.0.  This is a temporary compatibility
        # enabler for older runners, but should be removed soon
        if detected_distro.name in ["redhat", "rhel"]:
            packages.extend(['git', 'kernel-debug', 'kernel-debuginfo',
                             'kernel-debug-debuginfo', 'elfutils-devel'])
        if detected_distro.name == "SuSE":
            packages.extend(['git-core', 'kernel-default-devel', 'libebl1',
                             'kernel-default-debuginfo', 'kernel-devel',
                             'kernel-macros', 'libdw-devel', 'libebl-devel',
                             'libelf-devel'])
        for package in packages:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel(' %s is needed for the test to be run' % package)
        git.get_repo('git://sourceware.org/git/systemtap.git',
                     destination_dir=self.workdir)
        os.chdir(self.workdir)
        process.run('./configure', ignore_status=True, sudo=True)
        build.make(self.workdir)
        build.make(self.workdir, extra_args='install')
        self.test_dir = os.path.join(self.workdir, "testsuite")
        os.chdir(self.test_dir)
        # Run a simple systemtap script to make sure systemtap and the
        # kernel debuginfo packages are correctly installed
        script_result = process.system("PATH=%s/bin:$PATH stap -v /bin/true "
                                       "-e 'probe vfs.read { exit()"
                                       " }'", ignore_status=True, sudo=True,
                                       shell=True)
        if script_result != 0:
            self.cancel("simple systemtap test failed,"
                        "kernel debuginfo package may be missing")

    def test(self):
        make_option = self.params.get('make_option', default='installcheck')
        build.make(self.workdir, extra_args=make_option)
        # path of the log file. self.workdir/testsuite/systemtap.sum
        failed_tests = process.system_output("grep -w FAIL systemtap.sum",
                                             shell=True, ignore_status=True)
        if failed_tests:
            self.log.info(failed_tests)
            self.fail("Few tests failed,check log")


if __name__ == "__main__":
    main()
