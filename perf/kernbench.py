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
# Author: Sudeesh John <sudeesh@linux.vnet.ibm.com>
#
# Based on code by "mbligh@google.com (Martin Bligh)"
# https://github.com/autotest/autotest-client-tests/commits/master/kernbench

import os
import multiprocessing
import logging
import re
import platform

from avocado import Test
from avocado import main
from avocado.utils import build
from avocado.utils import process
from avocado.utils import kernel
from avocado.utils.software_manager import SoftwareManager

log = logging.getLogger('avocado.test')


class KernbenchTest(Test):
    """
    Kernbench comples the kernel source fetched from the kernel.org
    and compile it as per the configuration file. Performance figures will be
    shown in the log file.
    """

    def time_build(self, kern,
                   threads=None, timefile=None, make_opts=None):
        """time the bulding of the kernel"""
        os.chdir(kern.linux_dir)
        build.make(kern.linux_dir, extra_args='clean')
        if kern.config_path is None:
            build.make(kern.linux_dir, extra_args='defconfig')
        else:
            build.make(kern.linux_dir, extra_args='oldnoconfig')
        process.system('make silentoldconfig')
        if make_opts:
            build_string = ("/usr/bin/time -o %s make %s -j %s vmlinux" %
                            (timefile, make_opts, threads))
        else:
            build_string = ("/usr/bin/time -o %s make -j %s vmlinux" %
                            (timefile, threads))
        process.system(build_string, allow_output_check='None')
        if not os.path.isfile('vmlinux'):
            self.error("No vmlinux found, kernel build failed")

    def setUp(self):
        """
        setting up the env for the kernel building
        """
        smg = SoftwareManager()
        deps = ['gcc', 'make', 'automake', 'autoconf', 'time']
        for package in deps:
            if smg.check_installed(package) and not smg.install(package):
                self.error(package + ' is needed for the test to be run')

    def to_seconds(self, time_string):
        """Converts a string in M+:SS.SS format to S+.SS"""
        elts = time_string.split(':')
        if len(elts) == 1:
            return time_string
        return str(int(elts[0]) * 60 + float(elts[1]))

    def extract_all_time_results(self, results_string):
        """Extract user, system, and elapsed times into a list of tuples"""
        pattern = re.compile(r"(.*?)user (.*?)system (.*?)elapsed")
        results = []
        for result in pattern.findall(results_string):
            results.append(tuple([self.to_seconds(elt) for elt in result]))
        return results

    def test(self):
        """
        Kernel build Test
        """
        iterations = self.params.get('runs', default=1)
        threads = self.params.get('cpus', default=None)
        version = self.params.get('version', default='4.6')
        kernel_version = platform.uname()[2]
        config_path = '/boot/config-' + kernel_version
        if iterations is None:
            # Setting the default iteration as one
            iterations = 1
        if version is None:
            # setting the default version 4.6
            version = '4.6'
        if threads is None:
            # We will use 2 workers of each type for each CPU detected
            threads = 2 * multiprocessing.cpu_count()
        # initialize kernel object
        kern = kernel.KernelBuild(
            version, config_path=config_path, work_dir=None, data_dirs=None)
        # Seeting the default kernel URL
        kern.URL = 'https://www.kernel.org/pub/linux/kernel/v4.x/'
        # download the kernel tarball from kernel.org
        kern.download()
        # Uncompress the kernel archive to the work directory
        kern.uncompress()
        # Running configure script
        kern.configure()
        log.info("Starting build the kernel")
        timefile = ("%s/time_file" % kern.build_dir)
        # Build kernel
        user_time = 0
        system_time = 0
        elapsed_time = 0
        for run in range(iterations):
            log.info("Iteration: %s" % run)
            self.time_build(kern, threads, timefile, "")
            # Processing the timefile
            results = open(timefile).readline().strip()
            (user, system, elapsed) = self.extract_all_time_results(results)[0]
            user_time += float(user)
            system_time += float(system)
            elapsed_time += float(elapsed)
        # Reults
        log.info("Performance figures:")
        log.info("Iterations        : %s", iterations)
        log.info("Number of threads     : %s", threads)
        log.info("Kernel version        : %s", version)
        log.info("User      : %s", user_time)
        log.info("System    : %s", system_time)
        log.info("Elapsed   : %s", elapsed_time)

if __name__ == "__main__":
    main()
