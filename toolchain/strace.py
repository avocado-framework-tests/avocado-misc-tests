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
# Copyright: 2021 IBM
# Author: Sachin Sant <sachinp@linux.vnet.ibm.com>

import os
import re

from avocado import Test
from avocado.utils import build, process, git
from avocado.utils.software_manager import SoftwareManager


class Strace(Test):

    """
    Strace is a diagnostic and debugging command line utility for Linux
    :avocado: tags=os,testsuite
    """

    def setUp(self):
        """
        Build strace

        Source:
        http://github.com/strace/strace.git
        """
        smm = SoftwareManager()
        for package in ['make', 'gcc', 'autoconf', 'automake']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel(' %s is needed for the test to be run' % package)
        git.get_repo('https://github.com/strace/strace.git',
                     destination_dir=self.workdir)
        os.chdir(self.workdir)
        process.run('./bootstrap', ignore_status=True, sudo=True)
        process.run('./configure', ignore_status=True, sudo=True)
        build.make(self.workdir)

    def test(self):
        """
        Execute strace self tests
        """
        results = build.run_make(self.workdir, extra_args='-k check',
                                 process_kwargs={'ignore_status': True}).stdout

        fail_list = ['FAIL', 'XFAIL', 'ERROR']
        failures = []
        for failure in fail_list:
            num_fails = re.compile(r"# %s:(.*)" %
                                   failure).findall(results.decode('utf-8')
                                                    )[0].strip()
            if int(num_fails):
                failures.append({failure: num_fails})

        if failures:
            self.fail('Test failed with following:%s' % failures)
