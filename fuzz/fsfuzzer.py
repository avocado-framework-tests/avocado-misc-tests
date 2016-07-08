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
#
# Copyright: 2016 IBM
# Author: Praveen K Pandey <praveen@linux.vnet.ibm.com>
#
# Based on code by Martin Bligh <mbligh@google.com>
#   copyright: 2006 Google
#   https://github.com/autotest/autotest-client-tests/tree/master/fsfuzzer

import os
import re

from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils import git
from avocado.utils import distro
from avocado.utils import build
from avocado.utils.software_manager import SoftwareManager


class Fsfuzzer(Test):

    """
    fsfuzzer is a file system fuzzer tool. This test simply runs fsfuzzer
    Fuzzing is slang for fault injection via random inputs. The goal is to
    find bugs in software without reading code or designing detailed test
    cases.
       fsfuzz will inject random errors into the files systems
       mounted. Evidently it has found many errors in many systems.
    """

    def setUp(self):
        '''
        Build fsfuzzer
        Source:
        https://github.com/stevegrubb/fsfuzzer.git
        '''
        detected_distro = distro.detect()

        smm = SoftwareManager()

        if not smm.check_installed("gcc") and not smm.install("gcc"):
            self.error("Gcc is needed for the test to be run")

        git.get_repo('https://github.com/stevegrubb/fsfuzzer.git',
                     destination_dir=self.srcdir)

        os.chdir(self.srcdir)

        if detected_distro.name == "Ubuntu":
            # Patch for ubuntu
            fuzz_fix_patch = 'patch -p1 < %s' % (
                os.path.join(self.datadir, 'fsfuzz_fix.patch'))
            process.run(fuzz_fix_patch, shell=True)

        process.run('./autogen.sh', shell=True)
        process.run('./configure', shell=True)

        build.make(self.srcdir)

        self.args = self.params.get('fstype', default='')

        fs_sup = process.system_output('%s %s' % (
            os.path.join(self.srcdir, 'fsfuzz'), ' --help'))

        matchObj = re.search(r'%s' % self.args, fs_sup, re.M | re.I)
        if not matchObj:
            self.skip('File system ' + self.args +
                      ' is unsupported in ' + detected_distro.name)

    def test(self):

        '''
        Runs the fsfuzz test suite. By default uses all supported fstypes,
        but you can specify only one by `fstype` param.
        '''
        process.system('%s %s' % (os.path.join(
            self.srcdir, 'fsfuzz'), self.args), sudo=True)

if __name__ == "__main__":
    main()
