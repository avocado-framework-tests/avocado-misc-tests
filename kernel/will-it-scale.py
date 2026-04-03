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
# Copyright: 2024 IBM
# Author: Sachin Sant <sachinp@linux.ibm.com>
#


import os
import shutil
import pathlib
from sys import version_info

from avocado import Test
from avocado import skipIf
from avocado.utils import process, build, memory, archive, distro
from avocado.utils.software_manager.manager import SoftwareManager

SINGLE_NODE = len(memory.numa_nodes_with_memory()) < 2
VERSION_CHK = version_info[0] < 4 and version_info[1] < 7


class WillItScaleTest(Test):
    """
    Will It Scale takes a testcase and runs n parallel copies to see if the
    testcase will scale.
    Source - https://github.com/antonblanchard/will-it-scale

    :avocado: tags=kernel,ppc64le
    """
    fail_cmd = list()

    def run_cmd(self, cmd):
        if process.system(cmd, ignore_status=True, sudo=True, shell=True):
            self.fail_cmd.append(cmd)
        return

    def get_libhw(self):
        """
        SLES does not contain hwloc-devel package, get the source and
        compile it to be linked to will-it-scale binaries.

        Source - https://github.com/open-mpi/hwloc/
        """
        hwloc_url = ('https://github.com/open-mpi/hwloc/archive/refs/'
                     'heads/master.zip')
        tarball = self.fetch_asset('hwloc.zip', locations=hwloc_url,
                                   expire='7d')
        archive.extract(tarball, self.workdir)
        self.sourcedir = os.path.join(self.workdir, 'hwloc-master')
        os.chdir(self.sourcedir)
        self.run_cmd('./autogen.sh')
        self.run_cmd('./configure --prefix=/usr')
        if self.fail_cmd:
            self.fail('Configure failed, please check debug logs')
        if build.make(self.sourcedir):
            self.fail('make failed, please check debug logs')
        if build.make(self.sourcedir, extra_args='install'):
            self.fail('make install failed, please check debug logs')
        # Create a symlink with name libhwloc.so.0
        if not pathlib.Path("/usr/lib/libhwloc.so.0").is_symlink():
            self.run_cmd('ln -s /usr/lib/libhwloc.so.0.0.0 '
                         '/usr/lib/libhwloc.so.0')
            if self.fail_cmd:
                self.warn('libhwloc softlink failed, program may not run')

    @skipIf(SINGLE_NODE, "Test requires at least two numa nodes")
    @skipIf(VERSION_CHK, "Test requires Python 3.7+")
    def setUp(self):
        """
        To execute test using git copy
          make
          ./runalltests

        To generate graphical results
          ./postprocess.py
        """
        self.distro_rel = distro.detect()
        smm = SoftwareManager()
        deps = ['gcc', 'make']
        if self.distro_rel.name.lower() in ['fedora', 'redhat']:
            deps.extend(['hwloc-devel'])
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is required for this test' % package)
        # Compile and install libhwloc library
        if 'suse' in self.distro_rel.name.lower():
            self.get_libhw()

        self.postprocess = self.params.get('postprocess', default=True)
        self.testcase = self.params.get('name', default='brk1')
        url = self.params.get(
                'willit_url', default='https://github.com/antonblanchard/'
                'will-it-scale/archive/refs/heads/master.zip')
        tarball = self.fetch_asset('willit.zip', locations=[url],
                                   expire='7d')
        archive.extract(tarball, self.workdir)
        self.sourcedir = os.path.join(self.workdir, 'will-it-scale-master')
        os.chdir(self.sourcedir)
        # Modify the makefile to point to installed libhwloc
        if 'suse' in self.distro_rel.name.lower():
            makefile_patch = 'patch -p1 < %s' % self.get_data('makefile.patch')
            process.run(makefile_patch, shell=True)
        if build.make(self.sourcedir):
            self.fail('make failed, please check debug logs')

    def test_scaleitall(self):
        """
        Invoke and execute test(s)
        """
        os.chdir(self.sourcedir)
        self.log.info("Starting test...")

        # Identify the test to be executed
        if self.testcase in 'All':
            cmd = './runalltests'
        else:
            cmd = './runtest.py %s > %s.csv' % (self.testcase, self.testcase)

        # Execute the test(s)
        if process.system(cmd, shell=True, sudo=True, ignore_status=True) != 0:
            self.fail('Please check the logs for failure')
        if self.testcase not in 'All':
            shutil.copy(f"{self.testcase}.csv", self.logdir)

        # Generate graphical results if postprocessing is enabled
        if self.postprocess:
            cmd = './postprocess.py'
            if process.system(cmd, shell=True, ignore_status=True) != 0:
                self.log.warn('Post processing failed, graph may not be generated')
        if self.testcase not in 'All':
            shutil.copy(f"{self.testcase}.html", self.logdir)
