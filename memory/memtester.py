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
# Copyright: 2017 IBM
# Author: Harish S <harish@linux.vnet.ibm.com>
#         Basheer K<basheer@linux.vnet.ibm.com>
#

import os
from avocado import Test
from avocado.utils import process, build, memory, archive
from avocado.utils.software_manager.manager import SoftwareManager


class Memtester(Test):
    """
    1.memtester  is  an  effective  userspace  tester  for stress-testing the
      memory subsystem.  It is very effective  at  finding  intermittent  and
      non-deterministic  faults.
    2.memtester must be run with  root  privileges  to  mlock(3)  its  pages.
      Testing  memory  without locking the pages in place is mostly pointless
      and slow.

    :avocado: tags=memory,privileged
    """

    def setUp(self):
        '''
        Setup memtester
        '''
        smm = SoftwareManager()

        for pkg in ['gcc', 'make', 'patch']:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel('%s is needed for the test to be run' % pkg)
        try:
            gcc_version_output = process.run('gcc --version', shell=True).stdout_text
            gcc_major_version = int(gcc_version_output.split()[2].split('.')[0])
            self.log.info(f"Detected GCC version: {gcc_major_version}")
        except Exception as e:
            self.log.warning(f"Could not detect GCC version: {e}. Assuming patch is needed.")
            gcc_major_version = 15
        tarball = self.fetch_asset('memtester.zip',
                                   locations=['https://github.com/jnavila/'
                                              'memtester/archive/master.zip'],
                                   expire='7d')
        archive.extract(tarball, self.workdir)
        sourcedir = os.path.join(self.workdir, 'memtester-master')
        os.chdir(sourcedir)
        if gcc_major_version >= 15:
            memtester_patch = 'patch -p0 < %s' % os.path.abspath(
                self.get_data('memtester_gcc15.patch'))
            try:
                process.run(memtester_patch, shell=True)
                self.log.info("Applied memtester patch to fix GCC 15+ compilation issues")
            except Exception as e:
                self.cancel(f"Failed to apply required GCC 15+ patch: {e}. "
                            f"This patch is mandatory for GCC {gcc_major_version} to avoid "
                            f"implicit function declaration errors during compilation.")
        else:
            self.log.info(f"GCC version {gcc_major_version} detected. Patch not required.")
        process.system('chmod 755 extra-libs.sh', shell=True, sudo=True,
                       ignore_status=True)
        build.make(sourcedir)

    def test(self):
        '''
        Run memtester
        '''
        mem = self.params.get('memory', default=memory.meminfo.MemFree.m)
        runs = self.params.get('runs', default=1)
        phyaddr = self.params.get('physaddr', default=None)

        # Basic Memtester usecase
        if process.system("./memtester %s %s" % (mem, runs), verbose=True,
                          sudo=True,
                          ignore_status=True):
            self.fail("memtester failed for free space %s" % mem)

        if phyaddr:
            # To verify -p option if provided in the yaml file
            device = self.params.get('device', default='/dev/mem')
            if process.system("./memtester -p %s -d %s %s %s" %
                              (phyaddr, device, mem, runs), verbose=True,
                              sudo=True, ignore_status=True):
                self.fail("memtester failed for address %s" % phyaddr)
