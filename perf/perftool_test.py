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
#       :Sachin Sant <sachinp@linux.ibm.com>

import os
from avocado import Test
from avocado.utils import archive, build
from avocado.utils.software_manager.distro_packages import ensure_tool


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
        perf_path = self.params.get('perf_bin', default='')

        # Define distro-aware package map for perf and build deps
        distro_pkg_map = {
            "Ubuntu": [f"linux-tools-{os.uname()[2]}", "linux-tools-common", "gcc", "make"],
            "debian": [f"linux-tools-{os.uname()[2][3]}", "gcc", "make"],
            "centos": ["perf", "gcc", "make", "gcc-c++"],
            "fedora": ["perf", "gcc", "make", "gcc-c++"],
            "rhel": ["perf", "gcc", "make", "gcc-c++"],
            "SuSE": ["perf", "gcc", "make", "gcc-c++"],
        }

        try:
            perf_version = ensure_tool("perf",
                                       custom_path=perf_path,
                                       distro_pkg_map=distro_pkg_map)
            self.log.info(f"Perf version: {perf_version}")
            self.perf_bin = perf_path if perf_path else "perf"
        except RuntimeError as e:
            self.cancel(str(e))

        locations = ["https://github.com/rfmvh/perftool-testsuite/archive/"
                     "master.zip"]
        tarball = self.fetch_asset("perftool.zip", locations=locations,
                                   expire='7d')
        archive.extract(tarball, self.workdir)
        self.sourcedir = os.path.join(self.workdir,
                                      'perftool-testsuite-master')

    def test_perf_testsuite(self):
        '''
        Build perftool Test
        Source: https://github.com/rfmvh/perftool-testsuite
        '''
        count = 0
        for line in build.run_make(self.sourcedir, extra_args='check',
                                   process_kwargs={'ignore_status': True}
                                   ).stdout.decode("utf-8", "ignore").\
                splitlines():
            if '-- [ FAIL ] --' in line:
                count += 1
                self.log.info(line)
        if count > 0:
            self.fail("%s Test failed" % count)
