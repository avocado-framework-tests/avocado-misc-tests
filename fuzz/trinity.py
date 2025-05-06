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
# Author: Praveen K Pandey <praveen@linux.vnet.ibm.com>
#

import os
import re

from avocado import Test
from avocado.utils import archive, build, process, dmesg
from avocado.utils.software_manager.manager import SoftwareManager


class Trinity(Test):

    """
    This testsuite test  syscall by calling syscall
    with random system call and varying number of args
    """

    def setUp(self):
        '''
        Build Trinity
        Source:
        https://github.com/kernelslacker/trinity
        '''
        """
        Adding  non-root user
        """
        if process.system('getent group trinity', ignore_status=True):
            process.run('groupadd trinity', sudo=True)
        if process.system('getent passwd trinity', ignore_status=True):
            process.run(
                'useradd -g trinity  -m -d /home/trinity  trinity', sudo=True)
        process.run('usermod -a -G trinity  trinity', sudo=True)

        smm = SoftwareManager()

        for package in ("gcc", "make"):
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel(
                    "Fail to install %s required for this test." % package)

        locations = ["https://github.com/kernelslacker/trinity/archive/"
                     "master.zip"]
        tarball = self.fetch_asset("trinity.zip", locations=locations,
                                   expire='7d')
        archive.extract(tarball, self.workdir)
        self.sourcedir = os.path.join(self.workdir, 'trinity-master')

        os.chdir(self.sourcedir)

        process.run('chmod -R  +x ' + self.sourcedir)
        process.run('./configure', shell=True)
        build.make('.')
        process.run('touch trinity.log')
        process.run('cp -r ' + self.sourcedir + ' /home/trinity')
        self.sourcedir = os.path.join('/home/trinity', 'trinity-master')

        process.run('chown -R trinity:trinity ' + self.sourcedir)

    def test(self):
        '''
        Trinity need to run as non root user
        '''
        dmesg.clear_dmesg()
        args = self.params.get('runargs', default=' ')

        if process.system('su - trinity -c " %s  %s  %s"' %
                          (os.path.join(self.sourcedir, 'trinity'), args,
                           '-N 1000000'), shell=True, ignore_status=True):
            self.fail("trinity  command line  return as non zero exit code ")

        dmesg1 = process.system_output('dmesg')

        # verify if system having issue after fuzzer run

        match = re.search(br'unhandled', dmesg1, re.M | re.I)
        if match:
            self.log.info("Testcase failure as segfault")
        match = re.search(br'Call Trace:', dmesg1, re.M | re.I)
        if match:
            self.log.info("some call traces seen please check")
        match = re.search(br'tainting kernel:', dmesg1, re.M | re.I)
        if match:
            self.log.info("tainting kernel seen please check")

    def tearDown(self):
        """
        removing already added non-root user
        """

        process.system('userdel -r  trinity', sudo=True, ignore_status=True)
