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
# Copyright: 2019 IBM
# Author: Harish <harish@linux.vnet.ibm.com>
#


import os
import shutil

from avocado import Test
from avocado import main
from avocado.utils import process, build, memory, distro
from avocado.utils.software_manager import SoftwareManager


class MigratePages(Test):
    """
    Migrate chunks of memory between nodes with the following options
    1) normal pages
    2) hugepages
    3) hugepages with overcommit
    4) transparent hugepages

    :avocado: tags=memory,hugepage,migration
    """

    def copyutil(self, file_name):
        shutil.copyfile(self.get_data(file_name),
                        os.path.join(self.teststmpdir, file_name))

    def setUp(self):
        self.nr_chunks = self.params.get('nr_chunks', default=1)
        self.hpage = self.params.get('h_page', default=False)
        self.hpage_commit = self.params.get('h_commit', default=False)
        self.thp = self.params.get('thp', default=False)

        nodes = memory.numa_nodes_with_memory()
        if len(nodes) < 2:
            self.cancel('Test requires two numa nodes to run.'
                        'Node list with memory: %s' % nodes)

        dist = distro.detect()
        pkgs = ['gcc', 'make']
        if dist.name == "Ubuntu":
            pkgs.extend(['libpthread-stubs0-dev',
                         'libnuma-dev', 'libhugetlbfs-dev'])
        elif dist.name in ["centos", "rhel", "fedora"]:
            pkgs.extend(['numactl-devel', 'libhugetlbfs-devel'])
        elif dist.name == "SuSE":
            pkgs.extend(['libnuma-devel'])
            if dist.version >= 15:
                pkgs.extend(['libhugetlbfs-devel'])
            else:
                pkgs.extend(['libhugetlbfs-libhugetlb-devel'])

        smm = SoftwareManager()
        for package in pkgs:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

        # Enable THP
        if self.thp:
            try:
                memory.set_thp_value("enabled", "always")
            except Exception as details:
                self.fail("Failed to enable thp %s" % details)

        for file_name in ['node_move_pages.c', 'Makefile']:
            self.copyutil(file_name)

        build.make(self.teststmpdir)

    def test(self):
        os.chdir(self.teststmpdir)
        cmd = './node_move_pages -n %s' % self.nr_chunks

        if self.hpage:
            cmd += ' -h'
            if self.hpage_commit:
                cmd += ' -o'
        elif self.thp:
            cmd += ' -t'

        if process.system(cmd, shell=True, sudo=True, ignore_status=True):
            self.fail('Please check the logs for failure')


if __name__ == "__main__":
    main()
