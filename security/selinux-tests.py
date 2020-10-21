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
# Copyright: 2020 IBM
# Author: Nageswara R Sastry <rnsastry@linux.vnet.ibm.com>

import os
from avocado import Test
from avocado.utils import archive, build, distro, linux
from avocado.utils.software_manager import SoftwareManager


class SELinux(Test):

    """
    selinux-testsuite
    :avocado: tags=security,testsuite
    """

    def setUp(self):
        '''
        Install the basic packages to support selinux
        '''
        # Check for basic utilities
        smm = SoftwareManager()
        detected_distro = distro.detect()
        deps = ['gcc', 'make']
        if detected_distro.name in ['rhel', 'SuSE', 'fedora', 'centos',
                                    'redhat']:
            deps.extend(["perl-Test", "perl-Test-Harness", "perl-Test-Simple",
                         "perl-libs", "selinux-policy-devel",
                         "net-tools", "netlabel_tools", "iptables", "libbpf",
                         "lksctp-tools-devel", "attr", "libbpf-devel",
                         "keyutils-libs-devel", "quota", "xfsprogs-devel",
                         "libuuid-devel", "nftables", "kernel-devel",
                         "kernel-modules", "perl-Test-Harness", "coreutils",
                         "netlabel_tools", "libsepol", "checkpolicy",
                         "libselinux", "policycoreutils", "libsemanage",
                         "nfs-utils", "policycoreutils-newrole",
                         "xfsprogs-devel", "libselinux-devel"])
        else:
            self.cancel("Install the package for selinux supported\
                      by %s" % detected_distro.name)
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        url = "https://github.com/SELinuxProject/selinux-testsuite/archive/master.zip"
        tarball = self.fetch_asset(url, expire='7d')
        archive.extract(tarball, self.workdir)
        self.sourcedir = os.path.join(self.workdir, 'selinux-testsuite-master')
        os.chdir(self.sourcedir)
        if not linux.enable_selinux_enforcing():
            self.fail("Unable to enter in to 'Enforcing' mode")
        if build.make(self.sourcedir, extra_args="-C policy load") > 0:
            self.cancel("Failed to load the policies")

    def test(self):
        '''
        Running tests from selinux-testsuite
        '''
        count = 0
        output = build.run_make(self.sourcedir, extra_args="-C tests test",
                                process_kwargs={"ignore_status": True})
        for line in output.stderr_text.splitlines():
            if 'Failed test at' in line:
                count += 1
                self.log.info(line)
        if count:
            self.fail("%s test(s) failed, please refer to the log" % count)

    def tearDown(self):
        build.make(self.sourcedir, extra_args='-C policy unload')
