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
import signal

from avocado import Test
from avocado.utils import process, archive, build
from avocado.utils.software_manager.manager import SoftwareManager


class SpawnChild(Test):
    """
    Test to spawn child while mmap
    Reference: https://bugzilla.linux.ibm.com/show_bug.cgi?id=161674
    Source: https://bugzilla.linux.ibm.com/attachment.cgi?id=122561
    """

    def setUp(self):
        smm = SoftwareManager()

        for package in ['gcc-c++', 'make']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

        archive.extract(self.get_data("process_simple.zip"), self.workdir)
        build.make(self.workdir, extra_args="all")

    def test(self):
        os.chdir(self.workdir)
        self.log.info("Starting test...")
        for binary in ["process_exec_simple", "process_exec_simple_broken"]:
            count = 0
            proc = process.SubProcess('./%s' % binary, shell=True, sudo=True)
            pid = proc.start()
            if process.pid_exists(pid):
                while not proc.poll():
                    self.log.info("Waiting")
                    if not process.pid_exists(pid):
                        break
                    # Wait for ample time to check if process is still running
                    count += 1
                    if count == 400:
                        break

            if process.pid_exists(pid) and count == 400:
                process.kill_process_tree(pid, signal.SIGKILL)
                self.fail("Process simple HANGS, please raise a bug!")
