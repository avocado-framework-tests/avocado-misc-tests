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
from avocado.utils import process
from avocado.utils import git
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils import distro


class Oprofile(Test):

    def setUp(self):
        # Check for basic utilities
        sm = SoftwareManager()
        detected_distro = distro.detect()
        deps = ['dejagnu', 'expect']
        if detected_distro.name == "SuSE":
            deps.append("git-core")
        else:
            deps.append("git")
        if detected_distro.name in ["Ubuntu", 'debian']:
            deps.extend(["libxml2-utils", "tclsh"])
            if detected_distro.name == "Ubuntu":
                deps.extend(["oprofile"])
        elif (detected_distro.name == "rhel" and detected_distro.version >= "8"):
            deps.append("perf")
        else:
            deps.append("oprofile")
        for package in deps:
            if not sm.check_installed(package) and not sm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        git.get_repo('https://git.code.sf.net/p/oprofile/oprofile-tests',
                     destination_dir=self.workdir)
        os.chdir(self.workdir)
        os.chdir("testsuite/")

    def test(self):
        process.system('runtest --tool oprofile', ignore_status=True,
                       sudo=True)
        failed_tests = process.system_output("grep -w FAIL oprofile.sum",
                                             shell=True, ignore_status=True)
        if failed_tests:
            self.log.info(failed_tests)
            self.fail("few tests failed")
