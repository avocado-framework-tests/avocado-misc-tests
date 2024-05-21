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
# Copyright: 2024 IBM
# Author: Samir A Mulani <samir@linux.vnet.ibm.com>

import os
import shutil
from avocado import Test
from avocado.utils import process, distro, archive
from avocado.utils import build, distro, git
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils import linux_modules


class perf_sched_pip_workload(Test):

    def setUp(self):
        """
        This test case basically performance stats for kernel spinlock
        """
        smg = SoftwareManager()
        detected_distro = distro.detect()
        deps = ['gcc', 'make', 'automake', 'autoconf', 'time', 'bison', 'flex']
        if detected_distro.name in ['Ubuntu', 'debian']:
            linux_headers = 'linux-headers-%s' % os.uname()[2]
            deps.extend(['libc6', 'libc6-dev',
                         'libssl-dev', linux_headers])
        elif 'SuSE' in detected_distro.name:
            deps.extend(['glibc', 'glibc-devel', 'kernel-syms',
                         'openssl-devel', 'kernel-source'])
        elif detected_distro.name in ['centos', 'fedora', 'rhel']:
            deps.extend(['glibc', 'glibc-devel',
                         'kernel-devel', 'kernel-headers'])
        for package in deps:
            if not smg.check_installed(package) and not smg.install(package):
                self.cancel(f'{package} is needed for the test to be run')

        self.cpu_list = self.params.get("cpu_list", default=0)

        url = "https://github.com/npiggin/lockstorm.git"
        git.get_repo(url, branch='master', destination_dir=self.workdir)
        os.chdir(self.workdir)
        build.make(self.workdir)
        if not os.path.isfile("lockstorm.ko"):
            self.cancel("Module build failed. Please check the build log")

    def capture_dmesg_dump(self, smt_state):
        """
        This function capture the spinlock performance stats from dmesg.
        """
        cmd = "dmesg | tail -n 1"
        self.log.info(f"=================Dump data for \
                SMT Mode: {smt_state} benchmark======================\n\n")
        dump_data = process.run(cmd, shell=True)

    def test(self):
        """
        In this funtion basically we are changing the SMT states
        and running the lockstorm benchamrk.
        1.changing the SMT modes.
        2.Running the lockstorm benchamrk.
        3. Capturing the benchmark stats.
        """
        process.run('ppc64_cpu --cores-on=all', shell=True)
        process.run('ppc64_cpu --smt=on', shell=True)
        cpu_controller = ["2", "4", "6", "on", "off"]
        for smt_mode in cpu_controller:
            cmd = "ppc64_cpu --smt={}".format(smt_mode)
            self.log.info(f"=======smt mode {smt_mode}=======")
            process.run(cmd, shell=True)
            if self.cpu_list == 0:
                process.system("insmod ./lockstorm.ko",
                               ignore_status=True, shell=False, sudo=True)
            else:
                cmd = "insmod ./lockstorm.ko" + " cpulist=%s" % \
                        (self.cpu_list)
                process.run(cmd, shell=True)

            self.capture_dmesg_dump(smt_mode)

    def tearDown(self):
        """
        1. Restoring the system with turning on all the core's and smt on.
        """
        process.run('ppc64_cpu --cores-on=all', shell=True)
        process.run('ppc64_cpu --smt=on', shell=True)
