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
from avocado import skipIf
from avocado.utils import process, build, memory, distro, genio
from avocado.utils.software_manager.manager import SoftwareManager

SINGLE_NODE = len(memory.numa_nodes_with_memory()) < 2


class NumaTest(Test):
    """
    Exercises numa_move_pages and mbind call with 20% of the machine's free
    memory

    :avocado: tags=memory,migration,hugepage
    """

    def copyutil(self, file_name):
        shutil.copyfile(self.get_data(file_name),
                        os.path.join(self.teststmpdir, file_name))

    def setUp(self):
        smm = SoftwareManager()
        dist = distro.detect()
        memsize = int(memory.meminfo.MemFree.b * 0.2)
        self.nr_pages = self.params.get(
            'nr_pages', default=memsize // memory.get_page_size())
        self.map_type = self.params.get('map_type', default='private')
        self.hpage = self.params.get('h_page', default=False)

        nodes = memory.numa_nodes_with_memory()
        pkgs = ['gcc', 'make']
        hp_check = 0
        if self.hpage:
            hp_size = memory.get_huge_page_size()
            for node in nodes:
                genio.write_file('/sys/devices/system/node/node%s/hugepages/hu'
                                 'gepages-%skB/nr_hugepages' %
                                 (node, str(hp_size)), str(self.nr_pages))
            for node in nodes:
                hp_check += int(genio.read_file(
                    '/sys/devices/system/node/node%s/hugepages/hugepages-%skB'
                    '/nr_hugepages' % (node, str(hp_size))).strip())
            if hp_check < self.nr_pages:
                self.cancel('Not enough pages to be configured on nodes')
        if dist.name in ["Ubuntu", 'debian']:
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

        for package in pkgs:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

        for file_name in ['util.c', 'numa_test.c', 'softoffline.c',
                          'bench_movepages.c', 'Makefile']:
            self.copyutil(file_name)

        build.make(self.teststmpdir)

    @skipIf(SINGLE_NODE, "Test requires two numa nodes to run")
    def test_movepages(self):
        os.chdir(self.teststmpdir)
        self.log.info("Starting test...")
        cmd = './numa_test -m %s -n %s' % (self.map_type, self.nr_pages)
        if self.hpage:
            cmd = '%s -h' % cmd
        ret = process.system(cmd, shell=True, sudo=True, ignore_status=True)
        if ret == 255:
            self.cancel("Environment prevents test! Check logs for issues")
        elif ret != 0:
            self.fail('Please check the logs for failure')

    def test_softoffline(self):
        """
        Test PFN's before and after offlining
        """
        self.nr_pages = self.params.get(
            'nr_pages', default=50)
        os.chdir(self.teststmpdir)
        self.log.info("Starting test...")
        cmd = './softoffline -m %s -n %s' % (self.map_type, self.nr_pages)
        ret = process.system(cmd, shell=True, sudo=True, ignore_status=True)
        if ret != 0:
            self.fail('Please check the logs for failure')

    @skipIf(SINGLE_NODE, "Test requires two numa nodes to run")
    def test_thp_compare(self):
        """
        Test PFN's before and after offlining
        """
        self.nr_pages = self.params.get(
            'nr_pages', default=100)
        os.chdir(self.teststmpdir)
        self.log.info("Starting test...")
        cmd = './bench_movepages -n %s' % self.nr_pages
        ret = process.system(cmd, shell=True, sudo=True, ignore_status=True)
        if ret != 0:
            self.fail('Please check the logs for failure')
