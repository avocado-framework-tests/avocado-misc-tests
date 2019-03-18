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
# Copyright: 2019 IBM
# Author: Harish <harish@linux.vnet.ibm.com>

import os
from avocado import Test
from avocado import main
from avocado.utils import archive, build, cpu, memory, process
from avocado.utils.software_manager import SoftwareManager


class StressAppTest(Test):

    def setUp(self):
        self.test_file = self.params.get('tmp_file', default='/tmp/dummy')
        self.duration = self.params.get('duration', default='30')
        self.threads = self.params.get(
            'threads', default=cpu.online_cpus_count())
        self.size = self.params.get(
            'memory_to_test', default=int(0.9 * memory.meminfo.MemFree.m))

        smm = SoftwareManager()
        for package in ['gcc', 'libtool', 'autoconf', 'automake', 'make']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel("Failed to install %s, which is needed for"
                            "the test to be run" % package)

        if not os.path.exists(self.test_file):
            try:
                os.mknod(self.test_file)
            except OSError:
                self.cancel("Skipping test since test file creation failed")
        loc = ["https://github.com/stressapptest/"
               "stressapptest/archive/master.zip"]
        tarball = self.fetch_asset("stressapp.zip", locations=loc,
                                   expire='7d')
        archive.extract(tarball, self.workdir)
        self.sourcedir = os.path.join(self.workdir, 'stressapptest-master')

        os.chdir(self.sourcedir)
        process.run('./configure', shell=True)

        build.make(self.sourcedir)

    def test(self):
        os.chdir(os.path.join(self.sourcedir, "src"))
        run_cmd = "./stressapptest -s %s -M %s -m %s -C %s -i %s -W -f %s" % (
            self.duration, self.size, self.threads,
            self.threads, self.threads, self.test_file)
        if process.system(run_cmd, sudo=True, shell=True):
            self.fail("Test failed! Please check the logs")

    def tearDown(self):
        try:
            os.remove(self.test_file)
        except OSError:
            self.log.warn("Failed to remove fail")


if __name__ == "__main__":
    main()
