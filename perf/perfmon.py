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
from avocado.utils import process, build, git
from avocado.utils.software_manager.distro_packages import ensure_tool


class Perfmon(Test):

    """
    performance monitoring on Linux : test  perf_events on Linux
    :avocado: tags=perf,perfmon
    """

    def setUp(self):

        # Check for basic utilities
        perf_path = self.params.get('perf_bin', default='')

        # Define distro-aware package map for build deps
        distro_pkg_map = {
            "Ubuntu": ["libncurses-dev", "gcc", "make"],
            "debian": ["libncurses-dev", "gcc", "make"],
            "centos": ["ncurses-devel", "gcc", "make"],
            "fedora": ["ncurses-devel", "gcc", "make"],
            "rhel": ["ncurses-devel", "gcc", "make"],
            "SuSE": ["ncurses-devel", "gcc", "make"],
        }

        try:
            # Ensure toolchain and ncurses dev packages are present
            ensure_tool("gcc", distro_pkg_map=distro_pkg_map)
            ensure_tool("make", distro_pkg_map=distro_pkg_map)
        except RuntimeError as e:
            self.cancel(str(e))

        git.get_repo('https://git.code.sf.net/p/perfmon2/libpfm4',
                     destination_dir=self.workdir)

        os.chdir(self.workdir)

        build.make('.')

    def test(self):

        out = process.system_output('%s ' % os.path.join(
            self.workdir, 'tests/validate')).decode("utf-8")
        if 'fail' in out:
            self.fail("test failed:check manually")
