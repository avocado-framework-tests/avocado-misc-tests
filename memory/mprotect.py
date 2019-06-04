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


class Mprotect(Test):
    """
    Uses mprotect call to protect 90% of the machine's free
    memory and accesses with PROT_READ, PROT_WRITE and PROT_NONE

    :avocado: tags=memory
    """

    def copyutil(self, file_name):
        shutil.copyfile(self.get_data(file_name),
                        os.path.join(self.teststmpdir, file_name))

    def setUp(self):
        smm = SoftwareManager()
        self.nr_pages = self.params.get('nr_pages', default=None)
        self.in_err = self.params.get('induce_err', default=0)
        self.failure = self.params.get('failure', default=False)

        if not self.nr_pages:
            memsize = int(memory.meminfo.MemFree.b * 0.9)
            self.nr_pages = memsize / memory.get_page_size()

        for package in ['gcc', 'make']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

        for file_name in ['mprotect.c', 'Makefile']:
            self.copyutil(file_name)

        build.make(self.teststmpdir)

    def test(self):
        os.chdir(self.teststmpdir)
        self.log.info("Starting test...")

        ret = process.system('./mprotect %s %s' % (self.nr_pages, self.in_err),
                             shell=True, ignore_status=True, sudo=True)
        if self.failure:
            if ret != 255:
                self.fail("Please check the logs for debug")
            else:
                self.log.info("Failed as expected")
        else:
            if ret is not 0:
                self.fail("Please check the logs for debug")
            else:
                self.log.info("Passed as expected")


if __name__ == "__main__":
    main()
