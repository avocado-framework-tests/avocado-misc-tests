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
# Author: Disha Goel <disgoel@linux.vnet.ibm.com>

import platform
import os
import subprocess
import tempfile
import threading

from avocado import Test
from avocado.utils import distro, process, archive, build
from avocado.utils.software_manager.manager import SoftwareManager


class ebizzy(Test):

    """
    ebizzy workload
    """

    def setUp(self):
        '''
        Install the basic packages to support perf
        '''

        # Check for basic utilities
        smm = SoftwareManager()
        detected_distro = distro.detect()
        self.distro_name = detected_distro.name

        deps = ['gcc', 'make']
        if 'Ubuntu' in self.distro_name:
            deps.extend(['linux-tools-common', 'linux-tools-%s' %
                         platform.uname()[2]])
        elif 'debian' in detected_distro.name:
            deps.extend(['linux-perf'])
        elif self.distro_name in ['rhel', 'SuSE', 'fedora', 'centos']:
            deps.extend(['perf', 'python3-pexpect'])
        else:
            self.cancel("Install the package for perf supported \
                         by %s" % detected_distro.name)
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

        # Creating a temprory file
        self.temp_file = tempfile.NamedTemporaryFile().name

    def test_workload(self):
        # Get ebizzy workload and build
        url = 'https://sourceforge.net/projects/ebizzy/files/ebizzy/0.3/ebizzy-0.3.tar.gz'
        tarball = self.fetch_asset(url, expire='7d')
        archive.extract(tarball, self.workdir)
        version = os.path.basename(tarball.split('.tar.')[0])
        self.sourcedir = os.path.join(self.workdir, version)
        os.chdir(self.sourcedir)
        process.run("./configure")
        build.make(self.sourcedir, extra_args='LDFLAGS=-static')

        # Create thread objects
        thread1 = threading.Thread(target=self.run_workload)
        thread2 = threading.Thread(target=self.capture_top_output)
        # Start the threads
        thread1.start()
        thread2.start()
        # Wait for both threads to finish
        thread1.join()
        thread2.join()
        # Main thread continues here
        output = subprocess.check_output("grep ebizzy %s" % self.temp_file,
                                         shell=True,
                                         stderr=subprocess.STDOUT)
        if not output:
            self.fail("ebizzy workload not captured in perf top")

    def run_workload(self):
        process.run("./ebizzy -S1 -s1024 -t10", shell=True)

    def capture_top_output(self):
        process.getoutput("perf top -a > %s " % self.temp_file, timeout=10)

    def teardown(self):
        if os.path.isfile(self.temp_file):
            process.system('rm -f %s' % self.temp_file)
