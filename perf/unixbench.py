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
# Author: Santhosh G <santhog4@linux.vnet.ibm.com>
# Copyright: 2016 IBM
#
# Based on code mostly written by:
# Author : John Admanski <jadmanski@google.com>
# copyright : 2008 Google

import os
import re
from avocado import Test
from avocado.utils import process
from avocado.utils import build
from avocado.utils import archive
from avocado.utils.software_manager import SoftwareManager
from avocado.core import data_dir


class Unixbench(Test):

    def setUp(self):
        smm = SoftwareManager()
        # Check for basic utilities
        self.tmpdir = data_dir.get_tmp_dir()
        self.report_data = self.err = None
        self.build_dir = self.params.get('build_dir', default=self.tmpdir)
        for package in ['gcc', 'make']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        url = 'https://github.com/kdlucas/byte-unixbench/archive/master.zip'
        tarball = self.fetch_asset("byte-unixbench.zip", locations=[url],
                                   expire='7d')
        archive.extract(tarball, self.workdir)
        self.sourcedir = os.path.join(self.workdir,
                                      "byte-unixbench-master/UnixBench")
        os.chdir(self.sourcedir)
        build.make(self.sourcedir)

    def test(self):
        self.tmpdir = data_dir.get_tmp_dir()
        # Read USAGE in Unixbench directory in src to give the args
        args = self.params.get('args', default='-v -c 1')
        process.system('./Run %s' % args, shell=True,
                       sudo=True, ignore_status=True)
        report_path = os.path.join(self.logdir, 'stdout')
        self.report_data = open(report_path).readlines()

    def check_for_failure(self, words):
        length = len(words)
        if length >= 3 and words[-3:length] == ['no', 'measured', 'results']:
            # found a problem so record it in err string
            key = '_'.join(words[1:-3])
            if self.err is None:
                self.err = key
            else:
                self.err = self.err + " " + key
            return True
        else:
            return False

    def tearDown(self):
        self.err = None
        keyval = {}
        parse_flag = False
        result_flag = False
        for line in self.report_data:
            if "BYTE UNIX Benchmarks" in line:
                result_flag = True
            if "Dhrystone" in line and result_flag:
                parse_flag = True
            if parse_flag:
                if len(line.split()) == 0:
                    break
                words = line.split()
                # look for problems first
                if self.check_for_failure(words):
                    continue

                # we should make sure that there are at least
                # 6 guys before we start accessing the array
                if len(words) >= 6:
                    key = '_'.join(words[0:-6])
                    key = re.sub(r'\W', '', key)
                    value = words[-6]
                    keyval[key] = value
            else:
                continue
        for line in self.report_data:
            if 'System Benchmarks Index Score' in line:
                keyval['score'] = line.split()[-1]
                break

        if self.err is not None:
            self.fail('Test failure  Has been Occured \n %s' % self.err)
        else:
            self.log.info('System Benchmarks Index Score is %s \n'
                          'Please check log for full stat\n', keyval['score'])
