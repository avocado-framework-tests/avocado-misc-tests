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
# Copyright: 2022 IBM
# Author: Nageswara R Sastry <rnsastry@linux.vnet.ibm.com>

import os
from avocado import Test
from avocado.utils import build, distro, git, process
from avocado.utils.software_manager.manager import SoftwareManager


class IMAEVMUtils(Test):
    """
    ima-evm-utils testsuite
    :avocado: tags=security,testsuite
    """
    def setUp(self):
        '''
        Install the basic packages to support ima-evm-utils
        '''
        # Check for basic utilities
        smm = SoftwareManager()
        deps = ['gcc', 'make', 'autoconf', 'automake', 'asciidoc', 'libtool']
        detected_distro = distro.detect()
        if detected_distro.name in ['rhel', 'fedora', 'centos', 'redhat']:
            deps.extend(["keyutils-libs-devel", "libxslt", "openssl-devel",
                         "tpm2-tss-devel"])
        elif 'SuSE' in detected_distro.name:
            deps.extend(['attr', 'docbook-xsl-stylesheets', 'keyutils-devel',
                         'libattr-devel', 'libxslt-tools', 'openssl-devel',
                         'tpm2-0-tss-devel'])
        else:
            self.cancel("%s not supported for this test" % detected_distro.name)
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        run_type = self.params.get('type', default='upstream')
        if run_type == "upstream":
            def_url = "https://git.code.sf.net/p/linux-ima/ima-evm-utils"
            url = self.params.get('url', default=def_url)
            git.get_repo(url, destination_dir=self.workdir)
            os.chdir(self.workdir)
            output = process.run('./autogen.sh', ignore_status=True)
            if output.exit_status:
                self.fail("ima-evm-utils 'autogen.sh' failed.")
            output = process.run('./configure', ignore_status=True)
            if output.exit_status:
                self.fail("ima-evm-utils 'configure' failed.")
            self.srcdir = self.workdir
        elif run_type == "distro":
            self.srcdir = os.path.join(self.workdir, "ima-evm-utils-distro")
            if not os.path.exists(self.srcdir):
                os.makedirs(self.srcdir)
            self.srcdir = smm.get_source('ima-evm-utils', self.srcdir)
            if not self.srcdir:
                self.fail("ima-evm-utils source install failed.")
        os.chdir(self.srcdir)

    def test(self):
        '''
        Running tests from ima-evm-utils
        '''
        count = 0
        output = build.run_make(self.srcdir, extra_args="check",
                                process_kwargs={"ignore_status": True})
        if output.exit_status:
            self.fail("ima-evm-utils 'make check' failed.")
        for line in output.stdout_text.splitlines():
            if 'FAIL:' in line and 'XFAIL:' not in line and \
               '# FAIL:' not in line:
                count += 1
                self.log.info(line)
        if count:
            self.fail("%s test(s) failed, please refer to the log" % count)
