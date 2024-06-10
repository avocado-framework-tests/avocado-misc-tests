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
# Copyright: 2024 IBM
# Author: Krishan Gopal Saraswat <krishang@linux.ibm.com>

import os
import shutil
from avocado import Test
from avocado.utils import process
from avocado.utils.software_manager.manager import SoftwareManager


class Trex(Test):
    """
    Trex test
    """
    def setUp(self):
        """
        Build Trex
        Source:
        https://github.com/IBM/trextest
        """
        sm = SoftwareManager()
        packages = ['meson', 'gcc']
        for package in packages:
            if not sm.check_installed(package) and not sm.install(package):
                self.cancel(
                    "Fail to install %s required for this test." % package)
        cwd = os.getcwd()
        self.sourcedir = os.path.join(cwd, "trextest")
        if not os.path.exists(self.sourcedir):
            url = "https://github.com/IBM/trextest"
            process.run("git clone %s" % url)
        os.chdir(self.sourcedir)

    def test_trex(self):
        """
        Compile and build Trextest
        """
        make_cmd = "./make.sh"
        process.run(make_cmd, ignore_status=True, sudo=True, shell=True)
        build_dir = os.path.join(self.sourcedir, "build/tests")
        os.chdir(build_dir)
        # Get all the executable binaries in current directory
        cmd = "find . -maxdepth 1 -perm /u=x,g=x,o=x -type f"
        build_exec = process.system_output(cmd,
                                           ignore_status=True,
                                           sudo=True,
                                           shell=True
                                           ).decode().split("\n")

        for binaries in build_exec:
            res = process.run(binaries, ignore_status=True,
                              sudo=True, shell=True)
            if binaries == "./timing_array_test":
                if res.exit_status:
                    continue
                elif "Fail" in res.stdout.decode():
                    self.fail("%s test failed" % binaries)
            elif res.exit_status:
                self.fail("%s test failed" % binaries)
        demos_dir = os.path.join(self.sourcedir, "build/demos")
        os.chdir(demos_dir)
        # Get all the executable binaries in current directory
        demos_exec = process.system_output(cmd,
                                           ignore_status=True,
                                           sudo=True,
                                           shell=True
                                           ).decode().split("\n")
        for binaries in demos_exec:
            res = process.run(binaries, ignore_status=True,
                              sudo=True, shell=True)
            if res.exit_status and "Fail" in res.stdout.decode():
                self.fail("%s test failed" % binaries)

    def tearDown(self):
        # Delete the cloned directory after test finish
        if os.path.exists(self.sourcedir):
            shutil.rmtree(self.sourcedir)
