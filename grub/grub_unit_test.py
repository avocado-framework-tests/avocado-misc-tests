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


class UnitTestCases(Test):
    """
    GRUB Unit test cases
    """
    def setUp(self):
        """
        Build Qemu and install required packages
        Source:
        https://github.com/qemu/qemu.git
        """
        sm = SoftwareManager()
        packages = ['meson', 'gcc', 'gettext-devel', 'libisoburn', 'xorriso']
        for package in packages:
            if not sm.check_installed(package) and not sm.install(package):
                self.cancel(
                    "Fail to install %s required for this test." % package)

        # Setup Qemu
        qemu_version = process.run("qemu-system-ppc --version",
                                   ignore_status=True, sudo=True, shell=True)
        if qemu_version.exit_status != 0:
            qemu_url = "https://github.com/qemu/qemu.git"
            process.run("git clone %s" % qemu_url)
            # build qemu
            cwd = os.getcwd()
            self.sourcedir_qemu = os.path.join(cwd, "qemu")
            os.chdir(self.sourcedir_qemu)
            commands = ["./configure --target-list=ppc-softmmu",
                        "make", "make install"]
            for cmd in commands:
                process.run(cmd, ignore_status=True, sudo=True, shell=True)
            build_check = process.run("qemu-system-ppc --version",
                                      ignore_status=True, sudo=True, shell=True)
            if build_check.exit_status != 0:
                self.fail("qemu build is not successful")

    def test_grub_unit_testcases(self):
        """
        Compile and build GRUB unit test cases
        Source:
        https://git.savannah.gnu.org/git/grub.git
        """
        cwd = os.getcwd()
        self.sourcedir_grub = os.path.join(cwd, "grub")
        if not os.path.exists(self.sourcedir_grub):
            url = "https://git.savannah.gnu.org/git/grub.git"
            process.run("git clone %s" % url)
        os.chdir(self.sourcedir_grub)
        commands = ["./bootstrap", "./configure", "make -j`nproc`"]
        for cmd in commands:
            ret = process.run(cmd, ignore_status=True, sudo=True, shell=True)
            if ret.exit_status != 0:
                self.fail("{} command failed during grub testcase build process".format(cmd))
        # Add unicode fonts before running test
        fonts_cmd = "cp /usr/share/grub/unicode.pf2 ."
        process.run(fonts_cmd, ignore_status=True, sudo=True, shell=True)
        # run the entire testsuite
        result = process.run("make check", ignore_status=True, sudo=True, shell=True)
        result = result.stdout.decode('utf-8').splitlines()
        for line in result:
            if "# XFAIL:" in line:
                xfail = int(line.strip().split(":")[-1])
            if "# FAIL:" in line:
                fail = int(line.strip().split(":")[-1])
        if xfail > 0 or fail > 0:
            self.fail("Total test fail are {}, please check the logs".format(line))

    def tearDown(self):
        if os.path.exists(self.sourcedir_grub):
            shutil.rmtree(self.sourcedir_grub)
