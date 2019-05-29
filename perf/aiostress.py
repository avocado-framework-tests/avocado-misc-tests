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
from avocado import main
from avocado.utils import process, distro
from avocado.utils.software_manager import SoftwareManager


class Aiostress(Test):

    """
    aio-stress is a basic utility for testing the Linux kernel AIO api
    """

    def setUp(self):
        """
        Build 'aiostress'.
        Source:
         https://oss.oracle.com/~mason/aio-stress/aio-stress.c
        """
        smm = SoftwareManager()
        packages = []
        dist_name = distro.detect().name.lower()
        if dist_name == 'ubuntu':
            packages.extend(['libaio1', 'libaio-dev'])
        # FIXME: "redhat" as the distro name for RHEL is deprecated
        # on Avocado versions >= 50.0.  This is a temporary compatibility
        # enabler for older runners, but should be removed soon
        elif dist_name in ['centos', 'fedora', 'rhel', 'redhat']:
            packages.extend(['libaio', 'libaio-devel'])
        elif dist_name == 'suse':
            packages.extend(['libaio1', 'libaio-devel'])

        for package in packages:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

        aiostress = self.fetch_asset(
            'https://oss.oracle.com/~mason/aio-stress/aio-stress.c')
        os.chdir(self.workdir)
        # This requires libaio.h in order to build
        # -laio -lpthread is provided at end as a workaround for Ubuntu
        process.run('gcc -Wall -o aio-stress %s -laio -lpthread' % aiostress)

    def test(self):
        """
        Run aiostress
        """
        os.chdir(self.workdir)
        # aio-stress needs a filename (foo) to run tests on.
        cmd = ('./aio-stress foo')
        process.run(cmd)


if __name__ == "__main__":
    main()
