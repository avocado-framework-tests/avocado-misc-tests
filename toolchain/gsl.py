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
# Author: Pavithra <pavrampu@linux.vnet.ibm.com>

import os
from avocado import Test
from avocado import main
from avocado.utils import archive, process, build
from avocado.utils.software_manager import SoftwareManager


class GSL(Test):

    '''
    Script downloads gsl tar ball from ftp://ftp.gnu.org/gnu/gsl/ and runs self test.
    '''

    def setUp(self):
        sm = SoftwareManager()
        for package in ['gcc', 'make']:
            if not sm.check_installed(package) and not sm.install(package):
                self.cancel("Fail to install %s required for this test." %
                            package)
        gsl_version = self.params.get('gsl_version', default='2.2')
        tarball = self.fetch_asset(
            "ftp://ftp.gnu.org/gnu/gsl/gsl-%s.tar.gz" % gsl_version, expire='10d')
        archive.extract(tarball, self.workdir)
        self.sourcedir = os.path.join(
            self.workdir, os.path.basename(tarball.split('.tar')[0]))
        os.chdir(self.sourcedir)
        process.run('./configure', ignore_status=True, sudo=True)
        build.make(self.sourcedir)

    def test(self):
        process.run("make -k check", ignore_status=True, sudo=True)
        logfile = os.path.join(self.logdir, "stdout")
        if process.system_output("grep -Eai 'FAIL:  [1-9]' %s" %
                                 logfile, shell=True, ignore_status=True):
            process.run("grep -Eai 'Making check in|FAIL:  [1-9]' %s" % logfile,
                        ignore_status=True, sudo=True)
            self.fail("test failed, Please check debug log for failed test cases")


if __name__ == "__main__":
    main()
