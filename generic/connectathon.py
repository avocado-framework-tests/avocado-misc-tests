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
# Copyright: 2016 IBM
# Author: Praveen K Pandey <praveen@linux.vnet.ibm.com>
#
# Based on code by Poornima.Nayak (Poornima.Nayak@in.ibm.com)
#   copyright: 2011 IBM
#   https://github.com/autotest/autotest-client-tests/tree/master/connectathon

import os
import tempfile

from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils import build
from avocado.utils import git
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import distro


class Connectathon(Test):

    """
    The Connectathon tests run on top of an NFS mount
    and therefore test the behavior of a real (kernel) NFS
    client against a server
    """

    def setUp(self):
        '''
        Build Connectathon
        Source:
        git://git.linux-nfs.org/projects/steved/cthon04.git
        '''
        self.nfail = 0
        # Check for root permission
        if os.geteuid() != 0:
            exit("You need to have root privileges to run this script."
                 "\nPlease try again, using 'sudo'. Exiting.")
        # Check for basic utilities
        smm = SoftwareManager()
        detected_distro = distro.detect()
        packages = ['gcc', 'make']

        if detected_distro.name == "SuSE":
            packages.extend(['git-core'])

        else:
            packages.extend(['git'])

        for package in packages:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel("Fail to install %s required for this test." %
                            package)

        self.tmpdir = tempfile.mkdtemp(prefix='avocado_' + __name__)
        git.get_repo('git://git.linux-nfs.org/projects/steved/cthon04.git',
                     destination_dir=self.workdir)
        os.chdir(self.workdir)

        build.make(self.workdir)

    def test(self):

        args = self.params.get('arg', default='')
        cthon_iterations = self.params.get('cthon_iterations', default=1)
        testdir = self.params.get('testdir', default=None)
        os.chdir(self.workdir)

        if testdir is None:
            testdir = self.tmpdir
        try:
            if not args:
                # run basic test
                args = "-b -t"

            process.system('./runtests -N %s %s %s' %
                           (cthon_iterations, args, testdir), shell=True)

        except Exception:
            self.nfail += 1
            self.log.info("Test failed: ")
        if self.nfail != 0:
            raise self.fail('Connectathon test suite failed.')


if __name__ == "__main__":
    main()
