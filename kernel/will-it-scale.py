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
from sys import version_info

from avocado import Test
from avocado import skipIf
from avocado.utils import process, build, memory, archive
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

    @skipIf(SINGLE_NODE, "Test requires atleast two numa nodes")
    @skipIf(VERSION_CHK, "Test requires Python 3.7+")
    def setUp(self):
        """
        To execute test using git copy
          make
          ./runalltests

        To generate graphical results
          ./postprocess.py
        """
        smm = SoftwareManager()
        for package in ['gcc', 'make', 'hwloc-devel']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

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
                self.warn('Post processing failed, graph may not be generated')
        if self.testcase not in 'All':
            shutil.copy(f"{self.testcase}.html", self.logdir)
