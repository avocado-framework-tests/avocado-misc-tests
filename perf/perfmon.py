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
#

import os

from avocado import Test
from avocado.utils import process, build, git, distro
from avocado.utils.software_manager.manager import SoftwareManager


class Perfmon(Test):

    """
    performance monitoring on Linux : test  perf_events on Linux
    :avocado: tags=perf,perfmon
    """

    def setUp(self):

        # Check for basic utilities
        smm = SoftwareManager()
        dist = distro.detect()

        deps = ["gcc", "make"]
        if dist.name in ['Ubuntu', 'debian']:
            deps.extend(['libncurses-dev'])
        elif dist.name in ['rhel', 'SuSE']:
            deps.extend(['ncurses-devel'])
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel(
                    "Fail to install %s required for this test." % package)

        git.get_repo('git://git.code.sf.net/p/perfmon2/libpfm4',
                     destination_dir=self.workdir)

        os.chdir(self.workdir)

        build.make('.')

    def test(self):

        out = process.system_output('%s ' % os.path.join(
            self.workdir, 'tests/validate')).decode("utf-8")
        if 'fail' in out:
            self.fail("test failed:check manually")
