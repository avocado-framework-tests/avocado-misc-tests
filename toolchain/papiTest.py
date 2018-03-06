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
# Copyright: 2018 IBM.
# Author: Umesh S <umess1@linux.vnet.ibm.com>


import os
from avocado.utils import process
from avocado import Test
from avocado import main
from avocado.utils import git, build
from avocado.utils.software_manager import SoftwareManager


class papitest(Test):

    '''
    This testcase make use of testsuite provided by the
    source package, source files are downloaded and compiled
    '''

    def setUp(self):

        softm = SoftwareManager()

        for package in ['gcc', 'make']:
            if not softm.check_installed(package) and not softm.install(package):
                self.cancel("%s is needed for the test to be run" % package)
        test_type = self.params.get('type', default='upstream')

        if test_type == 'upstream':
            git.get_repo('https://github.com/arm-hpc/papi.git',
                         destination_dir=self.teststmpdir)
            self.path = os.path.join(self.teststmpdir, 'src')
        elif test_type == 'distro':
            sourcedir = os.path.join(self.teststmpdir, 'papi-distro')
            if not os.path.exists(sourcedir):
                os.makedirs(sourcedir)
            self.path = softm.get_source("papi", sourcedir)
            self.path = os.path.join(self.path, 'src')

        os.chdir(self.path)
        process.run('./configure', shell=True)
        build.make(self.path)

    def test(self):

        #Runs the tests

        result = process.run('./run_tests.sh', shell=True)

        #Display the failed tests

        errors = 0
        warns = 0
        for line in result.stdout.splitlines():
            if 'FAILED' in line:
                self.log.info(line)
                errors += 1
            elif 'WARNING' in line:
                self.log.info(line)
                warns += 1

        if errors == 0 and warns > 0:
            self.warn('number of warnings is %s', warns)

        elif errors > 0:
            self.log.warn('number of warnings is %s', warns)
            self.fail("number of errors is %s" % errors)


if __name__ == "__main__":
    main()
