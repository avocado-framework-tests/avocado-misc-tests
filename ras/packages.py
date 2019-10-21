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
from avocado import main
from avocado.utils import process
from avocado.utils import distro
from avocado.utils.software_manager import SoftwareManager


class Package_check(Test):

    def setUp(self):
        if "ppc" not in distro.detect().arch:
            self.cancel("supported only on Power platform")

        self.sm = SoftwareManager()
        self.packages = self.params.get(
            'packages', default=['powerpc-utils', 'ppc64-diag', 'lsvpd'])
        if 'PowerNV' in open('/proc/cpuinfo', 'r').read():
            self.packages.extend(['opal-prd'])

    def test(self):
        dist = distro.detect()
        is_fail = 0
        if dist.name == 'rhel':
            packages_rhel = self.params.get(
                'packages_rhel', default=['lshw', 'librtas'])
            self.packages.extend(packages_rhel)
            for package in self.packages:
                if "anaconda" in process.system_output("yum list installed "
                                                       "| grep %s | tail -1"
                                                       % package,
                                                       shell=True).decode("utf-8"):
                    self.log.info(
                        "%s package is installed by default" % package)
                else:
                    self.log.info(
                        "%s package is not installed by default" % package)
                    is_fail += 1
        elif dist.name == 'Ubuntu':
            packages_ubuntu = self.params.get(
                'packages_ubuntu', default=['librtas2'])
            self.packages.extend(packages_ubuntu)
            for package in self.packages:
                if process.system_output("apt-mark showauto %s" % package,
                                         shell=True):
                    self.log.info(
                        "%s package is installed by default" % package)
                else:
                    self.log.info(
                        "%s package is not installed by default" % package)
                    is_fail += 1
        else:
            for package in self.packages:
                if self.sm.check_installed(package):
                    self.log.info("%s package is installed" % package)
                else:
                    self.log.info("%s package is not installed" % package)
        if is_fail >= 1:
            self.fail("%s package(s) not installed by default" % is_fail)


if __name__ == "__main__":
    main()
