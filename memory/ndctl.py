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
# Copyright: 2019 IBM
# Author: Harish <harish@linux.vnet.ibm.com>

"""
Ndctl user space tooling for Linux, which handles NVDIMM devices.
This Suite works with various options of ndctl on a NVDIMM device.
"""

import os
import json
import glob
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils import archive
from avocado.utils import distro
from avocado.utils import build
from avocado.utils.software_manager import SoftwareManager


class NdctlTest(Test):

    """
    Ndctl user space tooling for Linux, which handles NVDIMM devices.

    """

    def get_json(self, option=''):
        """
        Get the json of each provided options

        return: By default returns entire detail of namespaces
        """
        try:
            json_op = json.loads(process.system_output(
                '%s list %s' % (self.binary, option), shell=True))
        except ValueError:
            json_op = []
        if option:
            vals = []
            for nid in json_op:
                vals.append(self.get_json_val(nid, self.opt_dict[option]))
            return vals
        return json_op

    @staticmethod
    def get_json_val(json_op, field):
        """
        Get the value of a field in given json
        """
        for key, value in json_op.iteritems():
            if key == field:
                return value
        return None

    @staticmethod
    def check_buses():
        """
        Get buses from sys subsystem to verify persisment devices exist
        """
        return glob.glob('/sys/bus/nd/drivers/nd_bus/ndbus*')

    def disable_region(self, name='all'):
        """
        Disable given region
        """
        if process.system('%s disable-region %s' % (self.binary, name),
                          shell=True, ignore_status=True):
            self.fail("Failed to disable %s region(s)" % name)

    def enable_region(self, name='all'):
        """
        Enable given region
        """
        if process.system('%s enable-region %s' % (self.binary, name),
                          shell=True, ignore_status=True):
            self.fail("Failed to enable %s region(s)" % name)

    def setUp(self):
        """
        Build 'ndctl' and setup the binary.
        """
        deps = []
        dist = distro.detect()
        self.package = self.params.get('package', default='upstream')

        if 'SuSE' not in dist.name:
            self.cancel('Unsupported OS %s' % dist.name)

        if not self.check_buses():
            self.cancel("Test needs atleast one region")

        if self.package == 'upstream':
            deps.extend(['gcc', 'make', 'automake', 'autoconf'])
            if dist.name == 'SuSE':
                deps.extend(['ruby2.5-rubygem-asciidoctor', 'libtool',
                             'libkmod-devel', 'libudev-devel',
                             'libuuid-devel-static', 'libjson-c-devel',
                             'systemd-devel', 'kmod-bash-completion'])

            locations = ["https://github.com/pmem/ndctl/archive/master.zip"]
            tarball = self.fetch_asset("ndctl.zip", locations=locations,
                                       expire='7d')
            archive.extract(tarball, self.teststmpdir)
            os.chdir("%s/ndctl-master" % self.teststmpdir)
            process.run('./autogen.sh', sudo=True, shell=True)
            process.run("./configure CFLAGS='-g -O2' --prefix=/usr "
                        "--sysconfdir=/etc --libdir="
                        "/usr/lib64", shell=True, sudo=True)
            build.make(".")
            self.binary = './ndctl/ndctl'
        else:
            deps.extend(['ndctl'])
            self.binary = 'ndctl'

        smm = SoftwareManager()
        for pkg in deps:
            if not smm.check_installed(pkg) and not \
                    smm.install(pkg):
                self.cancel('%s is needed for the test to be run' % pkg)
        self.opt_dict = {'-B': 'provider', '-D': 'dev', '-R': 'dev'}

    def test_bus_ids(self):
        """
        Test the bus id info
        """
        vals = self.get_json('-B')
        if not vals:
            self.fail('Failed to fetch bus IDs')
        self.log.info('Available Bus provider IDs: %s', vals)

    def test_dimms(self):
        """
        Test the dimms info
        """
        vals = self.get_json('-D')
        if not vals:
            self.fail('Failed to fetch DIMMs')
        self.log.info('Available DIMMs: %s', vals)

    def test_regions(self):
        """
        Test the regions info
        """
        self.disable_region()
        old = self.get_json('-R')
        self.enable_region()
        new = self.get_json('-R')
        if len(new) <= len(old):
            self.fail('Failed to fetch regions')
        self.log.info('Available regions: %s', new)


if __name__ == "__main__":
    main()
