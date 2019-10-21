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
# Copyright: 2019 IBM.
# Author: Naveen kumar T<naveet89@in.ibm.com>

import os
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils import distro
from avocado.utils.software_manager import SoftwareManager


class PerfInvalid(Test):

    """
    Performance analysis tools for Linux
    :avocado: tags=privileged,perf,invalid

    """

    def setUp(self):
        smg = SoftwareManager()
        dist = distro.detect()
        if 'Ubuntu' in dist.name:
            linux_tools = "linux-tools-" + os.uname()[2]
            pkgs = ['linux-tools-common', linux_tools]
        elif dist.name in ['centos', 'fedora', 'rhel', 'SuSE']:
            pkgs = ['perf']
        else:
            self.cancel("perf is not supported on %s" % dist.name)

        for pkg in pkgs:
            if not smg.check_installed(pkg) and not smg.install(pkg):
                self.cancel(
                    "Package %s is missing/could not be installed" % pkg)

    def test_perf_invalid_flag(self):
        cmd = "perf --version -test"
        output = process.run(cmd, ignore_status="True", sudo="True", shell="True")
        if output.exit_status == -11:
            self.fail("perf: failed to execute command %s" % cmd)


if __name__ == "__main__":
    main()
