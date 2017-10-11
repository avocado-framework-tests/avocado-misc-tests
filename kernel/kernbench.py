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
# Copyright: 2017 IBM
# Author: Sudeesh John <sudeesh@linux.vnet.ibm.com>
# Author: Harish Sriram <harish@linux.vnet.ibm.com>
#
# Based on code by "mbligh@google.com (Martin Bligh)"
# https://github.com/autotest/autotest-client-tests/commits/master/kernbench

import os
import logging
import re
import platform

from avocado import Test
from avocado import main
from avocado.utils import build
from avocado.utils import process
from avocado.utils import kernel
from avocado.utils import cpu
from avocado.utils import distro
from avocado.utils.software_manager import SoftwareManager

log = logging.getLogger('avocado.test')


class Kernbench(Test):
    """
    Kernbench compiles the kernel source fetched from the kernel.org
    and compile it as per the configuration file. Performance figures will be
    shown in the log file.
    """

    def time_build(self, kern,
                   threads=None, timefile=None, make_opts=None):
        """
        Time the bulding of the kernel
        """
        os.chdir(kern.linux_dir)
        build.make(kern.linux_dir, extra_args='clean')
        if kern.config_path is None:
            build.make(kern.linux_dir, extra_args='defconfig')
        else:
            build.make(kern.linux_dir, extra_args='oldnoconfig')
        if make_opts:
            build_string = "/usr/bin/time -o %s make %s -j %s vmlinux" % (
                timefile, make_opts, threads)
        else:
            build_string = "/usr/bin/time -o %s make -j %s vmlinux" % (
                timefile, threads)
        process.system(build_string, allow_output_check='None', shell=True)
        if not os.path.isfile('vmlinux'):
            self.error("No vmlinux found, kernel build failed")

    @staticmethod
    def to_seconds(time_string):
        """
        Converts a string in M+:SS.SS format to S+.SS
        """
        elts = time_string.split(':')
        if len(elts) == 1:
            return time_string
        return str(int(elts[0]) * 60 + float(elts[1]))

    def extract_all_time_results(self, results_string):
        """
        Extract user, system, and elapsed times into a list of tuples
        """
        pattern = re.compile(r"(.*?)user (.*?)system (.*?)elapsed")
        results = []
        for result in pattern.findall(results_string):
            results.append(tuple([self.to_seconds(elt) for elt in result]))
        return results

    def setUp(self):
        """
        Setting up the env for the kernel building
        """
        smg = SoftwareManager()
        detected_distro = distro.detect()
        deps = ['gcc', 'make', 'automake', 'autoconf', 'time']
        if 'Ubuntu' in detected_distro.name:
            deps.extend(['libpopt0', 'libc6', 'libc6-dev', 'libpopt-dev',
                         'libcap-ng0', 'libcap-ng-dev', 'elfutils', 'libelf1',
                         'libnuma-dev', 'libfuse-dev'])
        elif 'SuSE' in detected_distro.name:
            deps.extend(['libpopt0', 'glibc', 'glibc-devel',
                         'popt-devel', 'libcap1', 'libcap-devel',
                         'libcap-ng-devel'])
        # FIXME: "redhat" as the distro name for RHEL is deprecated
        # on Avocado versions >= 50.0.  This is a temporary compatibility
        # enabler for older runners, but should be removed soon
        elif detected_distro.name in ['centos', 'fedora', 'rhel', 'redhat']:
            deps.extend(['popt', 'glibc', 'glibc-devel', 'libcap-ng',
                         'libcap', 'libcap-devel', 'elfutils-libelf',
                         'elfutils-libelf-devel', 'openssl-devel'])

        for package in deps:
            if not smg.check_installed(package) and not smg.install(package):
                self.cancel(package + ' is needed for the test to be run')
        self.kernel_version = platform.uname()[2]
        self.iterations = self.params.get('runs', default=1)
        self.threads = self.params.get(
            'cpus', default=2 * cpu.online_cpus_count())
        self.version = self.params.get('version', default='4.6')
        self.config_path = '/boot/config-' + self.kernel_version

    def test(self):
        """
        Kernel build Test
        """
        # Initialize kernel object
        kern = kernel.KernelBuild(
            self.version, config_path=self.config_path,
            work_dir=None, data_dirs=None)
        # Setting the default kernel URL
        kern.URL = 'https://www.kernel.org/pub/linux/kernel/v4.x/'
        # Download the kernel tarball from kernel.org
        kern.download()
        # Uncompress the kernel archive to the work directory
        kern.uncompress()
        # Running configure script
        kern.configure()
        log.info("Starting build the kernel")
        timefile = "%s/time_file" % kern.build_dir
        # Build kernel
        user_time = 0
        system_time = 0
        elapsed_time = 0
        for run in range(self.iterations):
            log.info("Iteration: %s" % int(run) + 1)
            self.time_build(kern, self.threads, timefile, "")
            # Processing the timefile
            results = open(timefile).readline().strip()
            (user, system, elapsed) = self.extract_all_time_results(results)[0]
            user_time += float(user)
            system_time += float(system)
            elapsed_time += float(elapsed)
        # Results
        log.info("Performance figures:")
        log.info("Iterations        : %s", self.iterations)
        log.info("Number of threads     : %s", self.threads)
        log.info("Kernel version        : %s", self.version)
        log.info("User      : %s", user_time)
        log.info("System    : %s", system_time)
        log.info("Elapsed   : %s", elapsed_time)


if __name__ == "__main__":
    main()
