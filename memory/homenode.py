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
# Copyright: 2023 IBM
# Author: Geetika Moolchandani <geetika@linux.ibm.com>
#


import os
import shutil
from avocado import Test
from avocado.utils import process, build, memory, genio, distro
from avocado.utils.software_manager.manager import SoftwareManager


class HomeNodeTest(Test):
    """
    Test Description
    """

    def copyutil(self, file_name):
        shutil.copyfile(self.get_data(file_name),
                        os.path.join(self.teststmpdir, file_name))

    def setUp(self):
        smm = SoftwareManager()
        self.dist = distro.detect()

        self.nr_pages = self.params.get('nr_pages', default=100)
        self.map_type = self.params.get('map_type', default='private')
        self.hpage = self.params.get('h_page', default=False)
        self.pol_type = self.params.get('pol_type', default='MPOL_BIND')
        self.home_node = self.params.get('home_node', default=3)

        pkgs = ['gcc', 'make']

        if self.dist.name in ["Ubuntu", 'debian']:
            pkgs.extend(['libpthread-stubs0-dev',
                         'libnuma-dev', 'libhugetlbfs-dev'])
        elif self.dist.name in ["centos", "rhel", "fedora"]:
            if (self.dist.name == 'rhel' and self.dist.version >= '9'):
                self.cancel(
                    "libhugetlbfs packages are unavailable RHEL 9.x onwards.")
            pkgs.extend(['numactl-devel', 'libhugetlbfs-devel'])
        elif self.dist.name == "SuSE":
            pkgs.extend(['libnuma-devel'])
            if self.dist.version >= 15:
                pkgs.extend(['libhugetlbfs-devel'])
            else:
                pkgs.extend(['libhugetlbfs-libhugetlb-devel'])

        hp_configured = 0
        if self.hpage:
            hp_size = memory.get_huge_page_size()
            hp_configured += int(genio.read_file(
                '/sys/kernel/mm/hugepages/hugepages-%skB'
                '/nr_hugepages' % (str(hp_size))).strip())
            if hp_configured < self.nr_pages:
                self.cancel('Not enough pages to be configured on nodes')

        for package in ['gcc', 'make']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

        for file_name in ['homenode.c', 'Makefile']:
            self.copyutil(file_name)

        build.make(self.teststmpdir)

    def test(self):
        os.chdir(self.teststmpdir)
        cmd = './homenode -m %s' % self.map_type + \
            ' -f %s' % self.pol_type + ' -p%s' % self.home_node

        if self.hpage:
            if (self.dist.name == 'rhel' and self.dist.version >= '9'):
                self.cancel(
                    "Hugepage tests are cancelled on RHEL-9 and later.")
            cmd += ' -h %s' % self.hpage
        else:
            cmd += ' -n %s' % self.nr_pages

        ret = process.system(cmd, shell=True, sudo=True, ignore_status=True)
        if ret == 255:
            self.cancel("Environment prevents test! Check logs for node data")
        elif ret != 0:
            self.fail('Please check the logs for failure')
