#!/usr/bin/env python
#
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
#


import os
import shutil
import avocado
from avocado import Test
from avocado.utils import process, memory, distro, pmem, disk, partition
from avocado.utils.software_manager import SoftwareManager


class MemoHog(Test):
    """
    Hogs up memory to sepcified size

    :avocado: tags=memory
    """

    @avocado.fail_on(pmem.PMemException)
    def setup_nvdimm(self):
        """
        Setup pmem devices
        """
        self.plib = pmem.PMem()
        regions = sorted(self.plib.run_ndctl_list(
            '-R'), key=lambda i: i['size'], reverse=True)
        if not regions:
            self.plib.enable_region()
            regions = sorted(self.plib.run_ndctl_list(
                '-R'), key=lambda i: i['size'], reverse=True)
        self.region = self.plib.run_ndctl_list_val(regions[0], 'dev')
        if self.plib.run_ndctl_list('-N -r %s' % self.region):
            self.plib.destroy_namespace(region=self.region, force=True)
        self.plib.create_namespace(region=self.region)
        disk_id = "/dev/%s" % self.plib.run_ndctl_list_val(
            self.plib.run_ndctl_list('-N -r %s' % self.region)[0], 'blockdev')
        self.mnt_dir = '/pmem'

        self.part_obj = partition.Partition(disk_id, mountpoint=self.mnt_dir)
        self.log.info("Creating file system")
        self.part_obj.mkfs(fstype='ext4', args='-b 64k -F')
        self.log.info("Mounting disk %s", disk_id)
        if not os.path.exists(self.mnt_dir):
            os.makedirs(self.mnt_dir)
        try:
            self.part_obj.mount(args='-o dax')
        except partition.PartitionError:
            self.cancel("Mounting disk %s on directory failed" % disk_id)
        return os.path.join(self.mnt_dir, "file")

    def setUp(self):
        """
        Setup scripts/disks to memory hog
        """
        smm = SoftwareManager()
        self.memsize = self.params.get(
            'memory_size', default=None)
        if not self.memsize:
            self.memsize = int(memory.meminfo.MemFree.b * 0.9)
        self.file_type = self.params.get('file_type', default=None)
        deps = ['gcc']
        detected_distro = distro.detect()
        if detected_distro.name in ["Ubuntu", "debian"]:
            deps.extend(['libnuma-dev'])
        elif detected_distro.name in ["centos", "rhel", "fedora"]:
            deps.extend(['numactl-devel'])
        else:
            deps.extend(['libnuma-devel'])
        if self.file_type:
            if self.file_type == 'nvdimm':
                deps.extend(['ndctl'])
                if detected_distro.name == "rhel":
                    deps.extend(['daxctl'])
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

        srcdir = os.path.join(self.workdir, 'memhog')
        if not os.path.exists(srcdir):
            os.makedirs(srcdir)
        for fname in ['memhog.c', 'util.c', 'util.h', 'numaif.h', 'numa.h']:
            fetch_file = self.fetch_asset(
                fname, locations=['https://raw.githubusercontent.com/numactl/'
                                  'numactl/master/%s' % fname], expire='7d')
            shutil.copyfile(fetch_file, os.path.join(srcdir, fname))

        if self.file_type:
            if self.file_type == 'nvdimm':
                self.back_file = self.setup_nvdimm()
                disk_size = int(disk.freespace(self.mnt_dir) * 0.95)
            else:
                self.back_file = '/tmp/back_file'
                disk_size = int(disk.freespace('/tmp') * 0.95)
            if self.memsize > disk_size:
                self.memsize = disk_size
            cmd = 'fallocate -l %s %s' % (self.memsize, self.back_file)
            if process.system(cmd, ignore_status=True):
                self.cancel('Could not create file to be backed')

        os.chdir(srcdir)
        if process.system('gcc -lnuma -o memhog memhog.c util.c'):
            self.cancel('Compiling source failed')

    def test(self):
        """
        Run memory hog to eat up memory with or without file backing
        """
        self.log.info("Testing memory hog with given inputs")
        args = str(self.memsize)
        if self.file_type:
            args = "%s -f%s" % (args, self.back_file)
        if process.system('./memhog %s' % args, ignore_status=True):
            self.fail('Memory hog test failed')

    def tearDown(self):
        """
        Clear disk/file creation
        """
        if self.file_type:
            if self.file_type == 'nvdimm':
                self.part_obj.unmount(force=True)
                self.plib.destroy_namespace(region=self.region, force=True)
                shutil.rmtree(self.mnt_dir)
            else:
                os.remove(self.back_file)
