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
# Copyright: 2018 IBM.
# Author: Kamalesh Babulal <kamalesh@linux.vnet.ibm.com>

import os
import shutil
import tempfile
from avocado import Test
from avocado.utils import build
from avocado.utils import distro
from avocado.utils import process
from avocado.utils import dmesg
from avocado.utils.software_manager.manager import SoftwareManager


class Kretprobe(Test):

    """
    Test kernel kretprobe
    :avocado: tags=privileged
    """

    fail_cmd = list()

    def run_cmd(self, cmd):
        self.log.info("executing ============== %s =================", cmd)
        if process.system(cmd, ignore_status=True, sudo=True, shell=True):
            self.is_fail += 1
            self.fail_cmd.append(cmd)
        return

    @staticmethod
    def run_cmd_out(cmd):
        return process.system_output(cmd, shell=True, ignore_status=True,
                                     sudo=True).decode("utf-8")

    def setUp(self):
        """
        Setting up the env for the kernel building
        """
        smg = SoftwareManager()
        detected_distro = distro.detect()
        deps = ['gcc', 'make', 'automake', 'autoconf', 'time', 'bison', 'flex']
        if detected_distro.name in ['Ubuntu', 'debian']:
            linux_headers = 'linux-headers-%s' % os.uname()[2]
            deps.extend(['libpopt0', 'libc6', 'libc6-dev', 'libpopt-dev',
                         'libcap-ng0', 'libcap-ng-dev', 'elfutils', 'libelf1',
                         'libnuma-dev', 'libfuse-dev', 'libssl-dev', linux_headers])
        elif 'SuSE' in detected_distro.name:
            deps.extend(['libpopt0', 'glibc', 'glibc-devel',
                         'popt-devel', 'libcap2', 'libcap-devel', 'kernel-syms',
                         'libcap-ng-devel', 'openssl-devel', 'kernel-source'])
        elif detected_distro.name in ['centos', 'fedora', 'rhel']:
            deps.extend(['popt', 'glibc', 'glibc-devel', 'libcap-ng',
                         'libcap', 'libcap-devel', 'elfutils-libelf',
                         'elfutils-libelf-devel', 'openssl-devel',
                         'kernel-devel', 'kernel-headers'])
        for package in deps:
            if not smg.check_installed(package) and not smg.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        cmd = "lsprop  /proc/device-tree/ibm,secure-boot"
        output = process.system_output(cmd, ignore_status=True).decode()
        if '00000002' in output:
            self.cancel("Secure boot is enabled.")

    def build_module(self):
        """
        Building of the kretprobe kernel module
        """
        self.log.info(
            "============== Building kretprobe Module =================")
        self.sourcedir = tempfile.mkdtemp()
        os.chdir(self.sourcedir)

        self.location = ('https://raw.githubusercontent.com/torvalds/linux/'
                         'master/samples/kprobes/kretprobe_example.c')
        self.kretprobe_file = self.fetch_asset(self.location, expire='7d')
        self.kretprobe_dst = os.path.join(
            self.sourcedir, 'kretprobe_example.c')
        shutil.copy(self.kretprobe_file, self.kretprobe_dst)

        """
        Write module make file on the fly
        """
        makefile = open("Makefile", "w")
        makefile.write('obj-m := kretprobe_example.o\nKDIR := /lib/modules/$(shell uname -r)/build'
                       '\nPWD := $(shell pwd)\ndefault:\n\t'
                       '$(MAKE) -C $(KDIR) M=$(shell pwd) modules\n')
        makefile.close()

        self.is_fail = 0
        build.make(self.sourcedir)
        if self.is_fail >= 1:
            self.fail("Building kretprobe_example.ko failed")
        if not os.path.isfile('./kretprobe_example.ko'):
            self.fail("No kretprobe_example.ko found, module build failed")

    def execute_test(self):
        self.log.info("============== Testing kretprobe =================")
        dmesg.clear_dmesg()
        self.run_cmd("insmod ./kretprobe_example.ko")
        if self.is_fail >= 1:
            self.fail("insmod kretprobe_example.ko failed")

        if "Planted return probe" not in self.run_cmd_out("dmesg |grep -i planted"):
            self.fail(
                "kretprobe couldn't be planted, check dmesg for more information")

        """
        Execute date to trigger kernel_clone syscall
        """
        self.run_cmd("date")

        if "return" not in self.run_cmd_out("dmesg |grep -i kernel_clone"):
            self.fail(
                "kretprobe probing issues, check dmesg for more information")

        self.run_cmd("rmmod kretprobe_example")
        if self.is_fail >= 1:
            self.fail("rmmod kretprobe_example.ko failed")

        if "kretprobe" not in self.run_cmd_out("dmesg |grep -i unregistered"):
            self.fail(
                "kretprobe unregistering failed, check dmesg for more information")

    def test(self):
        self.build_module()
        self.execute_test()
