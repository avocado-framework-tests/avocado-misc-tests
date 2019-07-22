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
# Test Inspired basically from
# https://github.com/autotest/tp-qemu/blob/master/generic/tests/trans_hugepage.py
#
# Copyright: 2017 IBM
# Author: Santhosh G <santhog4@linux.vnet.ibm.com>

import os
from avocado import Test
from avocado import main
from avocado import skipIf
from avocado.utils import process
from avocado.utils import memory
from avocado.core import data_dir
from avocado.utils.partition import Partition


PAGESIZE = '4096' in str(memory.get_page_size())


class Thp(Test):

    '''
    The test enables THP and stress the system using dd load
    and verifies whether THP has been allocated for usage or not

    :avocado: tags=memory,privileged,hugepage
    '''

    @skipIf(PAGESIZE, "No THP support for kernel with 4K PAGESIZE")
    def setUp(self):
        '''
        Sets all the reqd parameter and also
        mounts the tmpfs to be used in test.
        '''

        # Set params as per available memory in system
        self.mem_path = self.params.get(
            "t_dir", default=os.path.join(data_dir.get_tmp_dir(), 'thp_space'))
        free_mem = self.params.get(
            "mem_size", default=memory.meminfo.MemFree.m)
        self.dd_timeout = self.params.get("dd_timeout", default=900)
        self.thp_split = None
        try:
            memory.read_from_vmstat("thp_split_page")
            self.thp_split = "thp_split_page"
        except IndexError:
            self.thp_split = "thp_split"

        # Set block size as hugepage size * 2
        self.block_size = memory.meminfo.Hugepagesize.m * 2
        self.count = free_mem // self.block_size

        # Mount device as per free memory size
        if not os.path.exists(self.mem_path):
            os.makedirs(self.mem_path)
        self.device = Partition(device="none", mountpoint=self.mem_path)
        self.device.mount(mountpoint=self.mem_path, fstype="tmpfs",
                          args='-o size=%dM' % free_mem)

    def test(self):
        '''
        Enables THP , Runs the dd workload and checks whether THP
        has been allocated.
        '''

        # Enables THP
        try:
            memory.set_thp_value("enabled", "always")
        except Exception as details:
            self.fail("Failed  %s" % details)

        # Read thp values before stressing the system
        thp_alloted_before = int(memory.read_from_vmstat("thp_fault_alloc"))
        thp_split_before = int(memory.read_from_vmstat(self.thp_split))
        thp_collapse_alloc_before = int(memory.read_from_vmstat
                                        ("thp_collapse_alloc"))

        # Start Stresssing the  System
        self.log.info('Stress testing using dd command')

        for iterator in range(self.count):
            stress_cmd = 'dd if=/dev/zero of=%s/%d bs=%dM count=1'\
                         % (self.mem_path, iterator, self.block_size)
            if(process.system(stress_cmd, timeout=self.dd_timeout,
                              verbose=False, ignore_status=True, shell=True)):
                self.fail('dd command failed  %s' % stress_cmd)

        # Read thp values after stressing the system
        thp_alloted_after = int(memory.read_from_vmstat("thp_fault_alloc"))
        thp_split_after = int(memory.read_from_vmstat(self.thp_split))
        thp_collapse_alloc_after = int(memory.read_from_vmstat
                                       ("thp_collapse_alloc"))

        # Check whether THP is Used or not
        if thp_alloted_after <= thp_alloted_before:
            e_msg = "Thp usage count has not increased\n"
            e_msg += "Before Stress:%d\nAfter stress:%d" % (thp_alloted_before,
                                                            thp_alloted_after)
            self.fail(e_msg)
        else:
            thp_fault_alloc = thp_alloted_after - thp_alloted_before
            thp_split = thp_split_after - thp_split_before
            thp_collapse_alloc = (thp_collapse_alloc_after -
                                  thp_collapse_alloc_before)
            self.log.info("\nTest statistics, changes during test run:")
            self.log.info("thp_fault_alloc=%d\nthp_split=%d\n"
                          "thp_collapse_alloc=%d\n",
                          thp_fault_alloc, thp_split, thp_collapse_alloc)

    def tearDown(self):
        '''
        Removes the files created and unmounts the tmpfs.
        '''

        if self.mem_path:
            self.log.info('Cleaning Up!!!')
            self.device.unmount()
            process.system('rm -rf %s' % self.mem_path, ignore_status=True)


if __name__ == "__main__":
    main()
