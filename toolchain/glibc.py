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
from avocado.core import data_dir


class Glibc(Test):
    '''
    The Test fetches the latest glibc repo and runs the tests in it
    '''

    def setUp(self):
        sm = SoftwareManager()
        deps = ['gcc', 'make', 'gawk']
        self.build_dir = self.params.get('build_dir',
                                         default=data_dir.get_tmp_dir())
        for package in deps:
            if not sm.check_installed(package) and not sm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        run_type = self.params.get('type', default='upstream')
        if run_type == "upstream":
            url = 'https://github.com/bminor/glibc/archive/master.zip'
            tarball = self.fetch_asset("glibc.zip", locations=[url], expire='7d')
            archive.extract(tarball, self.workdir)
            glibc_dir = os.path.join(self.workdir, "glibc-master")
        elif run_type == "distro":
            glibc_dir = os.path.join(self.workdir, "glibc-distro")
            if not os.path.exists(glibc_dir):
                os.makedirs(glibc_dir)
            glibc_dir = sm.get_source("glibc", glibc_dir)
        os.chdir(self.build_dir)
        process.run('%s/configure --prefix=%s' % (glibc_dir, self.build_dir),
                    ignore_status=True, sudo=True)
        build.make(self.build_dir)

    def test(self):
        ret = build.run_make(self.build_dir, extra_args='check',
                             process_kwargs={"ignore_bg_processes": True,
                                             "ignore_status": True})
        logfile = os.path.join(self.logdir, "debug.log")
        if ret.exit_status != 0:
            with open(logfile, 'r') as f:
                file_buff = f.read().splitlines()
                for index, line in enumerate(file_buff):
                    if 'Summary' in line:
                        failures = file_buff[index + 1].split()[3]
                        if int(failures) != 0:
                            self.fail("No of Failures occured %s"
                                      "\nCheck logs for more info" % failures)
        else:
            self.log.info("Tests Have been Passed\n"
                          "Please Check Logfile %s run info" % logfile)


if __name__ == "__main__":
    main()
