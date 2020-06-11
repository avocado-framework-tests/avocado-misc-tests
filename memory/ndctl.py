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
import re
import shutil
import json

import avocado
from avocado import Test
from avocado.utils import process
from avocado.utils import archive
from avocado.utils import distro
from avocado.utils import build
from avocado.utils import genio
from avocado.utils import memory
from avocado.utils import partition
from avocado.utils import pmem
from avocado.utils.software_manager import SoftwareManager


class NdctlTest(Test):

    """
    Ndctl user space tooling for Linux, which handles NVDIMM devices.
    """

    def get_default_region(self):
        """
        Get the largest region if not provided
        """
        self.plib.enable_region()
        region = self.params.get('region', default=None)
        if region:
            return region
        regions = self.plib.run_ndctl_list('-R')
        regions = sorted(regions, key=lambda i: i['size'], reverse=True)
        return self.plib.run_ndctl_list_val(regions[0], 'dev')

    def get_unsupported_alignval(self):
        """
        Return unsupported size align based on platform
        """
        align = self.get_size_alignval()
        if align == self.align_val['hash']:
            return self.align_val['radix']
        else:
            return self.align_val['hash']

    def get_size_alignval(self):
        """
        Return the size align restriction based on platform
        """
        self.align_val = {'hash': 16777216, 'radix': 2097152}
        if 'Hash' in genio.read_file('/proc/cpuinfo').rstrip('\t\r\n\0'):
            def_align = self.align_val['hash']
        else:
            def_align = self.align_val['radix']
        return def_align

    def build_fio(self):
        """
        Install fio or build if not possible
        """
        pkg = "fio"
        if process.system("which %s" % pkg, ignore_status=True):
            if not self.smm.check_installed(pkg) \
                    and not self.smm.install(pkg):
                for package in ["autoconf", "libtool", "make"]:
                    if not self.smm.check_installed(package) \
                            and not self.smm.install(package):
                        self.cancel(
                            "Fail to install %s required for this test."
                            "" % package)
                tarball = self.fetch_asset(
                    "http://brick.kernel.dk/snaps/fio-2.1.10.tar.gz")
                archive.extract(tarball, self.teststmpdir)
                fio_version = os.path.basename(tarball.split('.tar.')[0])
                sourcedir = os.path.join(self.teststmpdir, fio_version)
                build.make(sourcedir)
                return os.path.join(sourcedir, "fio")
        return pkg

    def setUp(self):
        """
        Build 'ndctl' and setup the binary.
        """
        deps = []
        self.dist = distro.detect()
        self.package = self.params.get('package', default='upstream')
        self.preserve_setup = self.params.get('preserve_change', default=False)
        self.mode_to_use = self.params.get('modes', default='fsdax')

        if self.dist.name not in ['SuSE', 'rhel']:
            self.cancel('Unsupported OS %s' % self.dist.name)

        # DAX wont work with reflink, disabling here
        self.reflink = '-m reflink=0'
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

            git_branch = self.params.get('git_branch', default='pending')
            location = "https://github.com/pmem/ndctl/archive/"
            location = location + git_branch + ".zip"
            tarball = self.fetch_asset("ndctl.zip", locations=location,
                                       expire='7d')
            archive.extract(tarball, self.teststmpdir)
            os.chdir("%s/ndctl-%s" % (self.teststmpdir, git_branch))
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

        self.opt_dict = {'-B': 'provider',
                         '-D': 'dev', '-R': 'dev', '-N': 'dev'}
        self.modes = ['raw', 'sector', 'fsdax', 'devdax']
        self.part = None
        self.disk = None
        self.plib = pmem.PMem(self.ndctl, self.daxctl)
        if not self.plib.check_buses():
            self.cancel("Test needs atleast one region")

    @avocado.fail_on(pmem.PMemException)
    def test_bus_ids(self):
        """
        Test the bus id info
        """
        vals = self.plib.run_ndctl_list('-B')
        if not vals:
            self.fail('Failed to fetch bus IDs')
        self.log.info('Available Bus provider IDs: %s', vals)

    @avocado.fail_on(pmem.PMemException)
    def test_dimms(self):
        """
        Test the dimms info
        """
        vals = self.plib.run_ndctl_list('-D')
        if not vals:
            self.fail('Failed to fetch DIMMs')
        self.log.info('Available DIMMs: %s', vals)

    @avocado.fail_on(pmem.PMemException)
    def test_regions(self):
        """
        Test the regions info
        """
        self.plib.disable_region()
        old = self.plib.run_ndctl_list('-R')
        self.plib.enable_region()
        new = self.plib.run_ndctl_list('-R')
        if len(new) <= len(old):
            self.fail('Failed to fetch regions')
        self.log.info('Available regions: %s', new)

    @avocado.fail_on(pmem.PMemException)
    def test_namespace(self):
        """
        Test namespace
        """
        self.plib.enable_region()
        regions = self.plib.run_ndctl_list('-R')
        for val in regions:
            region = self.plib.run_ndctl_list_val(val, 'dev')
            self.plib.disable_namespace(region=region)
            self.plib.destroy_namespace(region=region)
            self.plib.create_namespace(region=region)

        namespaces = self.plib.run_ndctl_list('-N')
        self.log.info('Created namespace %s', namespaces)

    @avocado.fail_on(pmem.PMemException)
    def test_disable_enable_ns(self):
        """
        Test enable disable namespace
        """
        region = self.get_default_region()
        if (not self.plib.is_region_legacy(region)):
            for _ in range(0, 3):
                self.plib.create_namespace(region=region, size='128M')
        namespaces = self.plib.run_ndctl_list('-N')
        ns_names = []
        for ns in namespaces:
            ns_names.append(self.plib.run_ndctl_list_val(ns, 'dev'))
        ns_names.append('all')

        for namespace in ns_names:
            self.plib.disable_namespace(namespace=namespace)
            self.plib.enable_namespace(namespace=namespace)

    @avocado.fail_on(pmem.PMemException)
    def test_namespace_modes(self):
        """
        Create  different namespace types
        """
        failed_modes = []
        region = self.get_default_region()
        self.log.info("Using %s for different namespace modes", region)
        self.plib.disable_namespace(region=region)
        self.plib.destroy_namespace(region=region)
        for mode in self.modes:
            self.plib.create_namespace(region=region, mode=mode)
            ns_json = self.plib.run_ndctl_list('-r %s -N' % region)[0]
            created_mode = self.plib.run_ndctl_list_val(ns_json, 'mode')
            if mode != created_mode:
                failed_modes.append(mode)
                self.log.error("Expected mode %s, Got %s", mode, created_mode)
            else:
                self.log.info("Namespace with %s mode: %s", mode, ns_json)
            ns_name = self.plib.run_ndctl_list_val(ns_json, 'dev')
            self.plib.disable_namespace(namespace=ns_name, region=region)
            self.plib.destroy_namespace(namespace=ns_name, region=region)

        if failed_modes:
            self.fail("Namespace for %s mode failed!" % failed_modes)

    @avocado.fail_on(pmem.PMemException)
    def test_namespace_devmap(self):
        """
        Test metadata device mapping option with a namespace
        """
        region = self.get_default_region()
        m_map = self.params.get('map', default='mem')
        self.log.info("Using %s for checking device mapping", region)
        self.plib.disable_namespace(region=region)
        self.plib.destroy_namespace(region=region)
        self.plib.create_namespace(region=region, mode=self.mode_to_use,
                                   memmap=m_map)
        self.log.info("Validating device mapping")
        map_val = self.plib.run_ndctl_list_val(self.plib.run_ndctl_list(
            '-r %s -N' % region)[0], 'map')
        if map_val != m_map:
            self.fail("Expected map:%s, Got %s" % (m_map, map_val))
        else:
            self.log.info("Metadata mapped as expected")

    def multiple_namespaces_region(self, region):
        """
        Test multiple namespace with single region
        """
        namespace_size = self.params.get('size', default=None)
        size_align = self.get_size_alignval()
        slot_count = self.plib.get_slot_count(region)
        self.log.info("Using %s for muliple namespace regions", region)
        self.plib.disable_namespace(region=region)
        self.plib.destroy_namespace(region=region)
        if namespace_size and ((namespace_size % size_align) != 0):
            self.cancel("Size value not %d aligned %d \n",
                        size_align, namespace_size)

        region_size = self.plib.run_ndctl_list_val(self.plib.run_ndctl_list(
            '-r %s' % region)[0], 'size')
        if not namespace_size:
            namespace_size = region_size // slot_count
            # Now align the namespace size
            namespace_size = (namespace_size // size_align) * size_align
        else:
            slot_count = region_size // namespace_size

        self.log.info("Creating %s namespaces", slot_count)
        for count in range(0, slot_count):
            self.plib.create_namespace(
                region=region, mode=self.mode_to_use, size=namespace_size)
            self.log.info("Namespace %s created", count + 1)

    @avocado.fail_on(pmem.PMemException)
    def test_multiple_namespaces_region(self):
        """
        Test multiple namespace with single region
        """
        region = self.get_default_region()
        if (self.plib.is_region_legacy(region)):
            self.cancel("Legacy config skipping the test")
        self.multiple_namespaces_region(region)

    @avocado.fail_on(pmem.PMemException)
    def test_multiple_ns_multiple_region(self):
        """
        Test multiple namespace with multiple region
        """
        self.plib.enable_region()
        if len(self.plib.run_ndctl_list('-R')) <= 1:
            self.cancel("Test not applicable without multiple regions")
        regions = self.plib.run_ndctl_list('-R')
        self.plib.disable_namespace()
        self.plib.destroy_namespace()
        for val in regions:
            region = self.plib.run_ndctl_list_val(val, 'dev')
            if (self.plib.is_region_legacy(region)):
                self.cancel("Legacy config skipping the test")
            self.multiple_namespaces_region(region)

    @avocado.fail_on(pmem.PMemException)
    def test_multiple_ns_modes_region(self):
        """
        Test multiple namespace modes with single region
        """
        region = self.get_default_region()
        if (self.plib.is_region_legacy(region)):
            self.cancel("Legacy config skipping the test")
        self.log.info("Using %s for muliple namespace regions", region)
        self.plib.disable_namespace(region=region)
        self.plib.destroy_namespace(region=region)
        size = self.plib.run_ndctl_list_val(self.plib.run_ndctl_list(
            '-r %s' % region)[0], 'size')
        if size < (len(self.modes) * 64 * 1024 * 1024):
            self.cancel('Not enough memory to create namespaces')
        for mode in self.modes:
            self.plib.create_namespace(
                region=region, mode=mode, size='64M')
            self.log.info("Namespace of type %s created", mode)

    @avocado.fail_on(pmem.PMemException)
    def test_nslot_namespace(self):
        """
        Test max namespace with nslot value
        """
        region = self.get_default_region()
        if (self.plib.is_region_legacy(region)):
            self.cancel("Legacy config skipping the test")
        size_align = self.get_size_alignval()
        slot_count = self.plib.get_slot_count(region)
        self.log.info("Using %s for max namespace creation", region)
        self.plib.disable_namespace()
        self.plib.destroy_namespace()
        region_size = self.plib.run_ndctl_list_val(self.plib.run_ndctl_list(
            '-r %s' % region)[0], 'size')
        namespace_size = region_size // slot_count
        # Now align the namespace size
        namespace_size = (namespace_size // size_align) * size_align

        self.log.info("Creating %s namespace", slot_count)
        for count in range(0, slot_count):
            self.plib.create_namespace(region=region, mode='fsdax',
                                       size=namespace_size)
            self.log.info("Namespace %s created", count)

    @avocado.fail_on(pmem.PMemException)
    def test_namespace_reconfigure(self):
        """
        Test namespace reconfiguration
        """
        region = self.get_default_region()
        self.log.info("Using %s for reconfiguring namespace", region)
        self.plib.disable_namespace()
        self.plib.destroy_namespace()
        self.plib.create_namespace(region=region, mode='fsdax', align='64k')
        old_ns = self.plib.run_ndctl_list()[0]
        old_ns_dev = self.plib.run_ndctl_list_val(old_ns, 'dev')
        self.log.info("Re-configuring namespace %s", old_ns_dev)
        self.plib.create_namespace(region=region, mode='fsdax', name='test_ns',
                                   reconfig=old_ns_dev, force=True)
        new_ns = self.plib.run_ndctl_list()[0]
        self.log.info("Checking namespace changes")
        failed_vals = []
        for key, val in new_ns.items():
            if key in list(set(old_ns.keys()) - set(['uuid', 'dev'])):
                if old_ns[key] != val:
                    failed_vals.append({key: val})
            else:
                self.log.info("Newly added filed %s:%s", key, val)
        if failed_vals:
            self.fail("New namespace unexpected change(s): %s" % failed_vals)

    @avocado.fail_on(pmem.PMemException)
    def test_check_namespace(self):
        """
        Verify metadata for sector mode namespaces
        """
        region = self.get_default_region()
        self.plib.disable_namespace()
        self.plib.destroy_namespace()
        self.log.info("Creating sector namespace using %s", region)
        self.plib.create_namespace(region=region, mode='sector')
        ns_sec_dev = self.plib.run_ndctl_list_val(self.plib.run_ndctl_list()[0], 'dev')
        self.plib.disable_namespace(namespace=ns_sec_dev)
        self.log.info("Checking BTT metadata")
        if process.system("%s check-namespace %s" % (self.ndctl, ns_sec_dev),
                          ignore_status=True):
            self.fail("Failed to check namespace metadata")

    @avocado.fail_on(pmem.PMemException)
    def test_check_numa(self):
        self.plib.enable_region()
        regions = self.plib.run_ndctl_list('-R')
        if not os.path.exists('/sys/bus/nd/devices/region0/numa_node'):
            self.fail("Numa node entries not found!")
        for val in regions:
            reg = self.plib.run_ndctl_list_val(val, 'dev')
            numa = genio.read_one_line('/sys/bus/nd/devices/%s/numa_node' % reg)
            # Check numa config in ndctl and sys interface
            if len(self.plib.run_ndctl_list('-r %s -R -U %s' % (reg, numa))) != 1:
                self.fail('Region mismatch between ndctl and sys interface')

    @avocado.fail_on(pmem.PMemException)
    def test_check_ns_numa(self):
        self.plib.enable_region()
        regions = self.plib.run_ndctl_list('-R')
        for dev in regions:
            region = self.plib.run_ndctl_list_val(dev, 'dev')
            if not self.plib.is_region_legacy(region):
                self.plib.disable_namespace(region=region)
                self.plib.destroy_namespace(region=region)
                for _ in range(3):
                    self.plib.create_namespace(
                        region=region, mode='fsdax', size='128M')

            namespaces = self.plib.run_ndctl_list('-N -r %s' % region)
            if not os.path.exists('/sys/bus/nd/devices/namespace0.0/numa_node'):
                self.fail("Numa node entries not found!")
            for val in namespaces:
                ns_name = self.plib.run_ndctl_list_val(val, 'dev')
                numa = genio.read_one_line(
                    '/sys/bus/nd/devices/%s/numa_node' % ns_name)
                # Check numa config in ndctl and sys interface
                if len(self.plib.run_ndctl_list('-N -n %s -U %s' % (ns_name, numa))) != 1:
                    self.fail('Numa mismatch between ndctl and sys interface')

    @avocado.fail_on(pmem.PMemException)
    def test_label_read_write(self):
        region = self.get_default_region()
        if (self.plib.is_region_legacy(region)):
            self.cancel("Legacy config skipping the test")

        nmem = "nmem%s" % re.findall(r'\d+', region)[0]
        self.log.info("Using %s for testing labels", region)
        self.plib.disable_region(name=region)
        self.log.info("Filling zeros to start test")
        if process.system('%s zero-labels %s' % (self.ndctl, nmem), shell=True):
            self.fail("Label zero-fill failed")

        self.plib.enable_region(name=region)
        self.plib.create_namespace(region=region)
        self.log.info("Storing labels with a namespace")
        old_op = process.system_output(
            '%s check-labels %s' % (self.ndctl, nmem), shell=True)
        if process.system('%s read-labels %s -o output' % (self.ndctl, nmem), shell=True):
            self.fail("Label read failed")

        self.log.info("Refilling zeroes before a restore")
        self.plib.disable_namespace(region=region)
        self.plib.destroy_namespace(region=region)
        self.plib.disable_region(name=region)
        if process.system('%s zero-labels %s' % (self.ndctl, nmem), shell=True):
            self.fail("Label zero-fill failed after read")

        self.log.info("Re-storing labels with a namespace")
        if process.system('%s write-labels %s -i output' % (self.ndctl, nmem), shell=True):
            self.fail("Label write failed")
        self.plib.enable_region(name=region)

        self.log.info("Checking mismatch after restore")
        new_op = process.system_output(
            '%s check-labels %s' % (self.ndctl, nmem), shell=True)
        if new_op != old_op:
            self.fail("Label read and write mismatch")

        self.log.info("Checking created namespace after restore")
        if len(self.plib.run_ndctl_list('-N -r %s' % region)) != 1:
            self.fail("Created namespace not found after label restore")

    @avocado.fail_on(pmem.PMemException)
    def test_daxctl_list(self):
        """
        Test daxctl list
        """
        region = self.get_default_region()
        self.plib.disable_namespace(region=region)
        self.plib.destroy_namespace(region=region)
        self.plib.create_namespace(region=region, mode='devdax')
        index = re.findall(r'\d+', region)[0]
        vals = self.plib.run_daxctl_list('-r %s' % (index))
        if len(vals) != 1:
            self.fail('Failed daxctl list')
        self.log.info('Created dax device %s', vals)

    @avocado.fail_on(pmem.PMemException)
    def test_region_capabilities(self):
        """
        Test region capabilities
        """
        self.plib.enable_region()
        self.plib.disable_namespace()
        self.plib.destroy_namespace()
        regions = self.plib.run_ndctl_list('-R -C')
        for region in regions:
            cap = self.plib.run_ndctl_list_val(region, 'capabilities')
            sec_sizes = []
            fsdax_align = []
            devdax_align = []
            for typ in cap:
                mode = self.plib.run_ndctl_list_val(typ, 'mode')
                if mode == 'fsdax':
                    fsdax_align = self.plib.run_ndctl_list_val(
                        typ, 'alignments')
                elif mode == 'devdax':
                    devdax_align = self.plib.run_ndctl_list_val(
                        typ, 'alignments')
                elif mode == 'sector':
                    sec_sizes = self.plib.run_ndctl_list_val(
                        typ, 'sector_sizes')
            reg_name = self.plib.run_ndctl_list_val(region, 'dev')
            self.log.info("Creating namespaces with possible sizes")
            for size in sec_sizes:
                self.plib.create_namespace(
                    region=reg_name, mode='sector', sector_size=size)
                self.plib.destroy_namespace(region=reg_name, force=True)
            for size in fsdax_align:
                self.plib.create_namespace(
                    region=reg_name, mode='fsdax', align=size)
                self.plib.destroy_namespace(region=reg_name, force=True)
            for size in devdax_align:
                self.plib.create_namespace(
                    region=reg_name, mode='devdax', align=size)
                self.plib.destroy_namespace(region=reg_name, force=True)

    @avocado.fail_on(pmem.PMemException)
    def write_infoblock(self, ns_name, align):
        """
        Write_infoblock on given namespace
        """
        if not self.plib.check_ndctl_subcmd("write-infoblock"):
            self.cancel("Binary does not support write-infoblock")
        write_cmd = "%s write-infoblock --align %s -m devdax "\
                    "%s" % (self.ndctl, align, ns_name)
        if process.system(write_cmd, ignore_status=True):
            self.fail("write-infoblock command failed")
        read_cmd = "%s read-infoblock -j %s" % (self.ndctl, ns_name)
        read_out = process.system_output(read_cmd, ignore_status=True).decode()
        read_out = json.loads(read_out)
        if align != int(self.plib.run_ndctl_list_val(read_out[0], 'align')):
            self.fail("Alignment has not changed")

    @avocado.fail_on(pmem.PMemException)
    def test_write_infoblock(self):
        """
        Test write_infoblock with align size
        """
        region = self.get_default_region()
        self.plib.disable_namespace(region=region)
        self.plib.destroy_namespace(region=region)
        self.plib.create_namespace(region=region, mode='devdax')
        ns_name = self.plib.run_ndctl_list_val(
            self.plib.run_ndctl_list("-N -r %s" % region)[0], 'dev')
        self.plib.disable_namespace(namespace=ns_name)
        self.write_infoblock(ns_name, self.get_size_alignval())
        self.plib.enable_namespace(namespace=ns_name)

    @avocado.fail_on(pmem.PMemException)
    def test_write_infoblock_negate(self):
        """
        Test write_infoblock with unsupported align size
        """
        region = self.get_default_region()
        self.plib.disable_namespace(region=region)
        self.plib.destroy_namespace(region=region)
        self.plib.create_namespace(region=region, mode='devdax')
        ns_name = self.plib.run_ndctl_list_val(
            self.plib.run_ndctl_list("-N -r %s" % region)[0], 'dev')
        self.plib.disable_namespace(namespace=ns_name)
        self.write_infoblock(ns_name, self.get_unsupported_alignval())
        failed = False
        found = False
        try:
            self.plib.enable_namespace(namespace=ns_name)
        except pmem.PMemException:
            self.log.info("Failed as expected")
            failed = True
        if not failed:
            self.log.info(self.plib.run_ndctl_list())
            self.fail("Enabling namespace must have failed")

        idle_ns = self.plib.run_ndctl_list('-Ni -r %s' % region)
        if len(idle_ns) > 1:
            for namespace in idle_ns:
                if int(self.plib.run_ndctl_list_val(namespace, 'size')) != 0:
                    found = True
                    break
        else:
            self.fail("Created namespace is not found")
        if not found:
            self.fail("Namespace with infoblock written not found")

        self.plib.destroy_namespace(namespace=ns_name, force=True)

    @avocado.fail_on(pmem.PMemException)
    def test_sector_write(self):
        """
        Test write on a sector mode device
        """
        region = self.get_default_region()
        self.plib.disable_namespace(region=region)
        self.plib.destroy_namespace(region=region)
        self.plib.create_namespace(region=region, mode='sector',
                                   sector_size='512')
        self.disk = '/dev/%s' % self.plib.run_ndctl_list_val(
            self.plib.run_ndctl_list("-N -r %s" % region)[0], 'blockdev')
        size = self.plib.run_ndctl_list_val(self.plib.run_ndctl_list(
            "-N -r %s" % region)[0], 'size')
        self.part = partition.Partition(self.disk)
        self.part.mkfs(fstype='xfs', args='-b size=%s -s size=512' %
                       memory.get_page_size())
        mnt_path = self.params.get('mnt_point', default='/pmemS')
        if not os.path.exists(mnt_path):
            os.makedirs(mnt_path)
        self.part.mount(mountpoint=mnt_path)
        self.log.info("Test will run on %s", mnt_path)
        fio_job = self.params.get('fio_job', default='sector-fio.job')
        cmd = '%s --directory %s --filename mmap-pmem --size %s %s' % (
            self.build_fio(), mnt_path, size // 2, self.get_data(fio_job))
        if process.system(cmd, ignore_status=True):
            self.fail("FIO mmap workload on fsdax failed")

    @avocado.fail_on(pmem.PMemException)
    def test_fsdax_write(self):
        """
        Test filesystem DAX with a FIO workload
        """
        region = self.get_default_region()
        self.plib.create_namespace(region=region, mode='fsdax')
        self.disk = '/dev/%s' % self.plib.run_ndctl_list_val(
            self.plib.run_ndctl_list("-N -r %s" % region)[0], 'blockdev')
        size = self.plib.run_ndctl_list_val(self.plib.run_ndctl_list(
            "-N -r %s" % region)[0], 'size')
        self.part = partition.Partition(self.disk)
        self.part.mkfs(fstype='xfs', args='-b size=%s -s size=512 %s' %
                       (memory.get_page_size(), self.reflink))
        mnt_path = self.params.get('mnt_point', default='/pmem')
        if not os.path.exists(mnt_path):
            os.makedirs(mnt_path)
        self.part.mount(mountpoint=mnt_path, args='-o dax')
        self.log.info("Test will run on %s", mnt_path)
        fio_job = self.params.get('fio_job', default='ndctl-fio.job')
        cmd = '%s --directory %s --filename mmap-pmem --size %s %s' % (
            self.build_fio(), mnt_path, size // 2, self.get_data(fio_job))
        if process.system(cmd, ignore_status=True):
            self.fail("FIO mmap workload on fsdax failed")

    @avocado.fail_on(pmem.PMemException)
    def test_map_sync(self):
        """
        Test MAP_SYNC flag with sample mmap write
        """
        region = self.get_default_region()
        self.plib.create_namespace(region=region, mode='fsdax')
        self.disk = '/dev/%s' % self.plib.run_ndctl_list_val(
            self.plib.run_ndctl_list("-N -r %s" % region)[0], 'blockdev')
        self.part = partition.Partition(self.disk)
        self.part.mkfs(fstype='xfs', args='-b size=%s -s size=512 %s' %
                       (memory.get_page_size(), self.reflink))
        mnt_path = self.params.get('mnt_point', default='/pmem_map')
        if not os.path.exists(mnt_path):
            os.makedirs(mnt_path)
        self.part.mount(mountpoint=mnt_path, args='-o dax')
        self.log.info("Testing MAP_SYNC on %s", mnt_path)
        src_file = os.path.join(self.teststmpdir, 'map_sync.c')
        shutil.copyfile(self.get_data('map_sync.c'), src_file)
        process.system('gcc %s -o map_sync' % src_file)
        process.system('fallocate -l 64k %s/new_file' % mnt_path)
        if process.system('./map_sync %s/new_file' % mnt_path, ignore_status=True):
            self.fail('Write with MAP_SYNC flag failed')

    @avocado.fail_on(pmem.PMemException)
    def test_devdax_write(self):
        """
        Test device DAX with a daxio binary
        """
        region = self.get_default_region()
        self.plib.create_namespace(region=region, mode='devdax')
        daxdev = "/dev/%s" % self.plib.run_ndctl_list_val(
            self.plib.run_ndctl_list("-N -r %s" % region)[0], 'chardev')
        if process.system("%s -b no -i /dev/urandom -o %s" % (self.get_data("daxio.static"), daxdev), ignore_status=True):
            self.fail("DAXIO write on devdax failed")

    @avocado.fail_on(pmem.PMemException)
    def tearDown(self):
        if self.part:
            self.part.unmount()
        if self.disk:
            self.log.info("Removing the FS meta created on %s", self.disk)
            delete_fs = "dd if=/dev/zero bs=1M count=1024 of=%s" % self.disk
            if process.system(delete_fs, shell=True, ignore_status=True):
                self.fail("Failed to delete filesystem on %s" % self.disk)

        if not self.preserve_setup:
            if self.plib.run_ndctl_list('-N'):
                self.plib.destroy_namespace(force=True)
            self.plib.disable_region()
