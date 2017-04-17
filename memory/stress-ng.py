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
# Copyright: 2017 IBM
# Modified by : Abdul Haleem <abdhalee@linux.vnet.ibm.com>
# Author: Aneesh Kumar K.V <anesh.kumar@linux.vnet.ibm.com>
#

import os
from avocado import Test
from avocado import main
from avocado.utils import process, build, archive, distro
from avocado.utils.software_manager import SoftwareManager


def clear_dmesg():
    process.run("dmesg -c ", sudo=True)


def collect_dmesg(object):
    object.whiteboard = process.system_output("dmesg")


class stressng(Test):

    """
    Stress-ng testsuite
    :param stressor: Which streess-ng stressor to run (default is "mmapfork")
    :param timeout: Timeout for each run (default 300)
    :param workers: How many workers to create for each run (default 0)
    :source: git://kernel.ubuntu.com/cking/stress-ng.git
    """

    def setUp(self):
        sm = SoftwareManager()
        detected_distro = distro.detect()
        self.stressor = self.params.get('stressor', default='mmapfork')
        self.ttimeout = self.params.get('ttimeout', default=300)
        self.workers = self.params.get('workers', default=0)
        if 'Ubuntu' in detected_distro.name:
            deps = ['stress-ng', 'libaio-dev', 'libapparmor-dev', 'libattr1-dev', 'libbsd-dev',
                    'libcap-dev', 'libgcrypt11-dev', 'libkeyutils-dev', 'libsctp-dev', 'zlib1g-dev']
        else:
            deps = ['libattr-devel', 'libbsd-devel', 'libcap-devel',
                    'libgcrypt-devel', 'keyutils-libs-devel', 'zlib-devel', 'libaio-devel']
        for package in deps:
            if not sm.check_installed(package) and not sm.install(package):
                self.log.info(
                    '%s is needed, get the source and build' % package)

        if 'Ubuntu' not in detected_distro.name:
            tarball = self.fetch_asset('stressng.zip', locations=[
                                       'https://github.com/ColinIanKing/'
                                       'stress-ng/archive/master.zip'],
                                       expire='7d')
            archive.extract(tarball, self.srcdir)
            self.srcdir = os.path.join(self.srcdir, 'stress-ng-master')
            os.chdir(self.srcdir)
            result = build.run_make(self.srcdir, ignore_status=True)
            for line in str(result).splitlines():
                if 'error:' in line:
                    self.cancel(
                        "Unsupported OS, Please check the build logs !!")
            build.make(self.srcdir, extra_args='install')
        clear_dmesg()

    def test(self):
        cmd = ("stress-ng --aggressive --verify --timeout %d --%s %d"
               % (self.ttimeout, self.stressor, self.workers))
        process.run(cmd, ignore_status=True, sudo=True)
        collect_dmesg(self)


if __name__ == "__main__":
    main()
