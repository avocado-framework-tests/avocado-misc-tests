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
# Copyright: 2016 IBM
# Author: Santhosh G <santhog4@linux.vnet.ibm.com>

import os
import re
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils import memory
from avocado.core import data_dir


class Thp(Test):
    '''
    The test enables THP and stress the system using dd load
    and verifies whether THP has been allocated for usage or not
    '''
    def setUp(self):
        # Check THP is Supported
        cmd = 'pgrep khugepaged'
        ret = process.system(cmd, verbose=False)
        if ret:
            self.skip('Hugepage daemon is not running !!!\n'
                      'Skipping Test as Not Applicable')
        # Get required mem info
        self.tmpdir = data_dir.get_tmp_dir()
        self.mem_path = os.path.join(self.tmpdir, 'thp_space')
        self.mem = int(memory.freememtotal() / 1024)
        self.dd_timeout = self.params.get('dd_timeout', default=900)
        # memory /(2 * huge_pagesize)
        self.count = int(self.mem / 32)

    def test(self):
        # Set THP to always
        cmd = "echo 'always' > /sys/kernel/mm/transparent_hugepage/enabled"
        ret = process.system(cmd)
        if ret:
            self.error('Unable to set THP to always')

        # Read thp values before stressing the system
        thp_alloted_before = int(memory.read_from_vmstat("thp_fault_alloc"))
        thp_split_before = int(memory.read_from_vmstat("thp_split_page"))
        thp_collapse_alloc_before = int(memory.read_from_vmstat
                                        ("thp_collapse_alloc"))

        # Start Stresssing the  System
        self.log.info('Base Stress test Start')
        # add mount point
        cmd = 'mkdir -p %s;mount -t tmpfs -o size=%dM '\
              'none %s;' % (self.mem_path, self.mem, self.mem_path)
        # Check for Initial Values
        cmd += 'rm -rf %s/*; for i in `seq %d`; do dd '\
               % (self.mem_path, self.count)
        # Keep bs as two times of hugepage size
        cmd += 'if=/dev/zero of=%s/$i bs=32768000 count=1& done;wait'\
               % self.mem_path
        stress_output = process.system_output(cmd,
                                              timeout=self.dd_timeout,
                                              shell=True)
        # Check For Error
        if len(re.findall("No space", stress_output)) > self.count * 0.6:
            e_msg = "Stress: Too many dd instances failed"
            self.error(e_msg)
        try:
            output = process.system('pidof dd', verbose=False)
        except Exception:
            output = None
        if output is not None:
            for i in re.split('\n+', output):
                process.system('kill -9 %s' % i, verbose=False)

        # Read thp values after stress
        thp_alloted_after = int(memory.read_from_vmstat("thp_fault_alloc"))
        thp_split_after = int(memory.read_from_vmstat("thp_split_page"))
        thp_collapse_alloc_after = int(memory.read_from_vmstat
                                       ("thp_collapse_alloc"))
        if thp_alloted_after <= thp_alloted_before:
            e_msg = "thp usage count has not increased\n"
            e_msg += "Before Stress:%d\nAfter stress:%d" % (thp_alloted_before,
                                                            thp_alloted_after)
            self.error(e_msg)
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
        if self.mem_path:
            self.log.info('Cleaning Up!!!')
            process.system('umount %s' % self.mem_path, verbose=False)
            process.system('rm -rf %s' % self.mem_path, verbose=False)


if __name__ == "__main__":
    main()
