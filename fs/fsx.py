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
#         Ayush Jain <ayush.jain3@amd.com>
#

import os, re
from avocado import Test
from avocado.utils import process, genio, archive, build
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils.partition import Partition

class Fsx(Test):
    '''
    The Fsx test is a file system exerciser test

    :avocado: tags=fs
    '''
    def parse_results(self,results):
        pattern = re.compile(r"\b(passed|failed|broken|skipped|warnings)\s+(\d+)")
        matches = pattern.findall(results.stderr.decode("utf-8"))
        result_dict = dict(matches)
        for param,count in result_dict.items():
            self.log.info(f"{str(param)} : {str(count)}")
        if(int(result_dict["failed"]) > 0 or int(result_dict["broken"]) > 0):
            self.fail('Fsx test failed')
        elif(int(result_dict["skipped"]) > 0):
            self.cancel(f'Fsx test {result_dict["skipped"]} skipped')
        elif(int(result_dict["warnings"]) > 0):
            self.log.warn(f'Fsx test {result_dict["warnings"]} warns')

    @staticmethod
    def mount_point(dir):
        lines = genio.read_file('/proc/mounts').rstrip('\t\r\0').splitlines()
        for substr in lines:
            mop = substr.split(" ")[1]
            if mop == dir:
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

        if not os.path.isdir(self.dir):
            os.makedirs(self.dir)

        self.device = None
        if not self.mount_point(self.dir):
            if self.thp:
                self.device = Partition(
                    device=self.disk, mountpoint=self.dir,
                    mount_options="huge=always")
            else:
                self.device = Partition(
                    device=self.disk, mountpoint=self.dir)
            self.device.mount(mountpoint=self.dir, fstype="tmpfs", mnt_check=False)

    def setUp(self):
        '''
        Setup fsx
        '''
        smm = SoftwareManager()
        for package in ['gcc', 'make', 'automake']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel(package + ' is needed for the test to be run')

        self.thp_page_cache = self.params.get('thp_page_cache', default=False)
        self.disk = self.params.get('disk', default="none")
        if self.thp_page_cache:
            self.dir = self.params.get('dir', default=self.workdir)
            if self.dir:
                self.setup_tmpfs_dir()
                self.output = os.path.join(self.dir, 'result')
            else:
                self.cancel("dir not specified")
        else:
            self.output = self.params.get('output_file', default=None)
            if not self.output:
                self.output=os.path.join(self.workdir,"result")

        if not os.path.exists(self.output):
            os.makedirs(self.output)

        url = self.params.get(
            'url', default='https://github.com/linux-test-project/ltp/archive/master.zip')
        match = next((ext for ext in [".zip", ".tar"] if ext in url), None)
        tarball = ''
        if match:
            tarball = self.fetch_asset(
                "ltp-master%s" % match, locations=[url], expire='7d')
        else:
            self.cancel("Provided LTP Url is not valid")
        self.ltpdir_parent = os.path.join(self.workdir,'/ltp')
        if not os.path.exists(self.ltpdir_parent):
            os.mkdir(self.ltpdir_parent)
        archive.extract(tarball, self.ltpdir_parent)
        self.ltp_dir = os.path.join(self.ltpdir_parent, "ltp-master")
        os.chdir(self.ltp_dir)
        build.make(self.ltp_dir, extra_args='autotools')
        process.system('./configure')

        self.test_file_max_size = self.params.get('test_file_max_size', default='1000000')
        self.single_op_max_size = self.params.get('single_op_max_size', default='1000000')
        self.total_ops = self.params.get('total_ops', default='1000')
        self.num_times = self.params.get('num_times', default='1')

    def test(self):
        '''
        Run Fsx test for exercising file system
        '''

        fsx_dir=os.path.join(self.ltp_dir,"testcases/kernel/fs/fsx-linux")
        os.chdir(fsx_dir)
        build.make(fsx_dir)

        cmd = "TMPDIR=%s ./fsx-linux -l %s -o %s -N %s -i %s -D" \
            % (self.output, self.test_file_max_size, self.single_op_max_size, \
            self.total_ops, self.num_times)

        results = process.run(cmd,shell=True)
        self.parse_results(results)

    def tearDown(self):
        if self.thp_page_cache:
            if self.dir:
                self.device.unmount()
