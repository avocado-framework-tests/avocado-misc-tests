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
# Copyright: 2017 IBM
# Author: Harish <harish@linux.vnet.ibm.com>
#

import os
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils.software_manager import SoftwareManager


class Fsx(Test):
    '''
    The Fsx test is a file system exerciser test

    :avocado: tags=fs
    '''

    def setUp(self):
        '''
        Setup fsx
        '''
        smm = SoftwareManager()
        for package in ['gcc', 'make']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel(package + ' is needed for the test to be run')

        fsx = self.fetch_asset(
            'https://raw.githubusercontent.com/linux-test-project/ltp/'
            'master/testcases/kernel/fs/fsx-linux/fsx-linux.c', expire='7d')
        os.chdir(self.workdir)
        process.system('gcc -o fsx %s' % fsx, shell=True, ignore_status=True)

    def test(self):
        '''
        Run Fsx test for exercising file system
        '''
        file_ub = self.params.get('file_ub', default='1000000')
        op_ub = self.params.get('op_ub', default='1000000')
        output = self.params.get('output_file', default='/tmp/result')
        num_times = self.params.get('num_times', default='10000')

        results = process.system_output(
            './fsx   -l %s -o %s -n -s 1 -N %s -d %s'
            % (file_ub, op_ub, num_times, output))

        if b'All operations completed' not in results.splitlines()[-1]:
            self.fail('Fsx test failed')


if __name__ == "__main__":
    main()
