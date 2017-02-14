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
# Author: Basheer K<basheer@linux.vnet.ibm.com>
#

import os
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils import build
from avocado.utils import memory
from avocado.utils import git
from avocado.utils import distro
from avocado.utils.software_manager import SoftwareManager


class Memtester(Test):
    """
    1.memtester  is  an  effective  userspace  tester  for stress-testing the
      memory subsystem.  It is very effective  at  finding  intermittent  and
      non-deterministic  faults.
    2.memtester must be run with  root  privileges  to  mlock(3)  its  pages.
      Testing  memory  without locking the pages in place is mostly pointless
      and slow.
    """

    def setUp(self):
        sm = SoftwareManager()
        detected_distro = distro.detect()
        deps = ['gcc', 'make']
        if detected_distro.name == "SuSE":
            deps.append('git-core')
        else:
            deps.append('git')
        for pkg in deps:
            if not sm.check_installed(pkg) and not sm.install(pkg):
                self.error('%s is needed for the test to be run' % pkg)

        git.get_repo('https://github.com/jnavila/memtester.git',
                     destination_dir=self.srcdir)
        os.chdir(self.srcdir)
        os.system('chmod 755 extra-libs.sh')
        build.make(self.srcdir)

    def test_memster(self):
        free_mem = int(memory.freememtotal() / 1024)
        os.chdir(self.srcdir)
        mem = self.params.get('memory', default=free_mem)
        runs = self.params.get('runs', default=1)
        phyaddr = self.params.get('physaddr', default=None)

        # Basic Memtester usecase
        ret = process.run("./memtester %s %s" % (mem, runs),
                          sudo=True,
                          ignore_status=True)

        if ret.exit_status:
            self.fail("memtester failed with %s exit status" % ret.exit_status)

        if phyaddr:
            # To verify -p option if provided in the yaml file
            ret = process.run("./memtester -p %s 64k %s" % (phyaddr, runs),
                              sudo=True,
                              ignore_status=True)
            if ret.exit_status:
                self.fail(
                    "memtester failed with %s exit status" %
                    ret.exit_status)

if __name__ == "__main__":
    main()
