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
# Copyright: 2020 IBM
# Author: Harish <harish@linux.vnet.ibm.com>

"""
Ndctl user space tooling for Linux, which handles NVDIMM devices.
This Suite works with various options of ndctl on a NVDIMM device.
"""

import os

import avocado
from avocado import Test
from avocado.utils import process
from avocado.utils import archive
from avocado.utils import distro
from avocado.utils import build
from avocado.utils import genio
from avocado.utils import pmem
from avocado.utils import cpu
from avocado.utils.software_manager import SoftwareManager


class NdctlDeviceTreeCheck(Test):
    """
    Ndctl Test to check numa associativity for pmem devices from device tree
    """
    @staticmethod
    def get_hex_list(filename):
        out = process.system_output('lsprop %s' %
                                    filename, shell=True).decode()
        values = "".join(out.replace('\t\t', '').split("\n")
                         [1:]).strip().split()
        return values

    def get_ref_point_index(self, legacy=False):
        path = "/proc/device-tree/rtas/ibm,associativity-reference-points"
        if legacy:
            path = "/proc/device-tree/ibm,opal/"\
                   "ibm,associativity-reference-points"
        val = self.get_hex_list(path)
        return int(val[0], 16)

    def get_node_id_from_associativity(self, assoc_ref_index, filename):
        values = self.get_hex_list(filename)
        return int(values[assoc_ref_index], 16)

    def parse_pmem_dt(self, ref_index, bus_id):
        dt_path = "/proc/device-tree/ibm,persistent-memory"
        path = os.path.join(dt_path, bus_id.split(':')[-1])
        node_id = self.get_node_id_from_associativity(ref_index,
                                                      '%s/ibm,associativi'
                                                      'ty' % path)
        return node_id

    def parse_legacy_dt(self, ref_index, provider):
        dt_path = "/proc/device-tree"
        path = os.path.join(dt_path, "nvdimm@%s" % provider.split(".")[0])
        node_id = self.get_node_id_from_associativity(ref_index,
                                                      '%s/ibm,associativi'
                                                      'ty' % path)
        return node_id

    def setUp(self):
        """
        Build 'ndctl' and setup the binary.
        """
        if "powerpc" not in cpu.get_cpu_arch():
            self.cancel("Test supported only on POWER arch")

        deps = []
        self.dist = distro.detect()
        self.package = self.params.get('package', default='distro')

        if self.dist.name not in ['SuSE', 'rhel']:
            self.cancel('Unsupported OS %s' % self.dist.name)

        self.smm = SoftwareManager()
        if self.package == 'upstream':
            deps.extend(['gcc', 'make', 'automake', 'autoconf'])
            if self.dist.name == 'SuSE':
                deps.extend(['libtool',
                             'libkmod-devel', 'libudev-devel', 'systemd-devel',
                             'libuuid-devel-static', 'libjson-c-devel',
                             'keyutils-devel', 'kmod-bash-completion'])
            elif self.dist.name == 'rhel':
                deps.extend(['libtool',
                             'kmod-devel', 'libuuid-devel', 'json-c-devel',
                             'systemd-devel', 'keyutils-libs-devel', 'jq',
                             'parted', 'libtool'])
            for pkg in deps:
                if not self.smm.check_installed(pkg) and not \
                        self.smm.install(pkg):
                    self.cancel('%s is needed for the test to be run' % pkg)

            locations = ["https://github.com/pmem/ndctl/archive/master.zip"]
            tarball = self.fetch_asset("ndctl.zip", locations=locations,
                                       expire='7d')
            archive.extract(tarball, self.teststmpdir)
            os.chdir("%s/ndctl-master" % self.teststmpdir)
            process.run('./autogen.sh', sudo=True, shell=True)
            process.run("./configure CFLAGS='-g -O2' --prefix=/usr "
                        "--disable-docs "
                        "--sysconfdir=/etc --libdir="
                        "/usr/lib64", shell=True, sudo=True)
            build.make(".")
            self.ndctl = os.path.abspath('./ndctl/ndctl')
            self.daxctl = os.path.abspath('./daxctl/daxctl')
        else:
            deps.extend(['ndctl'])
            if self.dist.name == 'rhel':
                deps.extend(['daxctl'])
            for pkg in deps:
                if not self.smm.check_installed(pkg) and not \
                        self.smm.install(pkg):
                    self.cancel('%s is needed for the test to be run' % pkg)
            self.ndctl = 'ndctl'
            self.daxctl = 'daxctl'

        self.plib = pmem.PMem(self.ndctl, self.daxctl)
        if not self.plib.check_buses():
            self.cancel("Test needs atleast one region")

    @avocado.fail_on(pmem.PMemException)
    def test(self):
        self.plib.enable_region()
        regions = self.plib.run_ndctl_list('-R')
        region = self.plib.run_ndctl_list_val(regions[0], 'dev')
        legacy = self.plib.is_region_legacy(region)
        buses = self.plib.run_ndctl_list('-RBN')
        failures = []
        assoc_ref_index = self.get_ref_point_index(legacy=legacy)
        for val in buses:
            region = self.plib.run_ndctl_list_val(val, 'regions')
            sys_id = self.plib.run_ndctl_list_val(region[0], 'dev')
            if legacy:
                # Use namespace level node for legacy h/w
                nss = self.plib.run_ndctl_list_val(region[0], 'namespaces')
                sys_id = self.plib.run_ndctl_list_val(nss[0], 'dev')
            node_path = '/sys/bus/nd/devices/%s/target_node' % sys_id
            if not os.path.exists(node_path):
                # Fallback to numa_node if target_node support does not exist
                node_path = '/sys/bus/nd/devices/%s/numa_node' % sys_id
            node = genio.read_one_line(node_path)

            provider = self.plib.run_ndctl_list_val(val, 'provider')
            if legacy:
                dt_node = str(self.parse_legacy_dt(assoc_ref_index, provider))
            else:
                dt_node = str(self.parse_pmem_dt(assoc_ref_index, provider))
            if node != dt_node:
                failures.append("%s associativity is wrong! "
                                "Exp:%s, Got:%s" % (sys_id, dt_node, node))
            else:
                self.log.info("Working as expected. "
                              "ndctl node: %s, DT node: %s", node, dt_node)
        if failures:
            self.fail(failures)

    @avocado.fail_on(pmem.PMemException)
    def tearDown(self):
        if hasattr(self, 'plib') and self.plib:
            self.plib.disable_region()
