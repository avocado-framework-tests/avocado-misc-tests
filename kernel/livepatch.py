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
import time
from avocado import Test
from avocado import main
from avocado.utils import build
from avocado.utils import distro
from avocado.utils import process
from avocado.utils import linux_modules
from avocado.utils import genio
from avocado.utils.software_manager import SoftwareManager


class Livepatch(Test):

    """
    Test kernel livepatching
    :avocado: tags=kernel
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
                                     sudo=True)

    def clear_dmesg(self):
        process.run("dmesg -C ", sudo=True)

    def check_kernel_support(self):
        if linux_modules.check_kernel_config("CONFIG_LIVEPATCH") == linux_modules.ModuleConfig.NOT_SET:
            self.fail("Livepatch support not available")

    def setUp(self):
        """
        Setting up the env for the livepatch module building
        """
        self.check_kernel_support()
        smg = SoftwareManager()
        detected_distro = distro.detect()
        deps = ['gcc', 'make', 'automake', 'autoconf', 'time', 'bison', 'flex']
        if 'Ubuntu' in detected_distro.name:
            linux_headers = 'linux-headers-%s' % os.uname()[2]
            deps.extend(['libpopt0', 'libc6', 'libc6-dev', 'libpopt-dev',
                         'libcap-ng0', 'libcap-ng-dev', 'elfutils', 'libelf1',
                         'libnuma-dev', 'libfuse-dev', 'libssl-dev',
                         linux_headers])
        elif 'SuSE' in detected_distro.name:
            deps.extend(['libpopt0', 'glibc', 'glibc-devel',
                         'popt-devel', 'libcap2', 'libcap-devel',
                         'kernel-syms', 'libcap-ng-devel', 'libopenssl-devel',
                         'kernel-source'])
        elif detected_distro.name in ['centos', 'fedora', 'rhel']:
            deps.extend(['popt', 'glibc', 'glibc-devel', 'libcap-ng',
                         'libcap', 'libcap-devel', 'elfutils-libelf',
                         'elfutils-libelf-devel', 'openssl-devel',
                         'kernel-devel', 'kernel-headers'])
        for package in deps:
            if not smg.check_installed(package) and not smg.install(package):
                self.cancel('%s is needed for the test to be run' % package)

    def build_module(self):
        """
        Building of the livepatching kernel module
        """
        self.log.info(
            "============== Building livepatching Module =================")
        self.sourcedir = tempfile.mkdtemp()
        os.chdir(self.sourcedir)

        self.location = ('https://raw.githubusercontent.com/torvalds/linux/'
                         'master/samples/livepatch/livepatch-sample.c')
        self.livepatch_file = self.fetch_asset(self.location, expire='7d')
        self.livepatch_dst = os.path.join(self.sourcedir, 'livepatch-sample.c')
        shutil.copy(self.livepatch_file, self.livepatch_dst)

        """
        Write module make file on the fly
        """
        makefile = open("Makefile", "w")
        makefile.write('obj-m := livepatch-sample.o\nKDIR '
                       ':= /lib/modules/$(shell uname -r)/build'
                       '\nPWD := $(shell pwd)\ndefault:\n\t'
                       '$(MAKE) -C $(KDIR) SUBDIRS=$(PWD) modules\n')
        makefile.close()

        if build.make(self.sourcedir) >= 1:
            self.fail("Building livepatch-sample.ko failed")
        if not os.path.isfile('./livepatch-sample.ko'):
            self.fail("No livepatch-sample.ko found, module build failed")

    def execute_test(self):
        self.log.info("============== Enabling livepatching ===============")
        self.clear_dmesg()
        self.is_fail = 0
        self.run_cmd("insmod ./livepatch-sample.ko")
        if self.is_fail >= 1:
            self.fail("insmod livepatch-sample.ko failed")

        if "enabling patch" not in \
                self.run_cmd_out("dmesg |grep -i livepatch_sample"):
            self.fail("livepatch couldn't be enabled, "
                      "check dmesg for more information")

        """
        Execute /proc/cmdline, to check if livepatch works
        """
        if "this has been live patched" not \
                in genio.read_one_line("/proc/cmdline"):
            self.fail("livepatching unsuccessful, "
                      "check dmesg for more information")

        self.log.info("=========== Disabling livepatching ===============")
        genio.write_one_line(
            "/sys/kernel/livepatch/livepatch_sample/enabled", "0")
        if "0" not in genio.read_one_line("/sys/kernel/livepatch/"
                                          "livepatch_sample/enabled"):
            self.fail("Unable to disable livepatch "
                      "for livepatch_sample module")

        if "unpatching transition" not in self.run_cmd_out("dmesg |grep "
                                                           "-i livepatch_sample"):
            self.fail(
                "livepatch couldn't be disabled, check dmesg "
                "for more information")

        if "this has been live patched" in \
                genio.read_one_line("/proc/cmdline"):
            self.fail(
                "livepatching disabling unsuccessful, check dmesg "
                "for more information")

        """
        Wait for 3 minutes before trying to remove the livepatching module
        """
        time.sleep(60 * 3)
        self.run_cmd("rmmod livepatch-sample")
        if self.is_fail >= 1:
            self.log.info("rmmod livepatch-sample.ko failed, "
                          "try removing it manual after sometime")

    def test(self):
        self.build_module()
        self.execute_test()


if __name__ == "__main__":
    main()
