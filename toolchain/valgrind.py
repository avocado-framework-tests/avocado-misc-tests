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
# Copyright: 2017 IBM
# Author: Harish S <harish@linux.vnet.ibm.com>

import os
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils import build
from avocado.utils import archive
from avocado.utils import distro
from avocado.utils.software_manager import SoftwareManager


class Valgrind(Test):
    '''
    Valgrind is an instrumentation framework for building dynamic analysis
    tools. Valgrind tools can automatically detect many memory management
    and threading bugs, and profile your programs in detail

    The Test fetches the recent valgrind tar and runs the tests in it
    '''

    def setUp(self):
        smm = SoftwareManager()
        self.failures = []

        dist = distro.detect()
        deps = ['gcc', 'make']
        if dist.name == 'Ubuntu':
            deps.extend(['g++'])
        # FIXME: "redhat" as the distro name for RHEL is deprecated
        # on Avocado versions >= 50.0.  This is a temporary compatibility
        # enabler for older runners, but should be removed soon
        elif dist.name in ['SuSE', 'rhel', 'fedora', 'centos', 'redhat']:
            deps.extend(['gcc-c++'])
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.skip('%s is needed for the test to be run' % package)
        tarball = self.fetch_asset(
            "http://valgrind.org/downloads/valgrind-3.12.0.tar.bz2")
        archive.extract(tarball, self.srcdir)
        version = os.path.basename(tarball.split('.tar.')[0])
        self.srcdir = os.path.join(self.srcdir, version)

        os.chdir(self.srcdir)
        process.run('./configure', ignore_status=True, sudo=True)

    def get_results(self, cmd):
        """
        run 'make' of given command and write the summary to respective files
        """
        summary = ''
        flag = False
        results = build.run_make(
            self.srcdir, extra_args=cmd, ignore_status=True).stdout
        for line in results.splitlines():
            if line.startswith('==') and line.endswith('=='):
                flag = True
            if flag:
                summary += '%s\n' % line
        with open(os.path.join(self.outputdir, '%s_result' % cmd), 'w') as f_obj:
            f_obj.write(summary)
        if 'failed' in summary:
            self.failures.append(cmd)

    def test(self):
        """
        Run valgrind test with different categories
        """
        build.make(self.srcdir)
        self.get_results('regtest')
        self.get_results('exp-regtest')
        self.get_results('nonexp-regtest')
        if self.failures:
            self.fail('Following tests failed: %s, Check %s for results' % (
                self.failures, self.outputdir))


if __name__ == "__main__":
    main()
