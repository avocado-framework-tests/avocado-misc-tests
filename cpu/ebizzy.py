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
# Author: Harish <harisrir@linux.vnet.ibm.com>
#
# Based on code by Sudhir Kumar <skumar@linux.vnet.ibm.com>
#   copyright: 2009 IBM
#   https://github.com/autotest/autotest-client-tests/tree/master/ebizzy

import os
import json
import re

from avocado import Test
from avocado import main
from avocado.utils import archive
from avocado.utils import process
from avocado.utils import build
from avocado.utils.software_manager import SoftwareManager


class Ebizzy(Test):

    '''
    ebizzy is designed to generate a workload resembling common web application
    server workloads. It is highly threaded, has a large in-memory working set,
    and allocates and deallocates memory frequently.

    :avocado: tags=cpu
    '''

    def setUp(self):
        '''
        Build ebizzy
        Source:
        http://liquidtelecom.dl.sourceforge.net/project/ebizzy/ebizzy/0.3
        /ebizzy-0.3.tar.gz
        '''
        sm = SoftwareManager()
        for package in ['gcc', 'make', 'patch']:
            if not sm.check_installed(package) and not sm.install(package):
                self.cancel("%s is needed for the test to be run" % package)
        tarball = self.fetch_asset('http://liquidtelecom.dl.sourceforge.net'
                                   '/project/ebizzy/ebizzy/0.3'
                                   '/ebizzy-0.3.tar.gz')
        archive.extract(tarball, self.workdir)
        version = os.path.basename(tarball.split('.tar.')[0])
        self.sourcedir = os.path.join(self.workdir, version)

        patch = self.params.get(
            'patch', default='Fix-build-issues-with-ebizzy.patch')
        os.chdir(self.sourcedir)
        p1 = 'patch -p0 < %s' % (self.get_data(patch))
        process.run(p1, shell=True)
        process.run('[ -x configure ] && ./configure', shell=True)
        build.make(self.sourcedir)

    # Note: default we use always mmap()
    def test(self):

        args = self.params.get('args', default='')
        num_chunks = self.params.get('num_chunks', default=1000)
        chunk_size = self.params.get('chunk_size', default=512000)
        seconds = self.params.get('seconds', default=100)
        num_threads = self.params.get('num_threads', default=100)
        args2 = '-m -n %s -P -R -s %s -S %s -t %s' % (num_chunks, chunk_size,
                                                      seconds, num_threads)
        args = args + ' ' + args2

        results = process.system_output('%s/ebizzy %s'
                                        % (self.sourcedir, args)).decode("utf-8")
        pattern = re.compile(r"(.*?) records/s")
        records = pattern.findall(results)[0]
        pattern = re.compile(r"real (.*?) s")
        real = pattern.findall(results)[0]
        pattern = re.compile(r"user (.*?) s")
        usr_time = pattern.findall(results)[0]
        pattern = re.compile(r"sys (.*?) s")
        sys_time = pattern.findall(results)[0]
        self.whiteboard = json.dumps({'records': records,
                                      'real_time': real,
                                      'user': usr_time,
                                      'sys': sys_time})


if __name__ == "__main__":
    main()
