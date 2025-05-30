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
from avocado.utils import genio
from avocado.utils import build
from avocado.utils import distro
from avocado.utils import process
from avocado.utils import linux_modules
from avocado.utils import dmesg
from avocado.utils import linux
from avocado.utils.software_manager.manager import SoftwareManager


class Kprobe(Test):

    """
    Test kernel kprobe
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

    def check_kernel_support(self):
        if linux_modules.check_kernel_config("CONFIG_OPTPROBES") == linux_modules.ModuleConfig.NOT_SET:
            return 0
        return 1

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
        if not linux.is_os_secureboot_enabled():
            self.cancel("Secure boot is enabled.")

    def build_module(self):
        """
        Building of the kprobe kernel module
        """
        self.log.info(
            "============== Building kprobe Module =================")
        self.sourcedir = tempfile.mkdtemp()
        os.chdir(self.sourcedir)

        self.location = ('https://raw.githubusercontent.com/torvalds/linux/'
                         'master/samples/kprobes/kprobe_example.c')
        self.kprobe_file = self.fetch_asset(self.location, expire='7d')
        self.kprobe_dst = os.path.join(self.sourcedir, 'kprobe_example.c')
        shutil.copy(self.kprobe_file, self.kprobe_dst)

        """
        Write module make file on the fly
        """
        makefile = open("Makefile", "w")
        makefile.write('obj-m := kprobe_example.o\nKDIR := /lib/modules/$(shell uname -r)/build'
                       '\nPWD := $(shell pwd)\ndefault:\n\t'
                       '$(MAKE) -C $(KDIR) M=$(shell pwd) modules\n')
        makefile.close()

        self.is_fail = 0
        build.make(self.sourcedir)
        if self.is_fail >= 1:
            self.fail("Building kprobe_example.ko failed")
        if not os.path.isfile('./kprobe_example.ko'):
            self.fail("No kprobe_example.ko found, module build failed")

    def execute_test(self):
        self.log.info("============== Testing kprobe =================")
        dmesg.clear_dmesg()
        self.run_cmd("insmod ./kprobe_example.ko")
        if self.is_fail >= 1:
            self.fail("insmod kprobe_example.ko failed")

        if "Planted kprobe" not in self.run_cmd_out("dmesg |grep -i planted"):
            self.fail(
                "kprobe couldn't be planted, check dmesg for more information")

        """
        Execute date to trigger kernel_clone syscall
        """
        self.run_cmd("date")

        if "handler_pre" not in self.run_cmd_out("dmesg |grep -i kernel_clone"):
            self.fail("kprobe probing issues, check dmesg for more information")

        self.run_cmd("rmmod kprobe_example")
        if self.is_fail >= 1:
            self.fail("rmmod kprobe_example.ko failed")

        if "kprobe" not in self.run_cmd_out("dmesg |grep -i unregistered"):
            self.fail(
                "kprobe unregistering failed, check dmesg for more information")

    def optprobes_disable_test(self):
        optprobes_file = "/proc/sys/debug/kprobes-optimization"
        if not self.check_kernel_support():
            self.log.info(
                "No support available for optprobes, skipping optprobes test")
            return

        if not os.path.exists(optprobes_file):
            self.log.info("optprobes control file %s missing, skipping optprobes test",
                          optprobes_file)
            return

        cur_val = genio.read_one_line(optprobes_file)
        genio.write_one_line(optprobes_file, "0")
        self.log.info(
            "================= Disabling optprobes ==================")
        if "0" not in genio.read_one_line(optprobes_file):
            self.fail("Not able to disable optprobes")
        self.execute_test()

        self.log.info(
            "================= Restoring optprobes ==================")
        genio.write_one_line(optprobes_file, cur_val)
        if cur_val not in genio.read_one_line(optprobes_file):
            self.fail("Not able to restore optprobes to %s", cur_val)

    def test(self):
        self.build_module()
        self.execute_test()
        self.optprobes_disable_test()
