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
# Author: Pavithra <pavrampu@linux.vnet.ibm.com>

from avocado import Test
from avocado.utils import distro
from avocado.utils.software_manager.manager import SoftwareManager


class Package_check(Test):

    def setUp(self):
        if "ppc" not in distro.detect().arch:
            self.cancel("supported only on Power platform")

        self.sm = SoftwareManager()
        self.packages = self.params.get(
            'packages', default=['powerpc-utils', 'ppc64-diag', 'lsvpd', 'powerpc-utils-core'])
        if 'PowerNV' in open('/proc/cpuinfo', 'r').read():
            self.packages.extend(['opal-prd'])

    def test(self):
        dist = distro.detect()
        if dist.name == 'rhel':
            packages_rhel = self.params.get(
                'packages_rhel', default=['lshw', 'librtas'])
            self.packages.extend(packages_rhel)
        elif dist.name == 'Ubuntu':
            packages_ubuntu = self.params.get(
                'packages_ubuntu', default=['librtas2'])
            self.packages.extend(packages_ubuntu)
        not_installed_list = []
        for package in self.packages:
            if self.sm.check_installed(package):
                self.log.info("%s package is installed" % package)
            else:
                not_installed_list.append(package)
        if not_installed_list:
            self.fail("%s packages not installed by default" % not_installed_list)
