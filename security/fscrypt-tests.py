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
# Author: Nageswara R Sastry <rnsastry@linux.ibm.com>

import os
from avocado import Test
from avocado.utils import archive, build, distro, linux_modules
from avocado.utils.software_manager import SoftwareManager


class fscrypt(Test):

    """
    fscrypt-testsuite
    :avocado: tags=security,testsuite
    """

    def setUp(self):
        '''
        Install the basic packages to support fscrypt
        '''
        cfg_param = "CONFIG_FS_ENCRYPTION"
        ret = linux_modules.check_kernel_config(cfg_param)
        if ret == linux_modules.ModuleConfig.NOT_SET:
            self.cancel("%s not set." % cfg_param)
        else:
            self.log.info("%s set." % cfg_param)
        # Check for basic utilities
        smm = SoftwareManager()
        detected_distro = distro.detect()
        deps = ['gcc', 'make']
        if detected_distro.name in ['rhel', 'SuSE', 'fedora', 'centos']:
            deps.extend(["autoconf", "automake", "golang", "expect",
                         "keyutils", "e2fsprogs", "pam-devel"])
        else:
            self.cancel("Unsupported distro %s for fscrypt package"
                        % detected_distro.name)
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        url = "https://github.com/google/fscrypt/archive/refs/heads/master.zip"
        tarball = self.fetch_asset(url, expire='7d')
        archive.extract(tarball, self.workdir)
        self.sourcedir = os.path.join(self.workdir, 'fscrypt-master')
        os.chdir(self.sourcedir)

    def test(self):
        '''
        Running tests from fscrypt
        '''
        count = 0
        output = build.run_make(self.sourcedir, extra_args="test",
                                process_kwargs={"ignore_status": True})
        if output.exit_status:
            self.fail("fscrypt-tests.py: 'make test' failed.")
        for line in output.stdout_text.splitlines():
            if 'not ok' in line:
                count += 1
                self.log.info(line)
        if count:
            self.fail("%s test(s) failed, please refer to the log" % count)
