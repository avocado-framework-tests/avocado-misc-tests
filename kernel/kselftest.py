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

from avocado import Test
from avocado import main
from avocado.utils import git
from avocado.utils import build
from avocado.utils import distro
from avocado.utils import archive
from avocado.utils.software_manager import SoftwareManager


class kselftest(Test):

    """
    Linux Kernel Selftest available with the source tar ball.
    Download linux source repository for the given git/http/tar location
    run the selftest available at tools/testing/selftest

    :see: https://www.kernel.org/doc/Documentation/kselftest.txt

    :param url: git/http link to the linux source repository or tar ball
    :param version: linux kernel version to download the tar file
    """

    testdir = 'tools/testing/selftests'

    def setUp(self):
        """
        Resolve the packages dependencies and download the source.
        """
        smg = SoftwareManager()
        detected_distro = distro.detect()
        deps = ['gcc', 'make', 'automake', 'autoconf']
        sdeps = ['git-core', 'popt', 'glibc', 'glibc-devel', 'popt-devel',
                 'libcap1', 'libcap1-devel', 'libcap-ng', 'libcap-ng-devel']
        udeps = ['git', 'popt', 'build-essential',
                 'libpopt-dev', 'libpopt0', 'libcap-dev', 'libcap-ng-dev']
        rdeps = ['git', 'popt', 'popt-static', 'glibc', 'glibc-devel',
                 'glibc-static', 'libcap-ng', 'libcap-ng-devel', 'libcap1', 'libcap1-devel']
        cdeps = ['git', 'popt', 'popt-static', 'glibc', 'glibc-devel',
                 'glibc-static', 'libcap-ng', 'libcap-ng-devel', 'libcap', 'libcap-devel']
        if 'ubuntu' in detected_distro.name:
            deps = deps + udeps
        elif 'redhat' in detected_distro.name:
            deps = deps + rdeps
        elif 'sles' in detected_distro.name:
            deps = deps + sdeps
        elif 'centos' in detected_distro.name:
            deps = deps + cdeps
        for package in deps:
            if not smg.check_installed(package) and not smg.install(package):
                self.error(
                    '%s is needed for the test to be run !!' % (package))

        url = self.params.get(
            'url', default='https://www.kernel.org/pub/linux/kernel')
        if 'git' not in url:
            version = self.params.get('version', default='4.8.6')
            tarball_base = 'linux-%s.tar.gz' % (version)
            tarball_url = '%s/v%s.x/%s' % (url, version[:1], tarball_base)
            self.log.info('Downloading linux kernel tarball')
            self.tarball = self.fetch_asset(tarball_url)
            archive.extract(self.tarball, self.srcdir)
            linux_src = 'linux-%s' % (version)
            self.buldir = os.path.join(self.srcdir, linux_src)
        else:
            self.log.info('Cloning linux kernel source')
            git.get_repo(url, destination_dir=self.srcdir)

        self.srcdir = os.path.join(self.buldir, self.testdir)
        result = build.run_make(self.srcdir)
        for line in str(result).splitlines():
            if 'ERROR' in line:
                self.fail("Compilation failed, Please check the build logs !!")

    def test(self):
        """
        Execute the kernel selftest
        """
        result = build.make(self.srcdir, extra_args='run_tests')
        for line in str(result).splitlines():
            if '[FAIL]' in line:
                self.fail("Selftest testcase failed, please check the test logs")


if __name__ == "__main__":
    main()
