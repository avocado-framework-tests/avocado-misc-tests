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
# Copyright: 2018 IBM
# Author: Harish <harish@linux.vnet.ibm.com>
#


import os
import shutil

import avocado
from avocado import Test
from avocado import main
from avocado.utils import process, build, memory, distro, pmem, partition
from avocado.utils.software_manager import SoftwareManager


class Mprotect(Test):
    """
    Uses mprotect call to protect 90% of the machine's free
    memory and accesses with PROT_READ, PROT_WRITE and PROT_NONE

    :avocado: tags=memory
    """

    def copyutil(self, file_name):
        shutil.copyfile(self.get_data(file_name),
                        os.path.join(self.teststmpdir, file_name))

    @avocado.fail_on(pmem.PMemException)
    def setup_nvdimm(self):
        self.plib = pmem.PMem()
        regions = sorted(self.plib.run_ndctl_list(
            '-R'), key=lambda i: i['size'], reverse=True)
        if not regions:
            self.plib.enable_region()
            regions = sorted(self.plib.run_ndctl_list(
                '-R'), key=lambda i: i['size'], reverse=True)
        self.region = self.plib.run_ndctl_list_val(regions[0], 'dev')
        self.plib.destroy_namespace(region=self.region, force=True)
        self.plib.create_namespace(region=self.region, size='128M')
        disk = "/dev/%s" % self.plib.run_ndctl_list_val(
            self.plib.run_ndctl_list('-N -r %s' % self.region)[0], 'blockdev')
        self.mnt_dir = '/pmem'

        self.part_obj = partition.Partition(disk, mountpoint=self.mnt_dir)
        self.log.info("Creating file system")
        self.part_obj.mkfs(fstype='ext4', args='-b 64k -F')
        self.log.info("Mounting disk %s on directory %s", disk, self.mnt_dir)
        if not os.path.exists(self.mnt_dir):
            os.makedirs(self.mnt_dir)
        try:
            self.part_obj.mount(args='-o dax')
        except partition.PartitionError:
            self.cancel("Mounting disk %s on directory failed" % disk)
        return os.path.join(self.mnt_dir, "file")

    def setUp(self):
        smm = SoftwareManager()
        self.nr_pages = self.params.get('nr_pages', default=None)
        self.in_err = self.params.get('induce_err', default=0)
        self.back_file = self.params.get('back_file', default="/dev/zero")
        self.file_type = self.params.get('file_type', default="block")
        self.failure = self.params.get('failure', default=False)

        if not self.nr_pages:
            memsize = int(memory.meminfo.MemFree.b * 0.9)
            self.nr_pages = memsize // memory.get_page_size()

        deps = ['gcc', 'make']
        if self.file_type == 'nvdimm':
            deps.extend(['ndctl'])
            if distro.detect().name == 'rhel':
                deps.extend(['daxctl'])
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

        if self.file_type == 'nvdimm':
            self.back_file = self.setup_nvdimm()
        for file_name in ['mprotect.c', 'Makefile']:
            self.copyutil(file_name)

        build.make(self.teststmpdir)

    def test(self):
        os.chdir(self.teststmpdir)
        self.log.info("Starting test...")

        ret = process.system('./mprotect %s %s %s' % (self.nr_pages, self.in_err, self.back_file),
                             shell=True, ignore_status=True, sudo=True)
        if self.failure:
            if ret != 255:
                self.fail("Please check the logs for debug")
            else:
                self.log.info("Failed as expected")
        else:
            if ret is not 0:
                self.fail("Please check the logs for debug")
            else:
                self.log.info("Passed as expected")

    def tearDown(self):
        if self.file_type == 'nvdimm':
            self.part_obj.unmount(force=True)
            self.plib.destroy_namespace(region=self.region, force=True)
            shutil.rmtree(self.mnt_dir)


if __name__ == "__main__":
    main()
