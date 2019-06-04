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
from avocado.utils import process, build, memory
from avocado.utils.software_manager import SoftwareManager


class KsmPoison(Test):
    """
    Exercise Kernel Samepage Merging (KSM) through madvise call to share
    machine's free mapped memory and accesses the pages through memset

    :avocado: tags=memory,ksm
    """

    def copyutil(self, file_name):
        shutil.copyfile(self.get_data(file_name),
                        os.path.join(self.teststmpdir, file_name))

    def setUp(self):
        smm = SoftwareManager()
        memsize = int(memory.meminfo.MemFree.b * 0.1)
        self.nr_pages = self.params.get('nr_pages', default=None)
        self.offline = self.params.get('offline', default='s')
        self.touch = self.params.get('touch', default=True)

        if not self.nr_pages:
            self.nr_pages = int(memsize / memory.get_page_size())

        for package in ['gcc', 'make']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

        for file_name in ['ksm_poison.c', 'Makefile']:
            self.copyutil(file_name)

        build.make(self.teststmpdir)

    def test(self):
        os.chdir(self.teststmpdir)
        cmd = './ksm_poison -n %s' % str(self.nr_pages / 2)
        if self.touch:
            cmd = '%s -t' % cmd
        if self.offline:
            cmd = '%s -%s' % (cmd, self.offline)
        ksm = process.SubProcess(cmd, shell=True, sudo=True)
        ksm.start()
        ksm.wait()

        if ksm.result.exit_status:
            self.fail("Please check the logs for debug")


if __name__ == "__main__":
    main()
