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
from avocado.utils import build, git
from avocado.utils.software_manager.manager import SoftwareManager


class KeyUtils(Test):
    """
    keyutils-testsuite
    :avocado: tags=security,testsuite
    """
    def setUp(self):
        '''
        Install the basic packages to support keyutils
        '''
        # Check for basic utilities
        smm = SoftwareManager()
        deps = ['gcc', 'make']
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        url = "https://git.kernel.org/pub/scm/linux/kernel/git/dhowells/keyutils.git"
        git.get_repo(url, destination_dir=self.workdir)
        os.environ['AUTOMATED'] = '1'
        self.make_path = os.path.join(self.workdir, 'tests')
        os.chdir(self.make_path)

    def test(self):
        '''
        Running tests from keyutils
        '''
        count = 0
        output = build.run_make(self.make_path,
                                process_kwargs={"ignore_status": True})
        for line in output.stdout_text.splitlines():
            if 'FAILED' in line:
                count += 1
                self.log.info(line)
        if count:
            self.fail("%s test(s) failed, please refer to the log" % count)
