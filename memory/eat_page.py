#!/usr/bin/env python
#
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
# Copyright: 2019 IBM
# Author: Praveen K Pandey<praveen@linux.vnet.ibm.com>
#


import os
import shutil

from avocado import Test
from avocado import main
from avocado.utils import process, build
from avocado.utils.software_manager import SoftwareManager


errorlog = ['WARNING: CPU:', 'Oops',
            'Segfault', 'soft lockup',
            'Unable to handle paging request',
            'rcu_sched detected stalls',
            'NMI backtrace for cpu',
            'WARNING: at',
            'INFO: possible recursive locking detected',
            'double fault:', 'BUG: Bad page state in']


def clear_dmesg():
    process.run("dmesg -C ", sudo=True)


def collect_dmesg(object):
    object.whiteboard = process.system_output("dmesg")


class EatPage(Test):
    """
    This test consume pages to force low memory kernel and application failures
    """

    def copyutil(self, file_name):
        shutil.copyfile(self.get_data(file_name),
                        os.path.join(self.teststmpdir, file_name))

    def __error_check(self):
        ERROR = []
        logs = process.system_output("dmesg -Txl 1,2,3,4").splitlines()
        for error in errorlog:
            for log in logs:
                if error in log:
                    ERROR.append(log)
        if "\n".join(ERROR):
            collect_dmesg(self)
            self.fail('ERROR: Test failed, please check the dmesg logs')

    def setUp(self):
        smm = SoftwareManager()
        self.time = self.params.get('time', default=20)
        for package in ['gcc', 'make']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

        for file_name in ['eat_page.c', 'Makefile']:
            self.copyutil(file_name)

        build.make(self.teststmpdir)
        clear_dmesg()

    def test(self):
        os.chdir(self.teststmpdir)
        process.system('./eat_page', shell=True, sudo=True,
                       timeout=self.time, ignore_status=True)
        self.__error_check()


if __name__ == "__main__":
    main()
