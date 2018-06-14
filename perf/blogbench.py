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


class Blogbench(Test):

    ''' Blogbench will start the required threads and the test will run
        according to the args given.A final "score" will then be given as
        an indication of read and write performance '''

    def setUp(self):
        sm = SoftwareManager()
        # Check for basic utilities
        for package in ['gcc', 'make', 'patch']:
            if not sm.check_installed(package) and not sm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        url = 'https://download.pureftpd.org/blogbench/blogbench-1.1.tar.bz2'
        blogbench_url = self.params.get('blogbench_url',
                                        default=url)
        blogbench_tarball = self.fetch_asset(blogbench_url, expire='7d')
        archive.extract(blogbench_tarball, self.workdir)
        blogbench_version = os.path.basename(blogbench_tarball
                                             .split('.tar.')[0])
        self.blogbench_dir = os.path.join(self.workdir, blogbench_version)
        os.chdir(self.blogbench_dir)
        patch = self.params.get('patch', default='config_guess.patch')
        process.run('patch -p1 config.guess %s' %
                    self.get_data(patch), shell=True)
        process.system('./configure')
        build.make(self.blogbench_dir, extra_args='install-strip')

    def test(self):
        test_dir = self.params.get('test_dir', default=data_dir.get_tmp_dir())
        # 4 Different types of threads can be specified as an args
        # These args are given higher value to stress the system more
        # Here, test is run with default args
        args = self.params.get('args', default='')
        args = ' -d %s %s ' % (test_dir, args)
        process.system("blogbench " + args, shell=True, sudo=True)
        report_path = os.path.join(self.logdir, 'stdout')
        with open(report_path, 'r') as f:
            file_buff = f.read().splitlines()
            for line in file_buff:
                if 'Final score for writes:' in line:
                    write_score = line.split()[4]
                if 'Final score for reads :' in line:
                    read_score = line.split()[5]
        self.log.info("The Benchmark Scores for Write and Read are : "
                      "%s  and %s\n " % (write_score, read_score))
        self.log.info("Please Check Logfile %s for more info of benchmark"
                      % report_path)


if __name__ == "__main__":
    main()
