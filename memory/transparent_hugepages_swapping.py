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
# Test Inspired basically from
# https://github.com/autotest/tp-qemu/blob/master/generic/tests/trans_hugepage_swapping.py
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


class ThpSwapping(Test):

    '''
    The test fills out the total avl memory and tries to swap the thp out.

    :avocado: tags=memory,privileged,hugepage
    '''

    @skipIf(PAGESIZE, "No THP support for kernel with 4K PAGESIZE")
    def setUp(self):
        '''
        Sets the Required params for dd and mounts the tmpfs dir
        '''

        self.swap_free = []
        mem_free = memory.meminfo.MemFree.m
        mem = memory.meminfo.MemTotal.m
        swap = memory.meminfo.SwapTotal.m
        self.hugepage_size = memory.meminfo.Hugepagesize.m
        self.swap_free.append(memory.meminfo.SwapFree.m)
        self.mem_path = os.path.join(data_dir.get_tmp_dir(), 'thp_space')
        self.dd_timeout = 900

        # If swap is enough fill all memory with dd
        if self.swap_free[0] > (mem - mem_free):
            self.count = (mem // self.hugepage_size) // 2
            tmpfs_size = mem
        else:
            self.count = (mem_free // self.hugepage_size) // 2
            tmpfs_size = mem_free

        if swap <= 0:
            self.cancel("Swap is not enabled in the system")

        if not os.path.ismount(self.mem_path):
            if not os.path.isdir(self.mem_path):
                os.makedirs(self.mem_path)
            self.device = Partition(device="none", mountpoint=self.mem_path)
            self.device.mount(mountpoint=self.mem_path, fstype="tmpfs",
                              args="-o size=%sM" % tmpfs_size)

    def test(self):
        '''
        Enables THP Runs dd, fills out the available memory and checks whether
        THP is swapped out.
        '''

        # Enables THP
        try:
            memory.set_thp_value("enabled", "always")
        except Exception as details:
            self.fail("Failed  %s" % details)

        for iterator in range(self.count):
            swap_cmd = "dd if=/dev/zero of=%s/%d bs=%sM "\
                       "count=1" % (self.mem_path, iterator,
                                    self.hugepage_size * 2)
            if(process.system(swap_cmd, timeout=self.dd_timeout,
                              verbose=False, ignore_status=True, shell=True)):
                self.fail('Swap command Failed %s' % swap_cmd)

        self.swap_free.append(memory.meminfo.SwapFree.m)

        # Checks Swap is used or not
        if self.swap_free[1] - self.swap_free[0] >= 0:
            self.fail("Swap Space remains untouched")

    def tearDown(self):
        '''
        Removes directories in tmpfs and unmounts it.
        '''

        if self.mem_path:
            self.log.info('Cleaning Up!!!')
            self.device.unmount()
            process.system('rm -rf %s' % self.mem_path, ignore_status=True)


if __name__ == "__main__":
    main()
