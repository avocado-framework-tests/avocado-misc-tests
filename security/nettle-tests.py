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
# Copyright: 2021 IBM
# Author: Nageswara R Sastry <rnsastry@linux.ibm.com>

import os
from avocado import Test
from avocado.utils import archive, build, distro, process
from avocado.utils.software_manager.manager import SoftwareManager


class Nettle(Test):

    """
    nettle-testsuite
    :avocado: tags=security,testsuite,crypto
    """

    def setUp(self):
        '''
        Install the basic packages to support Nettle
        '''

        # Check for basic utilities
        smm = SoftwareManager()
        det_dist = distro.detect()
        deps = ['gcc', 'make', 'm4', 'libtool', 'automake', 'autoconf']
        if det_dist.name in ['rhel', 'SuSE', 'fedora', 'centos']:
            deps.extend(["gmp-devel", "gettext-devel"])
            if det_dist.name == "rhel" and int(det_dist.version) >= 9:
                # RHEL9 package name is libkcapi-fipscheck, texinfo-tex
                deps.extend(["texinfo-tex"])
            elif det_dist.name == "SuSE":
                # SLES package name is texinfo
                deps.extend(["fipscheck", "texinfo"])
            else:
                # RHEL8/7 package name is fipscheck, texinfo-tex
                deps.extend(["fipscheck", "texinfo-tex"])
        else:
            self.cancel("Install the package for Nettle supported\
                      by %s" % det_dist.name)
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        run_type = self.params.get('type', default='upstream')
        if run_type == "upstream":
            def_url = ("https://github.com/gnutls/nettle/archive/refs/"
                       "heads/master.zip")
            url = self.params.get('url', default=def_url)
            tarball = self.fetch_asset(url, expire='7d')
            archive.extract(tarball, self.workdir)
            self.srcdir = os.path.join(self.workdir, 'nettle-master')
            os.chdir(self.srcdir)
            output = process.run('autoreconf -ifv', ignore_status=True)
            if output.exit_status:
                self.fail("nettle-tests.py: 'autoreconf' failed.")
            output = process.run('./configure', ignore_status=True)
            if output.exit_status:
                self.fail("nettle-tests.py: 'configure' failed.")
            if build.make(self.srcdir):
                self.fail("Building Nettle failed")
        elif run_type == "distro":
            self.srcdir = os.path.join(self.workdir, "nettle-distro")
            if not os.path.exists(self.srcdir):
                os.makedirs(self.srcdir)
            pkg_name = 'nettle'
            if det_dist.name == "SuSE":
                pkg_name = 'libnettle'
            self.srcdir = smm.get_source(pkg_name, self.srcdir)
            if not self.srcdir:
                self.fail("nettle source install failed.")

    def test(self):
        '''
        Running tests from nettle-testsuite
        '''
        count = 0
        output = build.run_make(self.srcdir, extra_args="check",
                                process_kwargs={"ignore_status": True})
        if output.exit_status:
            self.fail("nettle-tests.py: 'make check' failed.")
        for line in output.stdout_text.splitlines():
            if 'FAIL:' in line:
                count += 1
                self.log.info(line)
        if count:
            self.fail("%s test(s) failed, refer to the log file" % count)
