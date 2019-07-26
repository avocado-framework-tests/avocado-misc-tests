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
# Copyright: 2016 IBM
# Author:Praveen K Pandey <praveen@linux.vnet.ibm.com>

import os
import platform
from avocado import Test
from avocado import main
from avocado.utils import archive, build, distro, process
from avocado.utils.software_manager import SoftwareManager


class Perftool(Test):

    """
    perftool-testsuite
    :avocado: tags=perf,testsuite
    """

    def setUp(self):
        '''
        Install the basic packages to support perf
        '''

        # Check for basic utilities
        smm = SoftwareManager()
        detected_distro = distro.detect()
        deps = ['gcc', 'make', 'gcc-c++']
        if 'Ubuntu' in detected_distro.name:
            deps.extend(['linux-tools-common', 'linux-tools-%s' %
                         platform.uname()[2]])
        # FIXME: "redhat" as the distro name for RHEL is deprecated
        # on Avocado versions >= 50.0.  This is a temporary compatibility
        # enabler for older runners, but should be removed soon
        elif detected_distro.name in ['rhel', 'SuSE', 'fedora',
                                      'centos', 'redhat']:
            deps.extend(['perf'])
        else:
            self.cancel("Install the package for perf supported\
                      by %s" % detected_distro.name)
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

        locations = ["https://github.com/rfmvh/perftool-testsuite/archive/"
                     "master.zip"]
        tarball = self.fetch_asset("perftool.zip", locations=locations,
                                   expire='7d')
        archive.extract(tarball, self.workdir)
        self.sourcedir = os.path.join(self.workdir,
                                      'perftool-testsuite-master')

    def test(self):
        '''
        1.perf test :Does sanity tests and
          execute the tests by calling each module
        2.Build perftool Test
          Source:
          https://github.com/rfmvh/perftool-testsuite
        '''
        count = 0
        # Built in perf test
        for string in process.run("perf test", ignore_status=True).stderr.splitlines():
            if 'FAILED' in string:
                self.log.info("Test case failed is %s" % string)

        # perf testsuite
        for line in build.run_make(self.sourcedir, extra_args='check',
                                   process_kwargs={'ignore_status': True}
                                   ).stdout.splitlines():
            if '-- [ FAIL ] --' in line:
                count += 1
                self.log.info(line)

        if count > 0:
            self.fail("%s Test failed" % count)


if __name__ == "__main__":
    main()
