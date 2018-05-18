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
from avocado import main
from avocado.utils import process


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
        if self.iso_location is '':
            self.cancel("No ISO location given")
        self.option = self.params.get('option', default='')
        self.uninstall_flag = self.params.get('uninstall', default=True)
        self.iso = self.fetch_asset(self.iso_location, expire='10d')
        cmd = "mount -o loop %s %s" % (self.iso, self.workdir)
        process.run(cmd, shell=True)
        self.pwd = os.getcwd()

    def install(self):
        """
        Installs MOFED with given options.
        """
        self.log.info("Starting installation")
        os.chdir(self.workdir)
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
        cmd = "ibstat"
        if not process.system(cmd, ignore_status=True, shell=True):
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


if __name__ == "__main__":
    main()
