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
import json
import glob
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils import archive
from avocado.utils import distro
from avocado.utils import build
from avocado.utils import genio
from avocado.utils.software_manager import SoftwareManager


class NdctlTest(Test):

    """
    Ndctl user space tooling for Linux, which handles NVDIMM devices.

    """

    def get_json(self, short_opt='', long_opt=''):
        """
        Get the json of each provided options

        return: By default returns entire list of json objects
        return: Empty list is no output is empty
        """
        if short_opt:
            option = short_opt
        elif long_opt:
            option = long_opt
        else:
            option = ''
        try:
            json_op = json.loads(process.system_output(
                '%s list %s' % (self.binary, option), shell=True))
        except ValueError:
            json_op = []
        if short_opt:
            vals = []
            for nid in json_op:
                vals.append(self.get_json_val(nid, self.opt_dict[short_opt]))
            return vals
        return json_op

    @staticmethod
    def get_json_val(json_op, field):
        """
        Get the value of a field in given json
        """
        for key, value in json_op.items():
            if key == field:
                return value
        return None

    def get_aligned_count(self, size):
        """
        Return count based on default alignemnt
        """
        if 'Hash' in genio.read_file('/proc/cpuinfo').rstrip('\t\r\n\0'):
            def_align = 16 * 1024 * 1024
        else:
            def_align = 2 * 1024 * 1024
        if ((size // self.cnt) % def_align) != 0:
            self.log.warn("Namespace would fail as it is not %sM "
                          "aligned! Changing the number of "
                          "namespaces", def_align // (1024 * 1024))
            for count in range(self.cnt, 1, -1):
                if ((size // count) % def_align) == 0:
                    self.log.info("Changing namespaces to %s", count)
                    return count
        return self.cnt

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

    def disable_namespace(self, namespace='all', region='', bus='',
                          force=False):
        """
        Disable namepsaces
        """
        args = namespace
        if region:
            args = '%s -r %s' % (args, region)
        if bus:
            args = '%s -b %s' % (args, bus)
        if force:
            args = '%s -f' % args

        if process.system('%s disable-namespace %s' % (self.binary, args),
                          shell=True, ignore_status=True):
            self.fail('Namespace disble command failed')

    def create_namespace(self, region='', bus='', n_type='pmem', mode='fsdax',
                         memmap='dev', name='', size='', uuid='',
                         sector_size='', align='', reconfig='', force=False,
                         autolabel=False):
        """
        Creates namespace with specified options
        """
        args_dict = {region: '-r', bus: '-b', name: '-n', size: '-s',
                     uuid: '-u', sector_size: '-l', align: '-a',
                     reconfig: '-e'}
        minor_dict = {force: '-f', autolabel: '-L'}
        args = '-t %s -m %s ' % (n_type, mode)

        if mode in ['fsdax', 'devdax']:
            args += ' -M %s' % memmap
        for option in list(args_dict.keys()):
            if option:
                args += ' %s %s' % (args_dict[option], option)
        for option in list(minor_dict.keys()):
            if option:
                args += ' %s' % minor_dict[option]

        if process.system('%s create-namespace %s' % (self.binary, args),
                          shell=True, ignore_status=True):
            self.fail('Namespace create command failed')

    def destroy_namespace(self, namespace='all', region='', bus='',
                          force=False):
        """
        Destroy namepsaces
        """
        args = namespace
        args_dict = {region: '-r', bus: '-b'}
        for option in list(args_dict.keys()):
            if option:
                args += ' %s %s' % (args_dict[option], option)
        if force:
            args += ' -f'

        if process.system('%s destroy-namespace %s' % (self.binary, args),
                          shell=True, ignore_status=True):
            self.fail('Namespace destroy command failed')

    def setUp(self):
        """
        Build 'ndctl' and setup the binary.
        """
        deps = []
        self.dist = distro.detect()
        self.package = self.params.get('package', default='upstream')
        self.cnt = self.params.get('namespace_cnt', default=4)
        self.preserve_setup = self.params.get('preserve_change', default=False)
        self.size = self.params.get('size', default=None)
        self.mode_to_use = self.params.get('modes', default='fsdax')

        if 'SuSE' not in self.dist.name:
            self.cancel('Unsupported OS %s' % self.dist.name)

        if not self.check_buses():
            self.cancel("Test needs atleast one region")

        if self.package == 'upstream':
            deps.extend(['gcc', 'make', 'automake', 'autoconf'])
            if self.dist.name == 'SuSE':
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
        self.opt_dict = {'-B': 'provider',
                         '-D': 'dev', '-R': 'dev', '-N': 'dev'}
        self.modes = ['raw', 'fsdax', 'devdax']
        if self.dist.arch != 'ppc64le':
            self.modes.extend(['blk'])

    def test_bus_ids(self):
        """
        Test the bus id info
        """
        vals = self.get_json(short_opt='-B')
        if not vals:
            self.fail('Failed to fetch bus IDs')
        self.log.info('Available Bus provider IDs: %s', vals)

    def test_dimms(self):
        """
        Test the dimms info
        """
        vals = self.get_json(short_opt='-D')
        if not vals:
            self.fail('Failed to fetch DIMMs')
        self.log.info('Available DIMMs: %s', vals)

    def test_regions(self):
        """
        Test the regions info
        """
        self.disable_region()
        old = self.get_json(short_opt='-R')
        self.enable_region()
        new = self.get_json(short_opt='-R')
        if len(new) <= len(old):
            self.fail('Failed to fetch regions')
        self.log.info('Available regions: %s', new)

    def test_namespace(self):
        """
        Test namespace
        """
        self.enable_region()
        regions = self.get_json(short_opt='-R')
        for region in regions:
            self.disable_namespace(region=region)
            self.destroy_namespace(region=region)
            self.create_namespace(region=region)

        namespaces = self.get_json(short_opt='-N')
        self.log.info('Created namespace %s', namespaces)

    def test_namespace_modes(self):
        """
        Create  different namespace types
        """
        failed_modes = []
        self.enable_region()
        region = self.params.get('region', default=None)
        if not region:
            region = self.get_json(short_opt='-R')[0]
        self.log.info("Using %s for different namespace modes", region)
        self.disable_namespace(region=region)
        self.destroy_namespace(region=region)
        for mode in self.modes:
            self.create_namespace(region=region, mode=mode)
            ns_json = self.get_json()[0]
            created_mode = self.get_json_val(ns_json, 'mode')
            if mode != created_mode:
                failed_modes.append(mode)
                self.log.error("Expected mode %s, Got %s", mode, created_mode)
            else:
                self.log.info("Namespace with %s mode: %s" % (mode, ns_json))
            ns_name = self.get_json_val(ns_json, 'dev')
            self.disable_namespace(namespace=ns_name, region=region)
            self.destroy_namespace(namespace=ns_name, region=region)

        if failed_modes:
            self.fail("Namespace for %s mode failed!" % failed_modes)

    def test_multiple_namespaces_region(self):
        """
        Test multiple namespace with single region
        """
        self.enable_region()
        region = self.params.get('region', default=None)
        if not region:
            region = self.get_json(short_opt='-R')[0]
        self.log.info("Using %s for muliple namespace regions", region)
        self.disable_namespace(region=region)
        self.destroy_namespace(region=region)
        self.log.info("Creating %s namespaces", self.cnt)
        if not self.size:
            self.size = self.get_json_val(self.get_json(
                long_opt='-r %s' % region)[0], 'size')
            ch_cnt = self.get_aligned_count(self.size)
            self.size = self.size // ch_cnt
        else:
            # Assuming self.cnt is aligned
            ch_cnt = self.cnt
        for nid in range(0, ch_cnt):
            self.create_namespace(
                region=region, mode=self.mode_to_use, size=self.size)
            self.log.info("Namespace %s created", nid + 1)

    def test_multiple_ns_modes_region(self):
        """
        Test multiple namespace modes with single region
        """
        self.enable_region()
        region = self.params.get('region', default=None)
        if not region:
            region = self.get_json(short_opt='-R')[0]
        self.log.info("Using %s for muliple namespace regions", region)
        self.disable_namespace(region=region)
        self.destroy_namespace(region=region)
        size = self.get_json_val(self.get_json(
            long_opt='-r %s' % region)[0], 'size')
        if size < (len(self.modes) * 64 * 1024 * 1024):
            self.cancel('Not enough memory to create namespaces')
        for mode in self.modes:
            self.create_namespace(
                region=region, mode=mode, size='64M')
            self.log.info("Namespace of type %s created", mode)

    def test_multiple_ns_multiple_region(self):
        """
        Test multiple namespace with multiple region
        """
        self.enable_region()
        if len(self.get_json(short_opt='-R')) <= 1:
            self.cancel("Test not applicable without multiple regions")
        regions = self.get_json(short_opt='-R')
        self.disable_namespace()
        self.destroy_namespace()
        for region in regions:
            self.log.info("Using %s for muliple namespaces", region)
            self.log.info("Creating %s namespaces", self.cnt)
            if not self.size:
                self.size = self.get_json_val(self.get_json(
                    long_opt='-r %s' % region)[0], 'size')
                ch_cnt = self.get_aligned_count(self.size)
                self.size = self.size // ch_cnt
            else:
                # Assuming size is aligned
                ch_cnt = self.cnt
            for nid in range(0, ch_cnt):
                self.create_namespace(
                    region=region, mode=self.mode_to_use, size=self.size)
                self.log.info("Namespace %s created", nid + 1)

    def test_namespace_reconfigure(self):
        """
        Test namespace reconfiguration
        """
        self.enable_region()
        region = self.params.get('region', default=None)
        if not region:
            region = self.get_json(short_opt='-R')[0]
        self.log.info("Using %s for reconfiguring namespace", region)
        self.disable_namespace()
        self.destroy_namespace()
        self.create_namespace(region=region, mode='fsdax', align='64k')
        old_ns = self.get_json()[0]
        old_ns_dev = self.get_json_val(old_ns, 'dev')
        self.log.info("Re-configuring namespace %s", old_ns_dev)
        self.create_namespace(region=region, mode='fsdax',
                              name='test_ns', reconfig=old_ns_dev, force=True)
        new_ns = self.get_json()[0]
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

    def test_check_namespace(self):
        """
        Verify metadata for sector mode namespaces
        """
        self.enable_region()
        region = self.params.get('region', default=None)
        if not region:
            region = self.get_json(short_opt='-R')[0]
        self.disable_namespace()
        self.destroy_namespace()
        self.log.info("Creating sector namespace using %s", region)
        self.create_namespace(region=region, mode='sector')
        ns_sec_dev = self.get_json_val(self.get_json()[0], 'dev')
        self.disable_namespace(namespace=ns_sec_dev)
        self.log.info("Checking BTT metadata")
        if process.system("%s check-namespace %s" % (self.binary, ns_sec_dev),
                          ignore_status=True):
            self.fail("Failed to check namespace metadata")

    def test_check_numa(self):
        self.enable_region()
        regions = self.get_json(short_opt='-R')
        for reg in regions:
            numa = genio.read_one_line('/sys/devices/ndbus%s/%s/numa_node'
                                       % (re.findall(r'\d+', reg)[0], reg))
            # Check numa config in ndctl and sys interface
            if len(self.get_json(long_opt='-r %s -U %s' % (reg, numa))) != 1:
                self.fail('Region mismatch between ndctl and sys interface')

    def test_label_read_write(self):
        self.enable_region()
        region = self.params.get('region', default=None)
        if not region:
            region = self.get_json(short_opt='-R')[0]
        nmem = "nmem%s" % re.findall(r'\d+', region)[0]

        self.log.info("Using %s for testing labels", region)
        self.disable_region(name=region)
        self.log.info("Filling zeros to start test")
        if process.system('%s zero-labels %s' % (self.binary, nmem), shell=True):
            self.fail("Label zero-fill failed")

        self.enable_region(name=region)
        self.create_namespace(region=region)
        self.log.info("Storing labels with a namespace")
        old_op = process.system_output('%s check-labels %s' % (self.binary, nmem), shell=True)
        if process.system('%s read-labels %s -o output' % (self.binary, nmem), shell=True):
            self.fail("Label read failed")

        self.log.info("Refilling zeroes before a restore")
        self.disable_namespace(region=region)
        self.destroy_namespace(region=region)
        self.disable_region(name=region)
        if process.system('%s zero-labels %s' % (self.binary, nmem), shell=True):
            self.fail("Label zero-fill failed after read")

        self.log.info("Re-storing labels with a namespace")
        if process.system('%s write-labels %s -i output' % (self.binary, nmem), shell=True):
            self.fail("Label write failed")
        self.enable_region(name=region)

        self.log.info("Checking mismatch after restore")
        new_op = process.system_output('%s check-labels %s' % (self.binary, nmem), shell=True)
        if new_op != old_op:
            self.fail("Label read and write mismatch")

        self.log.info("Checking created namespace after restore")
        if len(self.get_json(long_opt='-r %s' % region)) != 1:
            self.fail("Created namespace not found after label restore")

    def tearDown(self):
        if not self.preserve_setup:
            if self.get_json(short_opt='-N'):
                self.destroy_namespace(force=True)
            self.disable_region()


if __name__ == "__main__":
    main()
