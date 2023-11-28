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
# Copyright: 2016 Red Hat, Inc
# Author: Amador Pahim <apahim@redhat.com>
#         Harish <harish@linux.vnet.ibm.com>
#
# Based on code by Masoud Asgharifard Sharbiani <masouds@google.com>
#   copyright 2006 Google
#   https://github.com/autotest/autotest-client-tests/tree/master/aiostress


import os

from avocado import Test
from avocado.utils import process, archive, build, distro
from avocado.utils.software_manager.manager import SoftwareManager


class Aiostress(Test):

    """
    aio-stress is a basic utility for testing the Linux kernel AIO api
    """

    def setUp(self):
        """
        Build 'aiostress'.
        Source:
         https://github.com/linux-test-project/ltp/blob/master/
         testcases/kernel/io/ltp-aiodio/aio-stress.c
        """
        smm = SoftwareManager()
        packages = ['make', 'gcc', 'autoconf', 'automake', 'pkg-config']
        dist_name = distro.detect().name.lower()
        if dist_name == 'ubuntu':
            packages.extend(['libaio1', 'libaio-dev'])
        elif dist_name in ['centos', 'fedora', 'rhel']:
            packages.extend(['libaio', 'libaio-devel'])
        elif dist_name == 'suse':
            packages.extend(['libaio1', 'libaio-devel'])
        for package in packages:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

        url = self.params.get(
            'url', default='https://github.com/linux-test-project/ltp/archive/master.zip')
        tarball = self.fetch_asset(url, expire='7d')
        archive.extract(tarball, self.workdir)
        ltp_dir = os.path.join(self.workdir, "ltp-master")
        os.chdir(ltp_dir)
        build.make(ltp_dir, extra_args='autotools')
        process.system('./configure')
        ltp_aio = os.path.join(ltp_dir, "testcases/kernel/io/ltp-aiodio/")
        os.chdir(ltp_aio)
        build.make(ltp_aio)

    def test(self):
        """
        Run aiostress
        """
        process.system('./aio-stress')
