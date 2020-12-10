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
# Author: Abdul Haleem <abdhalee@linux.vnet.ibm.com>

import os
import platform
import re
import glob

from avocado import Test
from avocado.utils import build
from avocado.utils import distro
from avocado.utils import archive, git
from avocado.utils.software_manager import SoftwareManager


class kselftest(Test):

    """
    Linux Kernel Selftest available as a part of kernel source code.
    run the selftest available at tools/testing/selftest

    :see: https://www.kernel.org/doc/Documentation/kselftest.txt
    :source: https://github.com/torvalds/linux/archive/master.zip

    :avocado: tags=kernel
    """

    testdir = 'tools/testing/selftests'

    def find_match(self, match_str, line):
        match = re.search(match_str, line)
        if match:
            self.error = True
            self.log.info("Testcase failed. Log from debug: %s" %
                          match.group(0))

    def setUp(self):
        """
        Resolve the packages dependencies and download the source.
        """
        smg = SoftwareManager()
        self.comp = self.params.get('comp', default='')
        self.run_type = self.params.get('type', default='upstream')
        if self.comp:
            self.comp = '-C %s' % self.comp
        detected_distro = distro.detect()
        deps = ['gcc', 'make', 'automake', 'autoconf', 'rsync']

        if detected_distro.name in ['Ubuntu', 'debian']:
            deps.extend(['libpopt0', 'libc6', 'libc6-dev', 'libcap-dev',
                         'libpopt-dev', 'libcap-ng0', 'libcap-ng-dev',
                         'libnuma-dev', 'libfuse-dev', 'elfutils', 'libelf1',
                         'libhugetlbfs-dev'])
        elif 'SuSE' in detected_distro.name:
            deps.extend(['glibc', 'glibc-devel', 'popt-devel', 'sudo',
                         'libcap2', 'libcap-devel', 'libcap-ng-devel',
                         'fuse', 'fuse-devel', 'glibc-devel-static'])
            if detected_distro.version >= 15:
                deps.extend(['libhugetlbfs-devel'])
            else:
                deps.extend(['libhugetlbfs-libhugetlb-devel'])
        elif detected_distro.name in ['centos', 'fedora', 'rhel']:
            deps.extend(['popt', 'glibc', 'glibc-devel', 'glibc-static',
                         'libcap-ng', 'libcap', 'libcap-devel', 'fuse-devel',
                         'libcap-ng-devel', 'popt-devel',
                         'libhugetlbfs-devel'])

        for package in deps:
            if not smg.check_installed(package) and not smg.install(package):
                self.cancel(
                    "Fail to install %s required for this test." % (package))

        if self.run_type == 'upstream':
            location = self.params.get('location', default='https://github.c'
                                       'om/torvalds/linux/archive/master.zip')
            path = ''
            match = next(
                (ext for ext in [".zip", ".tar"] if ext in location), None)
            if match:
                tarball = self.fetch_asset("kselftest%s" % match,
                                           locations=[location], expire='1d')
                archive.extract(tarball, self.workdir)
                path = glob.glob(os.path.join(self.workdir, "linux*"))
            else:
                git.get_repo(location, destination_dir=self.workdir)
                path = glob.glob(self.workdir)
            for l_dir in path:
                if os.path.isdir(l_dir) and 'Makefile' in os.listdir(l_dir):
                    self.buldir = os.path.join(self.workdir, l_dir)
                    break
        else:
            # Make sure kernel source repo is configured
            if detected_distro.name in ['centos', 'fedora', 'rhel']:
                src_name = 'kernel'
                if detected_distro.name == 'rhel':
                    # Check for "el*a" where ALT always ends with 'a'
                    if platform.uname()[2].split(".")[-2].endswith('a'):
                        self.log.info('Using ALT as kernel source')
                        src_name = 'kernel-alt'
                self.buldir = smg.get_source(src_name, self.workdir)
                self.buldir = os.path.join(
                    self.buldir, os.listdir(self.buldir)[0])
            elif detected_distro.name in ['Ubuntu', 'debian']:
                self.buldir = smg.get_source('linux', self.workdir)
            elif 'SuSE' in detected_distro.name:
                if not smg.check_installed("kernel-source") and not\
                        smg.install("kernel-source"):
                    self.cancel(
                        "Failed to install kernel-source for this test.")
                if not os.path.exists("/usr/src/linux"):
                    self.cancel("kernel source missing after install")
                self.buldir = "/usr/src/linux"

        self.sourcedir = os.path.join(self.buldir, self.testdir)
        if build.make(self.sourcedir):
            self.fail("Compilation failed, Please check the build logs !!")

    def test(self):
        """
        Execute the kernel selftest
        """
        self.error = False
        build.make(self.sourcedir,
                   extra_args='summary=1 %s run_tests' % self.comp)
        for line in open(os.path.join(self.logdir, 'debug.log')).readlines():
            self.find_match(r'not ok (.*) selftests:(.*)', line)

        if self.error:
            self.fail("Testcase failed during selftests")
