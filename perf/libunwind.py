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
# Copyright: 2017 IBM
# Author: Pooja <pooja@linux.vnet.ibm.com>

import os
import re

from avocado import Test
from avocado import main
from avocado.utils import archive, build, distro, process
from avocado.utils.software_manager import SoftwareManager


class Libunwind(Test):

    def setUp(self):
        '''
        Build Libunwind library
        Source:
        https://github.com/pathscale/libunwind/archive/vanilla_pathscale.zip
        '''
        dist = distro.detect()
        smm = SoftwareManager()
        deps = ['gcc', 'libtool', 'autoconf', 'automake', 'make']
        if dist.name == 'Ubuntu':
            deps.extend(['dh-autoreconf', 'dh-dist-zilla', 'g++',
                         'texlive-extra-utils'])
        elif dist.name in ['SuSE', 'rhel', 'fedora', 'redhat']:
            deps.extend(['gcc-c++'])
        else:
            self.cancel('Test not supported in %s' % dist.name)

        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel("Failed to install %s, which is needed for"
                            "the test to be run" % package)

        tarball = self.fetch_asset('vanilla_pathscale.zip', locations=[
            'https://github.com/pathscale/libunwind/archive/'
            'vanilla_pathscale.zip'], expire='7d')
        archive.extract(tarball, self.workdir)
        self.sourcedir = os.path.join(self.workdir, 'libunwind-vanilla_pathscale')
        os.chdir(self.sourcedir)
        process.run('./autogen.sh', shell=True)
        '''
        For configure options on different architecture please refer
        https://github.com/pathscale/libunwind
        '''
        configure_option = self.params.get('configure_option',
                                           default='configure_option')
        process.run('./configure %s' % configure_option, shell=True)
        build.make(self.sourcedir)
        build.make(self.sourcedir, extra_args='install')

    def test(self):
        '''
        Execute regression tests for libunwind library
        '''
        results = build.run_make(self.sourcedir, extra_args='check',
                                 process_kwargs={'ignore_status': True}).stdout

        fail_list = ['FAIL', 'XFAIL', 'ERROR']
        failures = []
        for failure in fail_list:
            num_fails = re.compile(r"# %s:(.*)" %
                                   failure).findall(results)[0].strip()
            if int(num_fails):
                failures.append({failure: num_fails})

        if failures:
            self.fail('Test failed with following:%s' % failures)


if __name__ == "__main__":
    main()
