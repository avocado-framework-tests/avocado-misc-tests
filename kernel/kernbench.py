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
import re
import platform

from avocado import Test
from avocado.utils import build
from avocado.utils import process
from avocado.utils import cpu
from avocado.utils import distro
from avocado.utils import archive
from avocado.utils.software_manager import SoftwareManager


class Kernbench(Test):
    """
    Kernbench compiles the kernel source fetched from the kernel.org
    and compile it as per the configuration file. Performance figures will be
    shown in the log file.
    """

    def time_build(self, threads=None, timefile=None, make_opts=None):
        """
        Time the building of the kernel
        """
        os.chdir(self.sourcedir)
        build.make(self.sourcedir, extra_args='clean')
        if self.config_path is None:
            build.make(self.sourcedir, extra_args='defconfig')
        else:
            build.make(self.sourcedir, extra_args='olddefconfig')
        self.kernel_config_fix()
        if make_opts:
            build_string = "/usr/bin/time -o %s make %s -j %s vmlinux" % (
                timefile, make_opts, threads)
        else:
            build_string = "/usr/bin/time -o %s make -j %s vmlinux" % (
                timefile, threads)
        process.system(build_string, ignore_status=True, shell=True)
        if not os.path.isfile('vmlinux'):
            self.fail("No vmlinux found, kernel build failed")

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

    def kernel_config_fix(self):
        '''
        Distro specific config based kernel build can fail if config file
        has trusted/module signature key options enabled. Modify the config
        options in question to allow successful kernel build
        '''
        process.system("sed -i 's/^.*CONFIG_SYSTEM_TRUSTED_KEYS/#&/g' .config",
                       shell=True, sudo=True)
        process.system("sed -i 's/^.*CONFIG_SYSTEM_TRUSTED_KEYRING/#&/g' \
                       .config", shell=True, sudo=True)
        process.system("sed -i 's/^.*CONFIG_MODULE_SIG_KEY/#&/g' .config",
                       shell=True, sudo=True)
        process.system("sed -i 's/^.*CONFIG_DEBUG_INFO_BTF/#&/g' .config",
                       shell=True, sudo=True)

    def setUp(self):
        """
        Setting up the env for the kernel building
        """
        smg = SoftwareManager()
        self.detected_distro = distro.detect()
        deps = ['gcc', 'make', 'automake', 'autoconf', 'time', 'bison', 'flex']
        if 'Ubuntu' in self.detected_distro.name:
            deps.extend(['libpopt0', 'libc6', 'libc6-dev', 'libpopt-dev',
                         'libcap-ng0', 'libcap-ng-dev', 'elfutils', 'libelf1',
                         'libnuma-dev', 'libfuse-dev', 'libssl-dev'])
        elif 'SuSE' in self.detected_distro.name:
            deps.extend(['libpopt0', 'glibc', 'glibc-devel',
                         'popt-devel', 'libcap2', 'libcap-devel',
                         'libcap-ng-devel', 'openssl-devel'])
        elif self.detected_distro.name in ['centos', 'fedora', 'rhel']:
            deps.extend(['popt', 'glibc', 'glibc-devel', 'libcap-ng',
                         'libcap', 'libcap-devel', 'elfutils-libelf',
                         'elfutils-libelf-devel', 'openssl-devel'])

        for package in deps:
            if not smg.check_installed(package) and not smg.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        self.kernel_version = platform.uname()[2]
        self.iterations = self.params.get('runs', default=1)
        self.threads = self.params.get('cpus', default=None)
        if self.threads is None:
            self.threads = 2 * cpu.online_cpus_count()
        self.location = self.params.get(
            'url', default='https://github.com/torvalds/linux/archive'
            '/master.zip')
        self.config_path = os.path.join('/boot/config-', self.kernel_version)
        # Uncompress the kernel archive to the work directory
        tarball = self.fetch_asset("kernbench.zip", locations=[self.location],
                                   expire='1d')
        archive.extract(tarball, self.workdir)

    def test(self):
        """
        Kernel build Test
        """
        # Setting the kernel
        self.sourcedir = os.path.join(self.workdir, 'linux-master')

        self.log.info("Starting build the kernel")
        timefile = "%s/time_file" % self.sourcedir
        # Build kernel
        user_time = 0
        system_time = 0
        elapsed_time = 0
        for run in range(self.iterations):
            self.log.info("Iteration: %s" % (int(run) + 1))
            self.time_build(self.threads, timefile, "")
            # Processing the timefile
            results = open(timefile).readline().strip()
            (user, system, elapsed) = self.extract_all_time_results(results)[0]
            user_time += float(user)
            system_time += float(system)
            elapsed_time += float(elapsed)
        # Results
        self.log.info("Performance figures:")
        self.log.info("Iterations        : %s", self.iterations)
        self.log.info("Number of threads     : %s", self.threads)
        self.log.info("User      : %s", user_time)
        self.log.info("System    : %s", system_time)
        self.log.info("Elapsed   : %s", elapsed_time)
