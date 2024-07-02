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
from avocado.utils import process, archive, distro, build
from avocado.utils import genio, pmem, disk, memory, partition
from avocado.utils.software_manager.manager import SoftwareManager


class PmemDeviceMapper(Test):
    """
    Ndctl user space tooling for Linux, which handles NVDIMM devices.
    """

    def get_size_alignval(self):
        """
        Return the size align restriction based on platform
        """
        if not os.path.exists("/sys/bus/nd/devices/region0/align"):
            self.cancel("Test cannot execute without the size alignment value")
        return int(genio.read_one_line("/sys/bus/nd/devices/region0/align"), 16)

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
                url = self.params.get("fio_url", default="http://brick.kernel"
                                                         ".dk/snaps/fio-2.1.10"
                                                         ".tar.gz")
                tarball = self.fetch_asset(url)
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
        package = self.params.get('package', default='distro')
        self.preserve_dm = self.params.get('preserve_dm', default=False)

        if self.dist.name not in ['SuSE', 'rhel']:
            self.cancel('Unsupported OS %s' % self.dist.name)

        self.smm = SoftwareManager()
        if package == 'upstream':
            deps.extend(['gcc', 'make', 'automake',
                         'autoconf', 'device-mapper'])
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
        self.plib.destroy_namespace(force=True)

        region = self.plib.run_ndctl_list_val(regions[0], 'dev')
        split = self.params.get('split_ns', default=False)
        if len(regions) == 1:
            if self.plib.is_region_legacy(region):
                self.cancel("Cannot create DM with single pmem device")
            if not split:
                self.cancel("Cannot run test without split option enabled")

        if split:
            if self.plib.is_region_legacy(region):
                self.cancel("Cannot split pmem device on legacy hardware")

            size_align = self.get_size_alignval()

            self.log.info("Creating namespace with existing regions")
            for reg_json in regions:
                region = self.plib.run_ndctl_list_val(reg_json, 'dev')
                slot_count = self.plib.get_slot_count(region)
                reg_size = self.plib.run_ndctl_list_val(
                    self.plib.run_ndctl_list('-r %s' % region)[0], 'size')
                namespace_size = reg_size // slot_count
                # Now align the namespace size
                namespace_size = (namespace_size //
                                  size_align) * size_align
                if namespace_size <= size_align:
                    self.log.warn("Skipping namespace size less than pagesize")
                    continue
                for _ in range(0, slot_count):
                    self.plib.create_namespace(
                        region=region, size=namespace_size)
        else:
            self.log.info("Creating namespace with full size")
            for reg_json in regions:
                region = self.plib.run_ndctl_list_val(reg_json, 'dev')
                self.plib.create_namespace(region=region)
        devices = self.plib.run_ndctl_list('-N')
        blk_cmd = ""
        bdev = None
        blk_size1 = 0
        for cnt, dev in enumerate(devices):
            bdev = self.plib.run_ndctl_list_val(dev, 'blockdev')
            bdev = "/dev/%s" % bdev
            blk_size2 = process.system_output(
                "blockdev --getsz %s" % bdev).decode()
            blk_cmd += ' %s %s linear %s 0 "\\\\n"' % (
                blk_size1, blk_size2, bdev)
            blk_size1 += int(blk_size2)
            if cnt == len(devices) - 1:
                break
        dm_cmd = 'echo -e "%s" | dmsetup create linear-pmem' % blk_cmd
        if process.system(dm_cmd, shell=True, sudo=True, ignore_status=True):
            self.fail("Creating DM failed")
        self.log.info("Running FIO on device-mapper")
        self.dm_disk = "/dev/mapper/linear-pmem"
        self.part = partition.Partition(self.dm_disk)
        self.part.mkfs(fstype='xfs', args='-b size=%s -s size=512 -m reflink=0' %
                       memory.get_page_size())
        mnt_path = self.params.get('mnt_point', default='/pmem')
        if not os.path.exists(mnt_path):
            os.makedirs(mnt_path)
        self.part.mount(mountpoint=mnt_path, args='-o dax')
        self.log.info("Test will run on %s", mnt_path)
        fio_job = self.params.get('fio_job', default='ndctl-fio.job')
        size = disk.freespace(mnt_path) * 0.9
        cmd = '%s --directory %s --filename mmap-pmem --size %s %s' % (
            self.build_fio(), mnt_path, size, self.get_data(fio_job))
        if process.system(cmd, ignore_status=True):
            self.fail("FIO mmap workload on fsdax failed")

    @avocado.fail_on(pmem.PMemException)
    def tearDown(self):
        if self.dm_disk:
            process.system('umount %s' % self.dm_disk, ignore_status=True)
        if not self.preserve_dm and hasattr(self, 'plib'):
            process.system('dmsetup remove linear-pmem',
                           sudo=True, ignore_status=True)
            self.plib.destroy_namespace(force=True)
            self.plib.disable_region()
