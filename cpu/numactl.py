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
# Author:Praveen K Pandey <praveen@linux.vnet.ibm.com>
#


import os

from avocado import Test
from avocado import main
from avocado.utils import archive, build, process, distro, memory
from avocado.utils.software_manager import SoftwareManager


class Numactl(Test):

    """
    Self test case of numactl

    :avocado: tags=cpu
    """

    def setUp(self):
        '''
        Build Numactl Test
        Source:
        https://github.com/numactl/numactl
        '''
        # Check for basic utilities
        smm = SoftwareManager()

        detected_distro = distro.detect()
        deps = ['gcc', 'libtool', 'autoconf', 'automake', 'make']
        if detected_distro.name == "Ubuntu":
            deps.extend(['libnuma-dev'])
        elif detected_distro.name in ["centos", "rhel", "fedora"]:
            deps.extend(['numactl-devel'])
        else:
            deps.extend(['libnuma-devel'])

        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel("Failed to install %s, which is needed for"
                            "the test to be run" % package)

        locations = ["https://github.com/numactl/numactl/archive/master.zip"]
        tarball = self.fetch_asset("numactl.zip", locations=locations,
                                   expire='7d')
        archive.extract(tarball, self.workdir)
        self.sourcedir = os.path.join(self.workdir, 'numactl-master')

        os.chdir(self.sourcedir)
        process.run('./autogen.sh', shell=True)

        process.run('./configure', shell=True)

        build.make(self.sourcedir)

    def test(self):

        if build.make(self.sourcedir, extra_args='-k -j 1'
                      ' test', ignore_status=True):
            if len(memory.numa_nodes_with_memory()) < 2:
                self.log.warn('Few tests failed due to less NUMA mem-nodes')
            else:
                self.fail('test failed, Please check debug log')


if __name__ == "__main__":
    main()
