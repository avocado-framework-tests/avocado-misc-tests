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
# Copyright: 2020 IBM.
# Author: Praveen K Pandey <praveen@linux.vnet.ibm.com>

import os

from avocado import Test, skipIf
from avocado.utils import process, build, pci
from avocado.utils import archive
from avocado.utils.software_manager.manager import SoftwareManager


class ServiceReport(Test):

    """
    ServiceReport is a tool to validate and repair system configuration for
    specific purposes.Initially envisaged to help setup systems for correct
    First Failure Data Capture (FFDC),it has now morphed into a plugin based
    framework which can do more than just FFDC validation.

    :avocado: tags=privileged
    """

    def setUp(self):
        smm = SoftwareManager()
        self.options = self.params.get('option', default='-l')
        if self.options == "-p":
            self.plugin = self.params.get('plugin_val', default='kdump')
            self.options = "%s %s" % (self.options, self.plugin)
        for package in ['make', 'gcc']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel("Fail to install %s required for this"
                            " test." % package)
        tarball = self.fetch_asset('ServiceReport.zip', locations=[
                                   'https://github.com/linux-ras/ServiceReport'
                                   '/archive/master.zip'], expire='7d')
        archive.extract(tarball, self.workdir)
        self.sourcedir = os.path.join(self.workdir, 'ServiceReport-master')
        build.make(self.sourcedir)

    def isAccelerator(self):
        for dev in os.listdir('/sys/bus/pci/devices'):
            try:
                if pci.get_pci_class_name(dev) == "accelerator":
                    return True
            except Exception:
                pass
        return False

    def test(self):
        os.chdir(self.sourcedir)
        cmd = "servicereport %s" % self.options
        if process.system(cmd, ignore_status=True, sudo=True, shell=True):
            self.fail("ServiceReport: Failed command is: %s" % cmd)

    @skipIf("ppc" not in os.uname()[4], "Skip, Powerpc specific tests")
    @skipIf(lambda self: not self.isAccelerator(), "Unsupported: PCI adapter is not an accelarator")
    def test_accelerator(self):
        os.chdir(self.sourcedir)

        cmd = "servicereport %s" % self.options
        if process.system(cmd, ignore_status=True, sudo=True, shell=True):
            self.fail("ServiceReport: Failed command is: %s" % cmd)

        if os.path.isdir('/dev/vfio') and any(e.isdigit() for e in os.listdir('/dev/vfio')):
            self.log.info("/dev/vfio already populated")
        else:
            self.log.info("/dev/vfio empty before servicereport")

        verboseCmd = "servicereport -v -p spyre"
        result = process.run(
            verboseCmd, ignore_status=True, sudo=True, shell=True)
        output = str(result.stdout + result.stderr, "utf-8")

        if 'FAIL' in output:
            self.log.info("FAIL detected in -v -p spyre")
            spyreRepairCmd = "servicereport -r -p spyre"
            process.run(spyreRepairCmd, ignore_status=True,
                        sudo=True, shell=True)

            self.log.info("Re-running -v -p spyre after repair")
            result = process.run(
                verboseCmd, ignore_status=True, sudo=True, shell=True)
            output = str(result.stdout + result.stderr, "utf-8")

            if 'FAIL' in output:
                self.fail("FAIL still present after Spyre repair")

        if not (os.path.isdir('/dev/vfio') and any(e.isdigit() for e in os.listdir('/dev/vfio'))):
            self.fail("/dev/vfio not populated after servicereport")

        user = 'senuser'
        group = 'sentient'

        process.run(f"useradd {user}",
                    ignore_status=True, sudo=True, shell=True)
        process.run(f"echo '{user}:{user}' | chpasswd", sudo=True, shell=True)
        process.run(f"usermod -aG {group} {user}", sudo=True, shell=True)

        userCmd = f"su - {user} -c 'servicereport -v -p spyre'"
        result = process.run(userCmd, ignore_status=True,
                             sudo=True, shell=True)
        output = str(result.stdout + result.stderr, "utf-8")

        if 'FAIL' in output:
            self.fail("FAIL detected when running -v -p spyre as a non-root user")
