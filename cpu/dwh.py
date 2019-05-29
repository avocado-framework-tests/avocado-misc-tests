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
# Author: Harish <harish@linux.vnet.ibm.com>
#


import os
import shutil

from avocado import Test
from avocado import main
from avocado.utils import process, build, memory, distro, cpu
from avocado.utils.software_manager import SoftwareManager


class Dwh(Test):
    """
    DWH test case to run a task with large (or small) numbers of
    pthreads, including worker and dedicated I/O threads. It's purpose
    is to generate heavy workloads for a single task.
    """

    def copyutil(self, file_name):
        shutil.copyfile(self.get_data(file_name),
                        os.path.join(self.teststmpdir, file_name))

    def setUp(self):
        smm = SoftwareManager()
        self.minthreads = self.params.get(
            'minthrd', default=(500 + cpu.online_cpus_count()))
        self.maxthreads = self.params.get('maxthrd', default=None)
        self.iothreads = self.params.get('iothrd', default=self.minthreads/2)
        self.maxmem = self.params.get('maxmem', default=int(
            memory.meminfo.MemFree.m / self.minthreads))
        self.maxio = self.params.get('maxio', default=None)
        self.longthreads = self.params.get('longthrd', default=False)
        self.shrtthreads = self.params.get('shortthrd', default=False)
        self.time = self.params.get('time', default=100)
        self.iotime = self.params.get('iotime', default=50)

        if self.longthreads and self.shrtthreads:
            self.cancel('Please choose right inputs')

        dist = distro.detect()
        packages = ['gcc', 'patch']
        if dist.name == 'Ubuntu':
            packages.extend(['g++'])
        elif dist.name in ['SuSE', 'fedora', 'rhel']:
            packages.extend(['gcc-c++'])
        for package in packages:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

        for file_name in ['dwh.cpp', 'Makefile']:
            self.copyutil(file_name)
        os.chdir(self.teststmpdir)
        if dist.name in ['fedora', 'rhel']:
            process.system('patch -p0 < %s' %
                           self.get_data('fofd.patch'), shell=True)
        build.make(self.teststmpdir)

    def test(self):
        args = "--minthreads %s" % self.minthreads
        if self.maxthreads:
            args = "%s --maxthreads %s" % (args, self.maxthreads)
        if self.iothreads:
            args = "%s --iothreads %s" % (args, self.iothreads)
        if self.maxmem:
            args = "%s --maxmem %sM" % (args, self.maxmem)
        if self.maxio:
            args = "%s --maxiosize %sM" % (args, self.maxio)
        if self.longthreads:
            args = "%s --longthreads" % args
        if self.shrtthreads:
            args = "%s --shortthreads" % args
        if self.time:
            args = "%s --time %s" % (args, self.time)
        if self.iotime:
            args = "%s --iotimeout %s" % (args, self.iotime)
        if process.system('./dwh %s dwh.test' % args,
                          shell=True, ignore_status=True, sudo=True):
            self.fail("Please check the logs for debug")


if __name__ == "__main__":
    main()
