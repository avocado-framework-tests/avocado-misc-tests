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
# Copyright: 2016 IBM
# Author: Pooja B Surya <pooja@linux.vnet.ibm.com>
#
# Based on code by  Michal Piotrowski <michal.k.k.piotrowski@gmail.com>
# Based on code by  Martin Bligh <mbligh@google.com>
# Based on code by  Michal Piotrowski <michal.k.k.piotrowski@gmail.com>
#
#  https://github.com/autotest/autotest-client-tests/tree/master/signaltes/
#  https://github.com/autotest/autotest-client-tests/blob/master/pi_tests
#  https://github.com/autotest/autotest-client-tests/tree/master/cyclictest


import os
from avocado import Test
from avocado import main
from avocado.utils import archive
from avocado.utils import build
from avocado.utils import process
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import distro


class rt_tests(Test):

    def setUp(self):
        # Check for basic utilities
        sm = SoftwareManager()
        detected_distro = distro.detect()
        deps = ["gcc", "make"]
        if detected_distro.name == "SuSE":
            deps.append("git-core")
        else:
            deps.append("git")
        if detected_distro.name == "Ubuntu":
            deps.append("build-essential")
            deps.append("libnuma-dev")
        elif detected_distro.name in ['centos', 'fedora', 'rhel', 'redhat']:
            deps.append("numactl-devel")
        for package in deps:
            if not sm.check_installed(package) and not sm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        tarball = self.fetch_asset(
            "https://www.kernel.org/pub/linux/utils/rt-tests/"
            "rt-tests-1.0.tar.gz")
        archive.extract(tarball, self.workdir)
        self.sourcedir = os.path.join(
            self.workdir, os.path.basename(tarball.split('.tar.')[0]))
        build.make(self.sourcedir)

    def test(self):
        test_to_run = self.params.get('test_to_run', default='signaltest')
        args = self.params.get('args', default=' -t 10 -l 100000')
        process.system("%s %s" % (os.path.join(self.sourcedir, test_to_run), args),
                       sudo=True)


if __name__ == "__main__":
    main()
