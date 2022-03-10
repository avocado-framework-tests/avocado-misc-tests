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

        run_type = self.params.get("type", default="distro")
        if run_type == "upstream":
            source = self.params.get('url', default="https://github.com/"
                                     "strace/strace.git")
            git.get_repo(source, destination_dir=os.path.join(
                self.workdir, 'strace'))
            self.src_st = os.path.join(self.workdir, "strace")
            os.chdir(self.src_st)
            process.run('./bootstrap', ignore_status=True, sudo=True)
        elif run_type == "distro":
            self.src_st = os.path.join(self.workdir, "strace-distro")
            if not os.path.exists(self.src_st):
                self.src_st = smm.get_source("strace", self.src_st)
            os.chdir(self.src_st)

        process.run('./configure', ignore_status=True, sudo=True)
        build.make(self.src_st)

    def test(self):
        """
        Execute strace self tests
        """
        results = build.run_make(self.src_st, extra_args='-k check',
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
