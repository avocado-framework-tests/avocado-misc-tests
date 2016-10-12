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
# Copyright: 2016 IBM
# Author: Santhosh G <santhog4@linux.vnet.ibm.com>

import os
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils import build
from avocado.utils import archive
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import distro
from avocado.core import data_dir


class glibc(Test):
    def setUp(self):
        sm = SoftwareManager()
        detected_distro = distro.detect()
        deps = ['gcc', 'make', 'gawk']
        self.tmpdir = data_dir.get_tmp_dir()
        self.build_dir = self.params.get('build_dir', default=self.tmpdir)
        for package in deps:
            if not sm.check_installed(package) and not sm.install(package):
                self.error(package + ' is needed for the test to be run')
        url = 'https://github.com/bminor/glibc/archive/master.zip'
        tarball = self.fetch_asset("glibc.zip", locations=[url], expire='0d')
        archive.extract(tarball, self.srcdir)
        self.srcdir = os.path.join(self.srcdir, "glibc-master")
        os.chdir(self.build_dir)
        process.run(self.srcdir + '/configure --prefix=%s' % self.build_dir,
                    ignore_status=True, sudo=True)
        build.make(self.build_dir)

    def test(self):
        ret = build.run_make(self.build_dir,
                             extra_args='check',
                             ignore_status=True,
                             allow_output_check='stdout')
        logfile = os.path.join(self.logdir, "stdout")
        if ret.exit_status != 0:
            with open(logfile, 'r') as f:
                file_buff = f.read().splitlines()
                for index, line in enumerate(file_buff):
                    if 'Summary' in line:
                        failures = file_buff[index+1].split()[0]
                        if int(failures) != 0:
                            self.fail("No of Failures occured %s"
                                      "\nCheck logs for more info" % failures)
        else:
            self.log.info("Tests Have been Passed\n"
                          "Please Check Logfile %s run info" % logfile)

if __name__ == "__main__":
    main()
