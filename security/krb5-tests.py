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
from avocado.utils import archive, build, process
from avocado.utils.software_manager.manager import SoftwareManager


class Krb5(Test):
    """
    krb5-testsuite
    :avocado: tags=security,testsuite
    """
    def setUp(self):
        '''
        Install the basic packages to support krb5
        '''
        # Check for basic utilities
        smm = SoftwareManager()
        deps = ['gcc', 'make', 'autoconf']
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        run_type = self.params.get('type', default='upstream')
        if run_type == "upstream":
            default_url = "https://github.com/krb5/krb5/archive/master.zip"
            url = self.params.get('url', default=default_url)
            tarball = self.fetch_asset(url, expire='7d')
            archive.extract(tarball, self.workdir)
            self.srcdir = os.path.join(self.workdir, 'krb5-master/src')
            os.chdir(self.srcdir)
            output = process.run('autoreconf', ignore_status=True)
            if output.exit_status:
                self.fail("krb5-tests.py: 'autoreconf' failed.")
            output = process.run('./configure', ignore_status=True)
            if output.exit_status:
                self.fail("krb5-tests.py: 'configure' failed.")
            if build.make(self.srcdir):
                self.fail("krb5-tests.py: 'make' failed.")
        elif run_type == "distro":
            self.srcdir = os.path.join(self.workdir, "krb5-distro")
            if not os.path.exists(self.srcdir):
                os.makedirs(self.srcdir)
            self.srcdir = smm.get_source("krb5", self.srcdir)
            if not self.srcdir:
                self.fail("krb5-tests.py: krb5 source install failed.")

    def test(self):
        '''
        Running tests from krb5
        '''
        count = 0
        output = build.run_make(self.srcdir, extra_args="check",
                                process_kwargs={"ignore_status": True})
        if output.exit_status:
            self.fail("krb5-tests.py: 'make check' failed.")
        for line in output.stdout_text.splitlines():
            if '*** Failure:' in line:
                count += 1
                self.log.info(line)
        if count:
            self.fail("%s test(s) failed, please refer to the log" % count)
