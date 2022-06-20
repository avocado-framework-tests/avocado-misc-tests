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
# Author: Narasimhan V <sim@linux.vnet.ibm.com>

"""
MOFED Install Test
"""

import os
from avocado import Test
from avocado.utils import process, distro
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils import linux_modules


class MOFEDInstallTest(Test):

    """
    This test verifies the installation of MOFED iso with different
    combinations of input parameters, as specified in multiplexer file.

    """

    def setUp(self):
        """
        Mount MOFED iso.
        """
        self.iso_location = self.params.get('iso_location', default='')
        self.kernelc = self.params.get("kernel_compile", default="Y")
        if self.iso_location is '':
            self.cancel("No ISO location given")
        self.option = self.params.get('option', default='')
        self.uninstall_flag = self.params.get('uninstall', default=True)
        detected_distro = distro.detect()
        pkgs = []
        self.uname = linux_modules.platform.uname()[2]
        kernel_ver = "kernel-devel-%s" % self.uname
        smm = SoftwareManager()
        if detected_distro.name == "SuSE":
            pkgs.extend(["make", "gcc", "python3-devel", "kernel-source",
                         "kernel-syms", "insserv-compat", "rpm-build"])
        # FIXME: "redhat" as the distro name for RHEL is deprecated
        # on Avocado versions >= 50.0.  This is a temporary compatibility
        # enabler for older runners, but should be removed soon
        elif detected_distro.name in ['rhel', 'fedora', 'redhat']:
            pkgs.extend(["make", "gcc", "python36-devel", "tcsh",
                         "kernel-rpm-macros", "gdb-headless", "rpm-build",
                         "gcc-gfortran", kernel_ver])
        for pkg in pkgs:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel("Not able to install %s" % pkg)
        self.iso = self.fetch_asset(self.iso_location, expire='10d')
        cmd = "mount -o loop %s %s" % (self.iso, self.workdir)
        process.run(cmd, shell=True)
        self.pwd = os.getcwd()
        if self.options_check() is False:
            self.cancel("option %s not supported with this MOFED" % self.option)

    def install(self):
        """
        Installs MOFED with given options.
        """
        self.log.info("Starting installation")
        os.chdir(self.workdir)
        if self.kernelc:
            self.option = self.option + " --add-kernel-support --skip-repo"
        cmd = './mlnxofedinstall %s --force' % self.option
        if process.system(cmd, ignore_status=True, shell=True):
            self.fail("Install Failed with %s" % self.option)

    def uninstall(self):
        """
        Uninstalls MOFED, if installed fine.
        """
        self.log.info("Starting uninstallation")
        cmd = "/etc/init.d/openibd restart"
        if not process.system(cmd, ignore_status=True, shell=True):
            return
        cmd = "ofed_info -s"
        if process.system(cmd, ignore_status=True, shell=True):
            return
        cmd = './uninstall.sh --force'
        if process.system(cmd, ignore_status=True, shell=True):
            self.fail("Uninstall Failed")

    def test(self):
        """
        Tests install and uninstall of MOFED.
        """
        self.install()
        if self.uninstall_flag:
            self.uninstall()

    def tearDown(self):
        """
        Clean up
        """
        os.chdir(self.pwd)
        cmd = "umount %s" % self.workdir
        process.run(cmd, shell=True)

    def options_check(self):
        '''
        Checks if Option is supported for the latest MOFED, Returns True if yes.
        Returns False otherwise.
        '''
        os.chdir(self.workdir)
        value_check = process.system_output('./mlnxofedinstall --help').decode('utf-8')
        vlist = self.option.split(" ")
        res = [idx for idx in vlist if idx.startswith('--') or idx.startswith('-')]
        for val in res:
            if val not in value_check:
                return False
        return True
