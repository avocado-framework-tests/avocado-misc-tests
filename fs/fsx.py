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
# Copyright: 2017 IBM
# Author: Harish <harish@linux.vnet.ibm.com>
#

import os
from avocado import Test
from avocado.utils import process, genio
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils.partition import Partition


class Fsx(Test):
    '''
    The Fsx test is a file system exerciser test

    :avocado: tags=fs
    '''

    @staticmethod
    def mount_point(mount_dir):
        lines = genio.read_file('/proc/mounts').rstrip('\t\r\0').splitlines()
        for substr in lines:
            mop = substr.split(" ")[1]
            if mop == mount_dir:
                return True
        return False

    def check_thp(self):
        if 'thp_file_alloc' in genio.read_file('/proc/vm'
                                               'stat').rstrip('\t\r\n\0'):
            self.thp = True
        return self.thp

    def setup_tmpfs_dir(self):
        # check for THP page cache
        self.check_thp()

        if not os.path.isdir(self.mount_dir):
            os.makedirs(self.mount_dir)

        self.device = None
        if not self.mount_point(self.mount_dir):
            if self.thp:
                self.device = Partition(
                    device="none", mountpoint=self.mount_dir,
                    mount_options="huge=always")
            else:
                self.device = Partition(
                    device="none", mountpoint=self.mount_dir)
            self.device.mount(mountpoint=self.mount_dir, fstype="tmpfs")

    def setUp(self):
        '''
        Setup fsx
        '''
        smm = SoftwareManager()
        for package in ['gcc', 'make']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel(package + ' is needed for the test to be run')

        fsx = self.fetch_asset(
            'https://raw.githubusercontent.com/linux-test-project/ltp/'
            'master/testcases/kernel/fs/fsx-linux/fsx-linux.c', expire='7d')
        os.chdir(self.workdir)
        process.system('gcc -o fsx %s' % fsx, shell=True, ignore_status=True)
        self.thp = False

    def test(self):
        '''
        Run Fsx test for exercising file system
        '''
        file_ub = self.params.get('file_ub', default='1000000')
        op_ub = self.params.get('op_ub', default='1000000')
        output = self.params.get('output_file', default='/tmp/result')
        num_times = self.params.get('num_times', default='10000')
        self.mount_dir = self.params.get('tmpfs_mount_dir', default=None)
        thp_page_cache = self.params.get('thp_page_cache', default=None)

        if thp_page_cache:
            if self.mount_dir:
                self.setup_tmpfs_dir()
                output = os.path.join(self.mount_dir, 'result')
            else:
                self.cancel("tmpfs_mount_dir not specified")
        else:
            output = self.params.get('output_file', default='/tmp/result')

        results = process.system_output(
            './fsx   -l %s -o %s -n -s 1 -N %s -d %s'
            % (file_ub, op_ub, num_times, output))

        if b'All operations completed' not in results.splitlines()[-1]:
            self.fail('Fsx test failed')

    def tearDown(self):
        if self.mount_dir:
            self.device.unmount()
