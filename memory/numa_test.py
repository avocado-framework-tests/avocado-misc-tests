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

from avocado import Test
from avocado import main
from avocado.utils import process, build, memory, distro
from avocado.utils.software_manager import SoftwareManager


class NumaTest(Test):
    """
    Excercises numa_move_pages and mbind call with 20% of the machine's free
    memory
    """

    def copyutil(self, file_name):
        shutil.copyfile(os.path.join(self.datadir, file_name),
                        os.path.join(self.teststmpdir, file_name))

    def setUp(self):
        smm = SoftwareManager()
        dist = distro.detect()
        memsize = int(memory.freememtotal() * 1024 * 0.2)
        self.nr_pages = self.params.get(
            'nr_pages', default=memsize / memory.get_page_size())
        self.map_type = self.params.get('map_type', default='private')

        nodes = memory.numa_nodes_with_memory()
        if len(nodes) < 2:
            self.cancel('Test requires two numa nodes to run.'
                        'Node list with memory: %s' % nodes)

        pkgs = ['gcc', 'make']
        if dist.name == "Ubuntu":
            pkgs.extend(['libpthread-stubs0-dev', 'libnuma-dev'])
        elif dist.name in ["centos", "rhel", "fedora"]:
            pkgs.extend(['numactl-devel'])
        else:
            pkgs.extend(['libnuma-devel'])

        for package in pkgs:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

        for file_name in ['util.c', 'numa_test.c', 'Makefile']:
            self.copyutil(file_name)

        build.make(self.teststmpdir)

    def test(self):
        os.chdir(self.teststmpdir)
        self.log.info("Starting test...")

        if process.system('./numa_test -m %s -n %s' % (self.map_type, self.nr_pages),
                          shell=True, sudo=True, ignore_status=True):
            self.fail('Please check the logs for failure')


if __name__ == "__main__":
    main()
