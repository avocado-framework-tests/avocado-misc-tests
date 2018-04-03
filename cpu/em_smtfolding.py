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
#
# Copyright: 2018 IBM
# Author: Shriya Kulkarni <shriyak@linux.vnet.ibm.com>
import os
from avocado import Test
from avocado import main
from avocado.utils import archive
from avocado.utils import process
from avocado.utils import build
from avocado.utils import process, cpu
from avocado.utils.software_manager import SoftwareManager


class smt_folding(Test):
    """
    Throughput test for SMT folding in presence of swizzle.
    """
    def setUp(self):
        '''
        1.Build ebizzy
        '''
        sm = SoftwareManager()
        for package in ['gcc', 'make']:
            if not sm.check_installed(package) and not sm.install(package):
                self.cancel("%s is needed for the test to be run" % package)
        tarball = self.fetch_asset('http://liquidtelecom.dl.sourceforge.net'
                                   '/project/ebizzy/ebizzy/0.3'
                                   '/ebizzy-0.3.tar.gz')
        archive.extract(tarball, self.srcdir)
        version = os.path.basename(tarball.split('.tar.')[0])
        self.sourcedir = os.path.join(self.srcdir, version)
        os.chdir(self.sourcedir)
        process.run("./configure")
        build.make(self.sourcedir)

    def test(self):
        '''
        1. Disable all the idle states
        2. Run ebizzy when smt=off and smt=on
        3. Enable all the idle states.
        '''
        self.cpu = 0
        cpu.online(self.cpu)
        # Disable the idle states
        process.run("cpupower idle-set -D 0", shell=True)
        process.system_output("ppc64_cpu --smt=off", shell=True)
        throughput_off = self.run_ebizzy()
        process.system_output("ppc64_cpu --smt=on", shell=True)
        throughput_on = self.run_ebizzy()
        # Enable the idle states
        process.run("cpupower idle-set -E 0", shell=True)
        if (int(throughput_off) > int(throughput_on)):
            self.log.info("PASS : Single thread performance is more than"
                          " multi-thread performance ")
        else:
            self.fail("FAIL : Single threaded performance is less than"
                      " multi thread performance ")

    def run_ebizzy(self):
        '''
        Run ebizzy by doing taskset
        '''
        output = process.system_output("taskset -c %s ./ebizzy -t1"
                                       " -S 6 -s 4096" % self.cpu, shell=True)
        return (output.split('\n', 1)[0]).split(' ')[0]


if __name__ == "__main__":
    main()
