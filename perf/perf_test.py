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
# Copyright: 2016 IBM
# Author:Praveen K Pandey <praveen@linux.vnet.ibm.com>
#       :Sachin Sant <sachinp@linux.ibm.com>

import platform
import os
from avocado import Test
from avocado.utils import distro, process, archive, build, git
from avocado.utils.software_manager.manager import SoftwareManager


class Perftest(Test):

    """
    perf test testsuite
    :avocado: tags=perf,testsuite
    """

    def buildPerf(self):
        """Build perf binary using upstream source code."""

        self.usegit = self.params.get('usegit', default='0')
        if self.usegit == 1:
            self.location = self.params.get('location', default='https://git'
                                            '.kernel.org/pub/scm/linux/kernel/'
                                            'git/acme/linux.git')
            self.branch = self.params.get('branch', default='main')
            git.get_repo(self.location, branch=self.branch,
                         destination_dir=self.workdir)
            self.sourcedir = self.workdir
        else:
            self.location = self.params.get('location', default='https://githu'
                                            'b.com/torvalds/linux/archive/mast'
                                            'er.zip')
            self.tarball = self.fetch_asset("perfcode.zip",
                                            locations=[self.location],
                                            expire='1d')
            archive.extract(self.tarball, self.workdir)
            self.sourcedir = os.path.join(self.workdir, 'linux-master')
        self.sourcedir = self.sourcedir + f"/tools/perf/"
        os.chdir(self.sourcedir)
        if build.make(self.sourcedir, extra_args='DESTDIR=/usr'):
            self.fail("Failed to build perf from source")
        if build.make(self.sourcedir, extra_args='DESTDIR=/usr install'):
            self.fail("make install from source failed")

    def setUp(self):
        '''
        Install the basic packages to support perf
        '''

        # Check for basic utilities
        smm = SoftwareManager()
        run_type = self.params.get('type', default='distro')
        detected_distro = distro.detect()
        deps = ['gcc', 'make']
        if run_type == 'distro':
            if 'Ubuntu' in detected_distro.name:
                deps.extend(['linux-tools-common', 'linux-tools-%s' %
                             platform.uname()[2]])
            elif 'debian' in detected_distro.name:
                deps.extend(['linux-tools-%s' % platform.uname()[2][3]])
            elif detected_distro.name in ['rhel', 'SuSE', 'fedora', 'centos']:
                deps.extend(['perf', 'gcc-c++', 'bpftool'])
                if 'SuSE' in detected_distro.name:
                    deps.extend(['kernel-default-debuginfo'])
                elif 'rhel' in detected_distro.name:
                    deps.extend(['clang', 'llvm', 'libbpf', 'python3-perf'])
                elif 'fedora' in detected_distro.name:
                    deps.extend(['clang', 'kernel-debuginfo'])
                else:
                    deps.extend(['clang', 'kernel-debuginfo',
                                 'perf-debuginfo'])
            else:
                self.cancel("Install the package for perf supported\
                          by %s" % detected_distro.name)
        if run_type == 'upstream':
            if detected_distro.name in ['rhel', 'fedora']:
                deps.extend(['systemtap-sdt-devel', 'slang-devel',
                             'perl-ExtUtils-Embed', 'libcap-devel',
                             'numactl-devel', 'libbabeltrace-devel',
                             'libpfm-devel', 'java-1.8.0-openjdk-devel',
                             'libtraceevent-devel'])
                if int(detected_distro.version) >= 9:
                    deps.extend(['libunwind-devel'])
            # TODO I could only locate systemtap-sdt-devel, libunwind-devel,
            # slang-devel, and libcap-devel packages. Missing list includes
            # elfutils-devel, libbabeltrace-devel, java-1.8.0-openjdk-devel
            # and libpfm4-devel. For now cancel the test due to missing
            # dependent packages
            if 'SuSE' in detected_distro.name:
                self.cancel("Install the required dependent packages")
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        if run_type == 'upstream':
            self.buildPerf()

    def test_perf_test(self):
        '''
        perf test: Does sanity tests and
        execute the tests by calling each module
        '''
        count = 0
        for string in process.run("perf test", ignore_status=True).\
                stderr.decode("utf-8", "ignore").splitlines():
            if 'FAILED' in string:
                count += 1
                self.log.info(string)
        if count > 0:
            self.fail("%s Test failed" % count)
