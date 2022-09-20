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
from avocado.utils import archive, build, distro, process
from avocado.utils.software_manager.manager import SoftwareManager


class Audit(Test):

    """
    audit-testsuite
    :avocado: tags=security,testsuite
    """

    def setUp(self):
        '''
        Install the basic packages to support audit
        '''

        # Check for basic utilities
        smm = SoftwareManager()
        detected_distro = distro.detect()
        deps = ["gcc", "make", "glibc", "glibc-devel", "perl",
                "perl-Test-Harness", "perl-File-Which", "perl-Time-HiRes"]
        if detected_distro.name in ['rhel', 'fedora', 'centos', 'redhat']:
            deps.extend(["perl-Test", "nmap-ncat"])
        elif detected_distro.name in ['SuSE']:
            deps.extend(["libtool", "tcpd-devel", "swig", "liburing-devel",
                         "openldap2-devel"])
        else:
            self.cancel("Install the package for audit supported\
                      by %s" % detected_distro.name)
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

        run_type = self.params.get('type', default='upstream')
        if run_type == "upstream":
            default_url = ("https://github.com/linux-audit/audit-userspace/"
                   "archive/master.zip")
            url = self.params.get('url', default=default_url)
            tarball = self.fetch_asset(url, expire='7d')
            archive.extract(tarball, self.workdir)
            self.srcdir = os.path.join(self.workdir, 'audit-userspace-master')
            os.chdir(self.srcdir)
            output = process.run('./autogen.sh', ignore_status=True)
            if output.exit_status:
                self.fail("audit-tests.py: 'autogen.sh' failed.")
            output = process.run('./configure', ignore_status=True)
            if output.exit_status:
                self.fail("audit-tests.py: 'configure' failed.")
            output = build.run_make(self.srcdir,
                                    process_kwargs={"ignore_status": True})
            if output.exit_status:
                self.fail("audit-tests.py: 'make' failed.")
        elif run_type == "distro":
            self.srcdir = os.path.join(self.workdir, "audit-distro")
            if not os.path.exists(self.srcdir):
                os.makedirs(self.srcdir)
            self.srcdir = smm.get_source('audit', self.srcdir)
        os.chdir(self.srcdir)

    def test(self):
        '''
        Running tests from audit-testsuite
        '''
        output = build.run_make(self.srcdir, extra_args="check",
                                process_kwargs={"ignore_status": True})
        if output.exit_status:
            self.fail("audit-tests.py: 'make check' failed.")
        for line in output.stdout_text.splitlines():
            if 'Result: FAIL' in line:
                self.log.info(line)
                self.fail("Some of the test(s) failed, refer to the log file")
