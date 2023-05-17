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
# Author: Abdul Haleem <abdhalee@linux.vnet.ibm.com>

import os
import platform
import re
import glob
import shutil

from avocado import Test
from avocado.utils import build, process
from avocado.utils import distro
from avocado.utils import archive, git
from avocado.utils.software_manager.manager import SoftwareManager


class kselftest(Test):
    """
    Linux Kernel Selftest available as a part of kernel source code.
    run the selftest available at tools/testing/selftest

    :see: https://www.kernel.org/doc/Documentation/kselftest.txt
    :source: https://github.com/torvalds/linux/archive/master.zip

    :avocado: tags=kernel
    """
    testdir = 'tools/testing/selftests'

    def find_match(self, match_str, line):
        match = re.search(match_str, line)
        if match:
            self.error = True
            self.log.info("Testcase failed. Log from debug: %s" %
                          match.group(0))

    def setUp(self):
        """
        Resolve the packages dependencies and download the source.
        """
        smg = SoftwareManager()
        self.comp = self.params.get('comp', default='')
        self.subtest = self.params.get('subtest', default='')
        if self.comp == "vm" and self.subtest == "ksm_tests":
            self.test_type = self.params.get('test_type', default='-H')
            self.Size_flag = self.params.get('Size', default='-s')
            self.Dup_MM_Area = self.params.get('Dup_MM_Area', default='100')
        self.build_option = self.params.get('build_option', default='-bp')
        self.run_type = self.params.get('type', default='upstream')
        detected_distro = distro.detect()
        deps = ['gcc', 'make', 'automake', 'autoconf', 'rsync']

        if detected_distro.name in ['Ubuntu', 'debian']:
            deps.extend(['libpopt0', 'libc6', 'libc6-dev', 'libcap-dev',
                         'libpopt-dev', 'libcap-ng0', 'libcap-ng-dev',
                         'libnuma-dev', 'libfuse-dev', 'elfutils', 'libelf1',
                         'libhugetlbfs-dev'])
        elif 'SuSE' in detected_distro.name:
            deps.extend(['glibc', 'glibc-devel', 'popt-devel', 'sudo',
                         'libcap2', 'libcap-devel', 'libcap-ng-devel',
                         'fuse', 'fuse-devel', 'glibc-devel-static',
                         'traceroute', 'iproute2', 'socat', 'clang7',
                         'libnuma-devel'])
            if detected_distro.version >= 15:
                deps.extend(['libhugetlbfs-devel'])
            else:
                deps.extend(['libhugetlbfs-libhugetlb-devel'])
        elif detected_distro.name in ['centos', 'fedora', 'rhel']:
            deps.extend(['popt', 'glibc', 'glibc-devel', 'glibc-static',
                         'libcap-ng', 'libcap', 'libcap-devel',
                         'libcap-ng-devel', 'popt-devel',
                         'libhugetlbfs-devel', 'clang', 'traceroute',
                         'iproute-tc', 'socat', 'numactl-devel'])
            dis_ver = int(detected_distro.version)
            if detected_distro.name == 'rhel' and dis_ver >= 9:
                packages_remove = ['libhugetlbfs-devel']
                deps = list(set(deps)-set(packages_remove))
                deps.extend(['fuse3-devel'])
            else:
                deps.extend(['fuse-devel'])

        for package in deps:
            if not smg.check_installed(package) and not smg.install(package):
                self.cancel(
                    "Fail to install %s package" % (package))

        if self.run_type == 'upstream':
            location = self.params.get('location', default='https://github.c'
                                       'om/torvalds/linux/archive/master.zip')
            path = ''
            match = next(
                (ext for ext in [".zip", ".tar"] if ext in location), None)
            if match:
                tarball = self.fetch_asset("kselftest%s" % match,
                                           locations=[location], expire='1d')
                archive.extract(tarball, self.workdir)
                path = glob.glob(os.path.join(self.workdir, "linux*"))
            else:
                git.get_repo(location, destination_dir=self.workdir)
                path = glob.glob(self.workdir)
            for l_dir in path:
                if os.path.isdir(l_dir) and 'Makefile' in os.listdir(l_dir):
                    self.buldir = os.path.join(self.workdir, l_dir)
                    break
        else:
            if self.subtest == 'pmu/event_code_tests':
                self.cancel("selftest not supported on distro")
            # Make sure kernel source repo is configured
            if detected_distro.name in ['centos', 'fedora', 'rhel']:
                src_name = 'kernel'
                if detected_distro.name == 'rhel':
                    # Check for "el*a" where ALT always ends with 'a'
                    if platform.uname()[2].split(".")[-2].endswith('a'):
                        self.log.info('Using ALT as kernel source')
                        src_name = 'kernel-alt'
                self.buldir = smg.get_source(
                    src_name, self.workdir, self.build_option)
                self.buldir = os.path.join(
                    self.buldir, os.listdir(self.buldir)[0])
            elif detected_distro.name in ['Ubuntu', 'debian']:
                self.buldir = smg.get_source('linux', self.workdir)
            elif 'SuSE' in detected_distro.name:
                if not smg.check_installed("kernel-source") and not\
                        smg.install("kernel-source"):
                    self.cancel(
                        "Failed to install kernel-source for this test.")
                if not os.path.exists("/usr/src/linux"):
                    self.cancel("kernel source missing after install")
                self.buldir = "/usr/src/linux"

        self.sourcedir = os.path.join(self.buldir, self.testdir)
        # cmsg_* tests from net/ subdirectory takes a lot of time to complete.
        # Until they have been root caused skip them.
        if self.comp == 'net':
            make_path = self.sourcedir + "/net/Makefile"
            process.system("sed -i 's/^.*cmsg_so_mark.sh/#&/g' %s" % make_path,
                           shell=True, sudo=True)
            process.system("sed -i 's/^.*cmsg_time.sh/#&/g' %s" % make_path,
                           shell=True, sudo=True)
        if self.comp:
            build_str = '-C %s' % self.comp
        if build.make(self.sourcedir, extra_args='%s' % build_str):
            self.fail("Compilation failed, Please check the build logs !!")

    def test(self):
        """
        Execute the kernel selftest
        """
        self.error = False
        kself_args = self.params.get("kself_args", default='')
        if self.comp == "bpf":
            self.bpf()
        else:
            if self.subtest == "ksm_tests":
                self.ksmtest()
            else:
                if self.subtest:
                    test_comp = self.comp + "/" + self.subtest
                else:
                    test_comp = self.comp
                build.make(self.sourcedir,
                           extra_args='%s -C %s run_tests' %
                           (kself_args, test_comp))
        for line in open(os.path.join(self.logdir, 'debug.log')).readlines():
            if self.run_type == 'upstream':
                self.find_match(r'not ok (.*) selftests:(.*)', line)
            elif self.run_type == 'distro':
                if distro.detect().name == 'SuSE' and\
                        distro.detect().version == 12:
                    self.find_match(r'selftests:(.*)\[FAIL\]', line)
                else:
                    self.find_match(r'not ok (.*) selftests:(.*)', line)

        if self.error:
            self.fail("Testcase failed during selftests")

    def run_cmd(self, cmd):
        """
        Run the command:
        Ex: ./ksm_tests -M
        """
        try:
            process.run(cmd, ignore_status=False, sudo=True)
        except process.CmdError as details:
            self.fail("Command %s failed: %s" % (cmd, details))

    def ksmtest(self):
        """
        Run the different ksm test types:
        Ex: -M (page merging)
        """
        ksm_test_dir = self.sourcedir + "/vm/"
        ksm_test_bin = ksm_test_dir+"/ksm_tests"
        self.test_list = ["-M", "-Z", "-N", "-U", "-C"]
        if os.path.exists(ksm_test_bin):
            os.chdir(ksm_test_dir)
            if(self.test_type == "-H" or self.test_type == "-P"):
                arg_payload = " ".join(["./ksm_tests", self.test_type,
                                       self.Size_flag, self.Dup_MM_Area])
                self.run_cmd(arg_payload)
            elif(self.test_type in self.test_list):
                arg_payload = " ".join(["./ksm_tests", self.test_type])
                self.run_cmd(arg_payload)
            else:
                self.cancel("Invalid test_type for ksm_tests:- {}"
                            .format(self.test_type))
        else:
            self.cancel("Invalid ksm_tests build path:- {}"
                        .format(ksm_test_dir))

    def bpf(self):
        bpf_test_dir = self.sourcedir + "/bpf/"
        os.chdir(bpf_test_dir)
        build.make(bpf_test_dir)
        self.run_cmd("./test_verifier")
        build.make(bpf_test_dir, extra_args='run_tests')

    def tearDown(self):
        self.log.info('Cleaning up')
        if os.path.exists(self.workdir):
            shutil.rmtree(self.workdir)
