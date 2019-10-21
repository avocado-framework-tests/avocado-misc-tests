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
# Copyright: 2016 IBM
# Author: Pavithra <pavrampu@linux.vnet.ibm.com>

import os
from avocado import Test
from avocado import main
from avocado.utils import archive
from avocado.utils import build
from avocado.utils import distro
from avocado.utils import process
from avocado.utils.software_manager import SoftwareManager


class CRIU(Test):

    def setUp(self):
        sm = SoftwareManager()
        dist = distro.detect()
        packages = ['gcc', 'make', 'protobuf', 'protobuf-c', 'protobuf-c-devel',
                    'protobuf-compiler', 'protobuf-devel', 'protobuf-python',
                    'libnl3-devel', 'libcap-devel', 'libaio-devel']
        # FIXME: "redhat" as the distro name for RHEL is deprecated
        # on Avocado versions >= 50.0.  This is a temporary compatibility
        # enabler for older runners, but should be removed soon
        if dist.name not in ['rhel', 'redhat']:
            self.cancel('Currently test is supported only on RHEL')
        for package in packages:
            if not sm.check_installed(package) and not sm.install(package):
                self.cancel("Fail to install %s required for this test." %
                            package)
        criu_version = self.params.get('criu_version', default='2.6')
        tarball = self.fetch_asset(
                  "http://download.openvz.org/criu/criu-%s.tar.bz2" % criu_version,
                  expire='10d')
        archive.extract(tarball, self.workdir)
        self.sourcedir = os.path.join(
            self.workdir, os.path.basename(tarball.split('.tar')[0]))
        build.make(self.sourcedir)
        self.sourcedir = os.path.join(self.sourcedir, "test")

    def test(self):
        os.chdir(self.sourcedir)
        process.run("./zdtm.py run -a --report sergeyb --keep-going",
                    ignore_status=True, sudo=True)
        logfile = os.path.join(self.logdir, "stdout")
        failed_tests = process.system_output(
            "grep -w FAIL %s" % logfile, shell=True, ignore_status=True).decode("utf-8")
        if failed_tests:
            self.fail("test failed, Please check debug log for failed test cases")


if __name__ == "__main__":
    main()
