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
from avocado.utils.software_manager.manager import SoftwareManager


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
        deps = ['gcc', 'make', "perl-Test-Harness", "perl-Test-Simple",
                "net-tools", "lksctp-tools-devel", "policycoreutils-newrole",
                "attr", "quota", "iptables", "nfs-utils", "policycoreutils",
                "xfsprogs-devel", "libuuid-devel", "nftables", "kernel-devel",
                "coreutils", "checkpolicy"]
        self.srcdir = None
        if detected_distro.name in ['rhel', 'fedora', 'centos', 'redhat']:
            deps.extend(["perl-Test", "perl-libs", "selinux-policy-devel",
                         "netlabel_tools", "libbpf", "libbpf-devel",
                         "keyutils-libs-devel", "kernel-modules",
                         "netlabel_tools", "libsepol", "libselinux",
                         "libselinux-devel", "libsemanage", "libbpf-devel"])
        elif detected_distro.name in ['SuSE', 'Ubuntu']:
            self.cancel("SELinux tests not supported on %s"
                        % detected_distro.name)
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        run_type = self.params.get('type', default='upstream')
        if run_type == "upstream":
            default_url = ("https://github.com/SELinuxProject/"
                           "selinux-testsuite/archive/master.zip")
            url = self.params.get('url', default=default_url)
            tarball = self.fetch_asset(url, expire='7d')
            archive.extract(tarball, self.workdir)
            self.srcdir = os.path.join(self.workdir, 'selinux-testsuite-master')
        elif run_type == "distro":
            self.srcdir = os.path.join(self.workdir, "selinux-distro")
            if not os.path.exists(self.srcdir):
                os.makedirs(self.srcdir)
            self.srcdir = smm.get_source('selinux', self.srcdir)
            if not self.srcdir:
                self.fail("selinux source install failed.")
        os.chdir(self.srcdir)
        if not linux.enable_selinux_enforcing():
            self.fail("Unable to enter in to 'Enforcing' mode")
        if build.make(self.srcdir, extra_args="-C policy load") > 0:
            self.cancel("Failed to load the policies")

    def test(self):
        '''
        Running tests from selinux-testsuite
        '''
        count = 0
        output = build.run_make(self.srcdir, extra_args="-C tests test",
                                process_kwargs={"ignore_status": True})
        if output.exit_status:
            self.fail("selinux-tests.py: 'make check' failed.")
        for line in output.stderr_text.splitlines():
            if 'Failed test at' in line:
                count += 1
                self.log.info(line)
        if count:
            self.fail("%s test(s) failed, please refer to the log" % count)

    def tearDown(self):
        if self.srcdir:
            build.make(self.srcdir, extra_args='-C policy unload')
