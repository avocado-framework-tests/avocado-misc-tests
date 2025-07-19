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
# Copyright: 2025 IBM
# Author: Pavithra Prakash <pavrampu@linux.vnet.ibm.com>
#

from avocado import Test
from avocado import skipUnless
from avocado.utils import process, memory


class HugepageSysctl(Test):
    """
    Test allocates given number of hugepages of default hugepage size.
    """
    @skipUnless('Hugepagesize' in dict(memory.meminfo),
                "Hugepagesize not defined in kernel.")
    def setUp(self):
        self.hpagesize = int(self.params.get(
            'hpagesize', default=memory.get_huge_page_size()/1024))
        self.log.info("Current default hugepage size is %sMB" % self.hpagesize)
        self.num_huge = int(self.params.get('num_pages', default='10'))

    def test(self):
        """
        To test configuring hugepages using sysctl.
        """
        process.run('echo "vm.nr_hugepages=%s" >> /etc/sysctl.conf' %
                    self.num_huge, sudo=True, shell=True)
        process.run('sysctl -p', sudo=True, shell=True)
        mem_info = process.system_output("tail /proc/meminfo", shell=True)
        self.log.info(mem_info)
        process.run("sed -i \'$d\' /etc/sysctl.conf", sudo=True, shell=True)
        value = memory.get_num_huge_pages_meminfo()
        if value != self.num_huge:
            self.fail("Hugepage configuration failed")
        else:
            print("%s number of hugepages are configured" % value)
