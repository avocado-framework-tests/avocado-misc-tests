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
# https://github.com/autotest/tp-qemu/blob/master/generic/tests/trans_hugepage_defrag.py
#
# Copyright: 2017 IBM
# Author: Santhosh G <santhog4@linux.vnet.ibm.com>

import os
import time
import mmap
import avocado
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils import memory
from avocado.utils import disk
from avocado.core import data_dir
from avocado.utils.partition import Partition


class Thp_Defrag(Test):

    '''
    Defrag test enables THP and fragments the system memory using dd load
    and turns on THP defrag and checks whether defrag occured.
    '''

    def setUp(self):

        '''
        Sets required params for dd workload and mounts the tmpfs
        '''

        # Get required mem info
        self.mem_path = os.path.join(data_dir.get_tmp_dir(), 'thp_space')
        self.block_size = int(mmap.PAGESIZE) / 1024
        self.dd_timeout = self.params.get('dd_timeout', default=900)
        # add mount point
        os.mkdir(self.mem_path)
        self.device = Partition(device="none", mountpoint=self.mem_path)
        self.device.mount(mountpoint=self.mem_path, fstype="tmpfs")
        free_space = (disk.freespace(self.mem_path)) / 1024
        # Leaving out some free space in tmpfs
        self.count = (free_space / self.block_size) - 3

    @avocado.fail_on
    def test(self):

        '''
        Enables THP, Turns off the defrag and fragments the memory.
        Once the memory gets fragmented turns on the defrag and checks
        whether defrag happened.
        '''

        # Enables THP
        memory.set_thp_value("enabled", "always")

        # Turns off Defrag
        memory.set_thp_value("khugepaged/defrag", "0")

        # Fragments The memory
        for iterator in range(self.count):
            defrag_cmd = 'dd if=/dev/urandom of=%s/%d bs=%dK count=1'\
                         % (self.mem_path, iterator, self.block_size)
            if(process.system(defrag_cmd, timeout=self.dd_timeout,
                              verbose=False, ignore_status=True, shell=True)):
                self.fail('Defrag command Failed %s' % defrag_cmd)

        total = memory.memtotal()
        hugepagesize = memory.get_huge_page_size()
        nr_full = int(0.8 * (total/hugepagesize))

        # Sets max possible hugepages before defrag on
        memory.set_num_huge_pages(nr_full)
        nr_hp_before = memory.get_num_huge_pages()

        # Turns Defrag ON
        memory.set_thp_value("khugepaged/defrag", "1")

        sleep_time = 10
        self.log.info("Sleeping %d seconds to settle out things", sleep_time)
        time.sleep(sleep_time)

        # Sets max hugepages after defrag on
        memory.set_num_huge_pages(nr_full)
        nr_hp_after = memory.get_num_huge_pages()

        # Check for memory defragmentation
        if nr_hp_before >= nr_hp_after:
            e_msg = "No Memory Defragmentation\n"
            e_msg += "%d hugepages before turning khugepaged on,\n"\
                     "%d After it" % (nr_hp_before, nr_hp_after)
            self.error(e_msg)

        self.log.info("Defrag test passed")

    def tearDown(self):

        '''
        Removes files and unmounts the tmpfs.
        '''

        if self.mem_path:
            self.log.info('Cleaning Up!!!')
            memory.set_num_huge_pages(0)
            process.system('rm -rf %s/*' % self.mem_path, ignore_status=True)
            self.device.unmount()


if __name__ == "__main__":
    main()
