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
import shutil
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils import archive
from avocado.utils import distro
from avocado.utils import build
from avocado.utils import genio
from avocado.utils import memory
from avocado.utils import partition
from avocado.utils.software_manager import SoftwareManager


class NdctlTest(Test):

    """
    Ndctl user space tooling for Linux, which handles NVDIMM devices.

    """
    def run_ndctl_list(self, option=''):
        """
        Get the json of each provided options

        return: By default returns entire list of json objects
        return: Empty list if output is empty
        """
        try:
            json_op = json.loads(process.system_output(
                '%s list %s' % (self.binary, option), shell=True))
        except ValueError:
            json_op = []
        return json_op

    @staticmethod
    def run_ndctl_list_val(json_op, field):
        """
        Get the value of a field in given json
        """
        for key, value in json_op.items():
            if key == field:
                return value
        return None

    def get_default_region(self):
        """
        Get the largest region if not provided
        """
        self.enable_region()
        region = self.params.get('region', default=None)
        if region:
            return region
        regions = self.run_ndctl_list('-R')
        regions = sorted(regions, key=lambda i: i['size'], reverse=True)
        return self.run_ndctl_list_val(regions[0], 'dev')

    @staticmethod
    def get_size_alignval():
        """
        Return the size align restriction based on platform
        """
        if 'Hash' in genio.read_file('/proc/cpuinfo').rstrip('\t\r\n\0'):
            def_align = 16 * 1024 * 1024
        else:
            def_align = 2 * 1024 * 1024
        return def_align

    def get_slot_count(self, region):
        """
        Get max slot count in the index area for a  dimm backing a region
        We use region0 - > nmem0
        """
        nmem = "nmem%s" % re.findall(r'\d+', region)[0]
        try:
            json_op = json.loads(process.system_output(
                '%s read-labels -j %s ' % (self.binary, nmem), shell=True))
        except ValueError:
            json_op = []
        first_dict = json_op[0]
        index_dict = self.run_ndctl_list_val(first_dict, 'index')[0]
        return self.run_ndctl_list_val(index_dict, 'nslot') - 1

    def is_region_legacy(self, region):
        """
        Check whether we have label index namespace. If legacy we can't create
        new namespaces.
        """
        nstype = genio.read_file("/sys/bus/nd/devices/" + region + "/nstype").rstrip("\n")
        if (nstype == "4"):
            return True
        return False

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

    def run_daxctl_list(self, options=''):
        """
        Run daxctl list command with option
        """
        return json.loads(process.system_output(
            '%s list %s' % (self.daxctl, options), shell=True))

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
                          verbose=False):
        """
        Disable namepsaces
        """
        args = namespace
        if region:
            args = '%s -r %s' % (args, region)
        if bus:
            args = '%s -b %s' % (args, bus)
        if verbose:
            args = '%s -v' % args

        if process.system('%s disable-namespace %s' % (self.binary, args),
                          shell=True, ignore_status=True):
            self.fail('Namespace disable failed for "%s"' % namespace)

    def enable_namespace(self, namespace='all', region='', bus='',
                         verbose=False):
        """
        Enable namepsaces
        """
        args = namespace
        if region:
            args = '%s -r %s' % (args, region)
        if bus:
            args = '%s -b %s' % (args, bus)
        if verbose:
            args = '%s -v' % args

        if process.system('%s enable-namespace %s' % (self.binary, args),
                          shell=True, ignore_status=True):
            self.fail('Namespace enable failed for "%s"' % namespace)

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

        if (self.is_region_legacy(region) and not reconfig):
            namespace = "namespace%s.0" % re.findall(r'\d+', region)[0]
            args += " -f -e " + namespace

        if process.system('%s create-namespace %s' % (self.binary, args),
                          shell=True, ignore_status=True):
            self.fail('Namespace create command failed')

    def destroy_namespace(self, namespace='all', region='', bus='',
                          force=False):
        """
        Destroy namepsaces
        """

        if (region and self.is_region_legacy(region)):
            return

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
        self.preserve_setup = self.params.get('preserve_change', default=False)
        self.mode_to_use = self.params.get('modes', default='fsdax')

        if self.dist.name not in ['SuSE', 'rhel']:
            self.cancel('Unsupported OS %s' % self.dist.name)

        # DAX wont work with reflink, disabling here
        self.reflink = '-m reflink=0'
        if not self.check_buses():
            self.cancel("Test needs atleast one region")

        self.smm = SoftwareManager()
        if self.package == 'upstream':
            deps.extend(['gcc', 'make', 'automake', 'autoconf'])
            if self.dist.name == 'SuSE':
                deps.extend(['ruby2.5-rubygem-asciidoctor', 'libtool',
                             'libkmod-devel', 'libudev-devel', 'systemd-devel',
                             'libuuid-devel-static', 'libjson-c-devel',
                             'keyutils-devel', 'kmod-bash-completion'])
            elif self.dist.name == 'rhel':
                deps.extend(['rubygem-asciidoctor', 'automake', 'libtool',
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
                        "--sysconfdir=/etc --libdir="
                        "/usr/lib64", shell=True, sudo=True)
            build.make(".")
            self.binary = './ndctl/ndctl'
            self.daxctl = './daxctl/daxctl'
        else:
            for pkg in ['ndctl', 'daxctl']:
                if not self.smm.check_installed(pkg) and not \
                        self.smm.install(pkg):
                    self.cancel('%s is needed for the test to be run' % pkg)
            self.binary = 'ndctl'
            self.daxctl = 'daxctl'

        self.opt_dict = {'-B': 'provider',
                         '-D': 'dev', '-R': 'dev', '-N': 'dev'}
        self.modes = ['raw', 'sector', 'fsdax', 'devdax']
        self.part = None
        self.disk = None

    def test_bus_ids(self):
        """
        Test the bus id info
        """
        vals = self.run_ndctl_list('-B')
        if not vals:
            self.fail('Failed to fetch bus IDs')
        self.log.info('Available Bus provider IDs: %s', vals)

    def test_dimms(self):
        """
        Test the dimms info
        """
        vals = self.run_ndctl_list('-D')
        if not vals:
            self.fail('Failed to fetch DIMMs')
        self.log.info('Available DIMMs: %s', vals)

    def test_regions(self):
        """
        Test the regions info
        """
        self.disable_region()
        old = self.run_ndctl_list('-R')
        self.enable_region()
        new = self.run_ndctl_list('-R')
        if len(new) <= len(old):
            self.fail('Failed to fetch regions')
        self.log.info('Available regions: %s', new)

    def test_namespace(self):
        """
        Test namespace
        """
        self.enable_region()
        regions = self.run_ndctl_list('-R')
        for val in regions:
            region = self.run_ndctl_list_val(val, 'dev')
            self.disable_namespace(region=region)
            self.destroy_namespace(region=region)
            self.create_namespace(region=region)

        namespaces = self.run_ndctl_list('-N')
        self.log.info('Created namespace %s', namespaces)

    def test_disable_enable_ns(self):
        """
        Test enable disable namespace
        """
        region = self.get_default_region()
        if (not self.is_region_legacy(region)):
            for _ in range(0, 3):
                self.create_namespace(region=region, size='128M')
        namespaces = self.run_ndctl_list('-N')
        ns_names = []
        for ns in namespaces:
            ns_names.append(self.run_ndctl_list_val(ns, 'dev'))
        ns_names.append('all')

        for namespace in ns_names:
            self.disable_namespace(namespace=namespace)
            self.enable_namespace(namespace=namespace)

    def test_namespace_modes(self):
        """
        Create  different namespace types
        """
        failed_modes = []
        region = self.get_default_region()
        self.log.info("Using %s for different namespace modes", region)
        self.disable_namespace(region=region)
        self.destroy_namespace(region=region)
        for mode in self.modes:
            self.create_namespace(region=region, mode=mode)
            ns_json = self.run_ndctl_list()[0]
            created_mode = self.run_ndctl_list_val(ns_json, 'mode')
            if mode != created_mode:
                failed_modes.append(mode)
                self.log.error("Expected mode %s, Got %s", mode, created_mode)
            else:
                self.log.info("Namespace with %s mode: %s", mode, ns_json)
            ns_name = self.run_ndctl_list_val(ns_json, 'dev')
            self.disable_namespace(namespace=ns_name, region=region)
            self.destroy_namespace(namespace=ns_name, region=region)

        if failed_modes:
            self.fail("Namespace for %s mode failed!" % failed_modes)

    def multiple_namespaces_region(self, region):
        """
        Test multiple namespace with single region
        """
        namespace_size = self.params.get('size', default=None)
        size_align = self.get_size_alignval()
        slot_count = self.get_slot_count(region)
        self.log.info("Using %s for muliple namespace regions", region)
        self.disable_namespace(region=region)
        self.destroy_namespace(region=region)
        if namespace_size and ((namespace_size % size_align) != 0):
            self.cancel("Size value not %d aligned %d \n",
                        size_align, namespace_size)

        region_size = self.run_ndctl_list_val(self.run_ndctl_list(
            '-r %s' % region)[0], 'size')
        if not namespace_size:
            namespace_size = region_size // slot_count
            # Now align the namespace size
            namespace_size = (namespace_size // size_align) * size_align
        else:
            slot_count = region_size // namespace_size

        self.log.info("Creating %s namespaces", slot_count)
        for count in range(0, slot_count):
            self.create_namespace(
                region=region, mode=self.mode_to_use, size=namespace_size)
            self.log.info("Namespace %s created", count + 1)

    def test_multiple_namespaces_region(self):
        """
        Test multiple namespace with single region
        """
        region = self.get_default_region()
        if (self.is_region_legacy(region)):
            self.cancel("Legacy config skipping the test")
        self.multiple_namespaces_region(region)

    def test_multiple_ns_multiple_region(self):
        """
        Test multiple namespace with multiple region
        """
        self.enable_region()
        if len(self.run_ndctl_list('-R')) <= 1:
            self.cancel("Test not applicable without multiple regions")
        regions = self.run_ndctl_list('-R')
        self.disable_namespace()
        self.destroy_namespace()
        for val in regions:
            region = self.run_ndctl_list_val(val, 'dev')
            if (self.is_region_legacy(region)):
                self.cancel("Legacy config skipping the test")
            self.multiple_namespaces_region(region)

    def test_multiple_ns_modes_region(self):
        """
        Test multiple namespace modes with single region
        """
        region = self.get_default_region()
        if (self.is_region_legacy(region)):
            self.cancel("Legacy config skipping the test")
        self.log.info("Using %s for muliple namespace regions", region)
        self.disable_namespace(region=region)
        self.destroy_namespace(region=region)
        size = self.run_ndctl_list_val(self.run_ndctl_list(
            '-r %s' % region)[0], 'size')
        if size < (len(self.modes) * 64 * 1024 * 1024):
            self.cancel('Not enough memory to create namespaces')
        for mode in self.modes:
            self.create_namespace(
                region=region, mode=mode, size='64M')
            self.log.info("Namespace of type %s created", mode)

    def test_nslot_namespace(self):
        """
        Test max namespace with nslot value
        """
        region = self.get_default_region()
        if (self.is_region_legacy(region)):
            self.cancel("Legacy config skipping the test")
        size_align = self.get_size_alignval()
        slot_count = self.get_slot_count(region)
        self.log.info("Using %s for max namespace creation", region)
        self.disable_namespace()
        self.destroy_namespace()
        region_size = self.run_ndctl_list_val(self.run_ndctl_list(
            '-r %s' % region)[0], 'size')
        namespace_size = region_size // slot_count
        # Now align the namespace size
        namespace_size = (namespace_size // size_align) * size_align

        self.log.info("Creating %s namespace", slot_count)
        for count in range(0, slot_count):
            self.create_namespace(region=region, mode='fsdax', size=namespace_size)
            self.log.info("Namespace %s created", count)

    def test_namespace_reconfigure(self):
        """
        Test namespace reconfiguration
        """
        region = self.get_default_region()
        self.log.info("Using %s for reconfiguring namespace", region)
        self.disable_namespace()
        self.destroy_namespace()
        self.create_namespace(region=region, mode='fsdax', align='64k')
        old_ns = self.run_ndctl_list()[0]
        old_ns_dev = self.run_ndctl_list_val(old_ns, 'dev')
        self.log.info("Re-configuring namespace %s", old_ns_dev)
        self.create_namespace(region=region, mode='fsdax',
                              name='test_ns', reconfig=old_ns_dev, force=True)
        new_ns = self.run_ndctl_list()[0]
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
        region = self.get_default_region()
        self.disable_namespace()
        self.destroy_namespace()
        self.log.info("Creating sector namespace using %s", region)
        self.create_namespace(region=region, mode='sector')
        ns_sec_dev = self.run_ndctl_list_val(self.run_ndctl_list()[0], 'dev')
        self.disable_namespace(namespace=ns_sec_dev)
        self.log.info("Checking BTT metadata")
        if process.system("%s check-namespace %s" % (self.binary, ns_sec_dev),
                          ignore_status=True):
            self.fail("Failed to check namespace metadata")

    def test_check_numa(self):
        self.enable_region()
        regions = self.run_ndctl_list('-R')
        for val in regions:
            reg = self.run_ndctl_list_val(val, 'dev')
            numa = genio.read_one_line('/sys/devices/ndbus%s/%s/numa_node'
                                       % (re.findall(r'\d+', reg)[0], reg))
            # Check numa config in ndctl and sys interface
            if len(self.run_ndctl_list('-r %s -U %s' % (reg, numa))) != 1:
                self.fail('Region mismatch between ndctl and sys interface')

    def test_label_read_write(self):
        region = self.get_default_region()
        if (self.is_region_legacy(region)):
            self.cancel("Legacy config skipping the test")

        nmem = "nmem%s" % re.findall(r'\d+', region)[0]
        self.log.info("Using %s for testing labels", region)
        self.disable_region(name=region)
        self.log.info("Filling zeros to start test")
        if process.system('%s zero-labels %s' % (self.binary, nmem), shell=True):
            self.fail("Label zero-fill failed")

        self.enable_region(name=region)
        self.create_namespace(region=region)
        self.log.info("Storing labels with a namespace")
        old_op = process.system_output(
            '%s check-labels %s' % (self.binary, nmem), shell=True)
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
        new_op = process.system_output(
            '%s check-labels %s' % (self.binary, nmem), shell=True)
        if new_op != old_op:
            self.fail("Label read and write mismatch")

        self.log.info("Checking created namespace after restore")
        if len(self.run_ndctl_list('-N -r %s' % region)) != 1:
            self.fail("Created namespace not found after label restore")

    def test_daxctl_list(self):
        """
        Test daxctl list
        """
        region = self.get_default_region()
        self.disable_namespace(region=region)
        self.destroy_namespace(region=region)
        self.create_namespace(region=region, mode='devdax')
        index = re.findall(r'\d+', region)[0]
        vals = self.run_daxctl_list('-r %s' % (index))
        if len(vals) != 1:
            self.fail('Failed daxctl list')
        self.log.info('Created dax device %s', vals)

    def test_sector_write(self):
        """
        Test write on a sector mode device
        """
        region = self.get_default_region()
        self.disable_namespace(region=region)
        self.destroy_namespace(region=region)
        self.create_namespace(region=region, mode='sector', sector_size='512')
        self.disk = '/dev/%s' % self.run_ndctl_list_val(
            self.run_ndctl_list("-N -r %s" % region)[0], 'blockdev')
        size = self.run_ndctl_list_val(self.run_ndctl_list(
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

    def test_fsdax_write(self):
        """
        Test filesystem DAX with a FIO workload
        """
        region = self.get_default_region()
        self.create_namespace(region=region, mode='fsdax')
        self.disk = '/dev/%s' % self.run_ndctl_list_val(
            self.run_ndctl_list("-N -r %s" % region)[0], 'blockdev')
        size = self.run_ndctl_list_val(self.run_ndctl_list(
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

    def test_map_sync(self):
        """
        Test MAP_SYNC flag with sample mmap write
        """
        region = self.get_default_region()
        self.create_namespace(region=region, mode='fsdax')
        self.disk = '/dev/%s' % self.run_ndctl_list_val(
            self.run_ndctl_list("-N -r %s" % region)[0], 'blockdev')
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

    def test_devdax_write(self):
        """
        Test device DAX with a daxio binary
        """
        region = self.get_default_region()
        self.create_namespace(region=region, mode='devdax')
        daxdev = "/dev/%s" % self.run_ndctl_list_val(
            self.run_ndctl_list("-N -r %s" % region)[0], 'chardev')
        if process.system("%s -b no -i /dev/urandom "
                          "-o %s" % (self.get_data("daxio.static"), daxdev), ignore_status=True):
            self.fail("DAXIO write on devdax failed")

    def tearDown(self):
        if self.part:
            self.part.unmount()
        if self.disk:
            self.log.info("Removing the FS meta created on %s", self.disk)
            delete_fs = "dd if=/dev/zero bs=1M count=1024 of=%s" % self.disk
            if process.system(delete_fs, shell=True, ignore_status=True):
                self.fail("Failed to delete filesystem on %s" % self.disk)

        if not self.preserve_setup:
            if self.run_ndctl_list('-N'):
                self.destroy_namespace(force=True)
            self.disable_region()


if __name__ == "__main__":
    main()
