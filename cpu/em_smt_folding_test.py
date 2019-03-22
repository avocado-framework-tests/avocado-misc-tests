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
#       : Praveen K Pandey <praveen@linux.vnet.ibm.com>

import os
import platform
from avocado import Test
from avocado import main
from avocado.utils import archive, build
from avocado.utils import process, cpu, distro
from avocado.utils.software_manager import SoftwareManager


class SmtFolding(Test):
    """
    Throughput test for SMT folding in presence of swizzle.
    TODO :  add logic to  Revert back  value smt and cpu  state
            as it was before test.
    """

    def setUp(self):
        '''
        Build ebizzy
        '''
        if 'ppc' not in distro.detect().arch:
            self.cancel("Processor is not ppc64")
        smg = SoftwareManager()
        detected_distro = distro.detect()
        deps = ['gcc', 'make', 'patch']
        if 'Ubuntu' in detected_distro.name:
            deps.extend(['linux-tools-common', 'linux-tools-%s'
                         % platform.uname()[2]])
        elif detected_distro.name == "SuSE":
            deps.extend(['cpupower'])
        else:
            deps.extend(['kernel-tools'])
        for package in deps:
            if not smg.check_installed(package) and not smg.install(package):
                self.cancel("%s is needed for the test to be run" % package)
        tarball = self.fetch_asset('http://liquidtelecom.dl.sourceforge.net'
                                   '/project/ebizzy/ebizzy/0.3'
                                   '/ebizzy-0.3.tar.gz')
        archive.extract(tarball, self.workdir)
        version = os.path.basename(tarball.split('.tar.')[0])
        self.sourcedir = os.path.join(self.workdir, version)

        patch = self.params.get(
            'patch', default='Fix-build-issues-with-ebizzy.patch')

        os.chdir(self.sourcedir)
        fix_patch = 'patch -p0 < %s' % (self.get_data(patch))
        process.run(fix_patch, shell=True)
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
        if int(throughput_off) > int(throughput_on):
            self.log.info("PASS : Single thread performance is better than"
                          " multi-thread performance ")
        else:
            self.fail("FAIL : Performance is degraded when SMT off")

    def run_ebizzy(self):
        '''
        Run ebizzy by doing taskset
        '''
        output = process.system_output("taskset -c %s ./ebizzy -t1"
                                       " -S 6 -s 4096" % self.cpu, shell=True)
        return output.split()[0]


if __name__ == "__main__":
    main()
