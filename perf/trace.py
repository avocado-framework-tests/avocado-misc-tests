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
# Copyright: 2021 IBM
# Author: Kalpana Shetty <kalshett@in.ibm.com>
#

import os

from avocado import Test
from avocado.utils import distro, process, archive, git
from avocado.utils.software_manager import SoftwareManager


class Linuxtrace(Test):

    """
    Linux Trace tests
    """

    @staticmethod
    def run_cmd_out(cmd):
        return process.system_output(cmd, shell=True, ignore_status=True,
                                     sudo=True)

    def setUp(self):
        '''
        Install the pre-requisites packages and download kernel source
        '''
        self.testdir = "tools/testing/selftests/ftrace"
        smg = SoftwareManager()
        self.run_type = self.params.get('type', default='upstream')
        detected_distro = distro.detect()

        if self.run_type == 'distro':
            # Make sure kernel source repo is configured
            if detected_distro.name in ['rhel', 'centos']:
                deps = ['yum-utils']
                for package in deps:
                    if not smg.check_installed(package) and not\
                            smg.install(package):
                        self.cancel("Fail to install %s\
                                    required for this test."
                                    % (package))
                uname_cmd = "uname -r | cut -f 1-4 -d '.'"
                self.output = self.run_cmd_out("%s" % uname_cmd).decode(
                                               "utf-8")
                kernel_src = ("kernel-%s.src" % self.output)

                download_cmd = ("yumdownloader --assumeyes --verbose\
                                --source %s --destdir %s" %
                                (kernel_src, self.workdir))
                self.run_cmd_out("%s" % download_cmd)

                install_rpm_cmd = ("rpm -i %s/%s.rpm" %
                                   (self.workdir, kernel_src))
                self.run_cmd_out("%s" % install_rpm_cmd)

                src_def_path = "/root/rpmbuild/SOURCES"
                linux_name = "linux-%s.tar.xz" % self.output
                tarball = "%s/%s" % (src_def_path, linux_name)
                archive.extract(tarball, self.workdir)
                os.chdir("%s/linux-%s/%s" % (self.workdir, self.output,
                         self.testdir))
            elif 'SuSE' in detected_distro.name:
                if not smg.check_installed("kernel-source") and not\
                        smg.install("kernel-source"):
                    self.cancel(
                        "Failed to install kernel-source for this test.")
                if not os.path.exists("/usr/src/linux"):
                    self.cancel("kernel source missing after install")
                self.output = "/usr/src/linux"
                os.chdir("%s/%s" % (self.output, self.testdir))
        else:
            location = self.params.get('location', default='https://github.c'
                                       'om/torvalds/linux/archive/master.zip')
            self.output = "master"

            match = next(
                (ext for ext in [".zip", ".tar"] if ext in location), None)
            if match:
                tarball = self.fetch_asset("kselftest%s" % match,
                                           locations=[location], expire='1d')
                archive.extract(tarball, self.workdir)
            else:
                git.get_repo(location, destination_dir=self.workdir)
            os.chdir("%s/linux-%s/%s" % (self.workdir, self.output,
                     self.testdir))

    def test_ftrace_basic(self):
        '''
        Execute ftrace basic tests
        '''
        self.log.info("ftrace basic tests...")
        self.run_cmd_out("./ftracetest ./test.d/00basic")

    def test_ftrace_event(self):
        '''
        Execute ftrace event tests
        '''
        self.log.info("ftrace event tests....")
        self.run_cmd_out("./ftracetest test.d/event")

    def test_ftrace(self):
        '''
        Execute ftrace tests
        '''
        self.log.info("ftrace tests....")
        self.run_cmd_out("./ftracetest test.d/ftrace")

    def test_ftrace_instances(self):
        '''
        Execute ftrace instances tests
        '''
        self.log.info("ftrace instaces tests....")
        self.run_cmd_out("./ftracetest test.d/instances")

    def test_ftrace_trigger(self):
        '''
        Execute ftrace trigger tests
        '''
        self.log.info("ftrace trigger tests....")
        self.run_cmd_out("./ftracetest test.d/trigger")

    def test_ftrace_kprobe(self):
        '''
        Execute ftrace kprobe tests
        '''
        self.log.info("ftrace kprobe tests....")
        self.run_cmd_out("./ftracetest test.d/kprobe")
