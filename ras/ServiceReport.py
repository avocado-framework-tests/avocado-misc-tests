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

from avocado import Test
from avocado.utils import process, build
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

    def test(self):
        os.chdir(self.sourcedir)
        cmd = "./servicereport %s" % self.options
        if process.system(cmd, ignore_status=True, sudo=True, shell=True):
            self.fail("ServiceReport: Failed command is: %s" % cmd)
