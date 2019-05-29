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
# Copyright: 2017 IBM
# Author: Harish Sriram <harish@linux.vnet.ibm.com>
#


import os

from avocado import Test
from avocado import main
from avocado.utils import archive, build, process, distro, cpu
from avocado.utils.software_manager import SoftwareManager


class Numatop(Test):

    """
    Test case of numatop functionality
    Test runs mgen application to check numatop snapshot registers it

    :avocado: tags=cpu,privileged
    """

    def setUp(self):
        '''
        Build numatop Test
        Source:
        https://github.com/01org/numatop.git
        '''

        # Check for basic utilities
        # TODO: Add support for other distributions
        self.numa_pid = None
        detected_distro = distro.detect().name.lower()
        if not detected_distro == "ubuntu":
            self.cancel("Upsupported OS %s" % detected_distro)
        smm = SoftwareManager()
        for package in ['gcc', 'numatop', 'make', 'libnuma-dev',
                        'libncurses-dev']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel("Failed to install %s, which is needed for"
                            "the test to be run" % package)

        locations = ["https://github.com/intel/numatop/archive/master.zip"]
        tarball = self.fetch_asset("numatop.zip", locations=locations,
                                   expire='7d')
        archive.extract(tarball, self.workdir)
        self.sourcedir = os.path.join(self.workdir, 'numatop-master')

        os.chdir(self.sourcedir)
        process.run('./autogen.sh', shell=True, sudo=True)
        build.make(self.sourcedir, extra_args='check')

    def test(self):

        mgen_flag = False
        mgen = os.path.join(self.sourcedir, 'mgen')
        self.numa_pid = process.SubProcess(
            'numatop -d result_file', shell=True)
        self.numa_pid.start()

        # Run mgen for 5 seconds to generate a single snapshot of numatop
        process.run('%s -a 0 -c %s -t 5' %
                    (mgen, cpu.cpu_online_list()[0]), shell=True, sudo=True)

        # Kill numatop recording after running mgen
        self.numa_pid.terminate()

        # Analyse record file for mgen record
        with open('%s/result_file' % self.sourcedir, 'r') as f_read:
            lines = f_read.readlines()
            for line in lines:
                if 'mgen' in line:
                    mgen_flag = True
                    break
        if not mgen_flag:
            self.fail('Numatop failed to record mgen latency. Please check '
                      'the record file: %s/result_file' % self.sourcedir)


if __name__ == "__main__":
    main()
