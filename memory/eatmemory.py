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
# Copyright: 2016 IBM
# Author: Santhosh G <santhog4@linux.vnet.ibm.com>

import os
from avocado import Test
from avocado.utils import build
from avocado.utils import git
from avocado.utils import memory
from avocado.utils import process
from avocado.utils import distro
from avocado.utils.software_manager import SoftwareManager


class eatmemory(Test):

    def setUp(self):
        sm = SoftwareManager()
        detected_distro = distro.detect()
        deps = ['gcc', 'make', 'git']
        for package in deps:
            if package == 'git' and detected_distro.name == "SuSE":
                package = 'git-core'
            if not sm.check_installed(package) and not sm.install(package):
                self.error(package + ' is needed for the test to be run')
        git.get_repo('https://github.com/julman99/eatmemory.git',
                     destination_dir=self.srcdir)
        os.chdir(self.srcdir)
        build.make(self.srcdir)
        self.total_mem_in_bytes = int(memory.memtotal()) * 1024
        self.total_mem_in_units = self.mem_in_units(self.total_mem_in_bytes)
        unit = self.total_mem_in_units[-1]
        if unit == 'B' or unit == 'K':
            self.total_mem_in_units = self.total_mem_in_units[0:-1]

    def mem_in_units(self, memory):
        for x in ['B', 'K', 'M', 'G']:
            if memory < 1024.0:
                return "%3.1f%s" % (memory, x)
            memory /= 1024.0
        #Since Tb is Invalid in eatmemory G is returned
        return "%3.1f%s" % (memory, 'G')

    def test(self):
        memory_to_test = self.params.get('memory_to_test',
                                         default=self.total_mem_in_units)
        os.chdir(self.srcdir)
        output = process.system_output('./eatmemory %s' % memory_to_test,
                                       ignore_status=True)
        self.log.info(output)
        if 'Done, press any key to free the memory' in output:
            self.log.info('The Given memory Has been Eaten Successfully')
        else:
            self.fail('Given memory not eaten properly !!! \n'
                      'Please Check Logs')
