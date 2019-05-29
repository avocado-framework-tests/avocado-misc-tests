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
from avocado import main
from avocado.utils import process, build, memory, archive
from avocado.utils.software_manager import SoftwareManager


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

        for pkg in ['gcc', 'make']:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel('%s is needed for the test to be run' % pkg)
        tarball = self.fetch_asset('memtester.zip',
                                   locations=['https://github.com/jnavila/'
                                              'memtester/archive/master.zip'],
                                   expire='7d')
        archive.extract(tarball, self.workdir)
        sourcedir = os.path.join(self.workdir, 'memtester-master')
        os.chdir(sourcedir)
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


if __name__ == "__main__":
    main()
