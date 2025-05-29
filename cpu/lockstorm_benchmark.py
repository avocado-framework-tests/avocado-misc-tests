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
from avocado import Test
from avocado.utils import process, distro
from avocado.utils import build, distro, git, dmesg
from avocado.utils.software_manager.manager import SoftwareManager


class lockstorm_benchmark(Test):
    def setUp(self):
        """
        This test case basically generate the performance stats
        for kernel spinlock.
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
        self.test_iter = self.params.get("test_iter", default=5)

        url = "https://github.com/npiggin/lockstorm.git"
        git.get_repo(url, branch='master', destination_dir=self.workdir)
        os.chdir(self.workdir)
        build.make(self.workdir)
        if not os.path.isfile("lockstorm.ko"):
            self.cancel("Module build failed. Please check the build log")

    def capture_dmesg_dump(self, smt_state):
        """
        This function capture the spinlock performance stats from dmesg.

        :param smt_state: Here we are passing the smt state that we are
        going to change.
        """
        cmd = "dmesg | grep 'lockstorm: spinlock iterations'"
        self.log.info(f"=================Dump data for \
                SMT Mode: {smt_state} benchmark======================\n\n")
        dump_data = process.run(cmd, shell=True)
        return dump_data

    def test(self):
        """
        In this function basically we are changing the SMT states
        and running the lockstorm benchmark.
        1.changing the SMT modes.
        2.Running the lockstorm benchmark.
        3. Capturing the benchmark stats.
        """
        lockstorm_dir = self.logdir + "/lockstorm_benc"
        os.makedirs(lockstorm_dir, exist_ok=True)
        process.run('ppc64_cpu --cores-on=all', shell=True)
        process.run('ppc64_cpu --smt=on', shell=True)
        cpu_controller = ["2", "4", "6", "on", "off"]
        for test_run in range(self.test_iter):
            self.log.info("Test iteration %s " % (test_run))
            for smt_mode in cpu_controller:
                cmd = "ppc64_cpu --smt={}".format(smt_mode)
                self.log.info(f"=======smt mode {smt_mode}=======")
                process.run(cmd, shell=True)
                cmd = "insmod ./lockstorm.ko" + " cpulist=%s" % \
                    (self.cpu_list)
                dmesg.clear_dmesg()
                if self.cpu_list == 0:
                    cmd = "insmod ./lockstorm.ko"
                result = process.run(cmd, ignore_status=True, shell=False,
                                     sudo=True)
                if 'Key was rejected by service' in result.stderr.decode():
                    self.cancel("Inserting module was rejected by kernel.")
                lockstorm_data = self.capture_dmesg_dump(smt_mode)
                stdout_output = lockstorm_data.stdout
                lockstorm_log = lockstorm_dir + "/lockstorm.log"
                with open(lockstorm_log, "a") as payload:
                    payload.write(
                        "==================Iteration {}=============\
                                    \n".format(str(test_run)))
                    payload.write("============SMT mode: {}============= \
                            \n".format(smt_mode))
                    lines = stdout_output.splitlines()
                    for line in lines:
                        decoded_string = line.decode('utf-8')
                        cleaned_string = decoded_string.lstrip('\t')
                        payload.write(cleaned_string + '\n')
                    payload.write("\n")

    def tearDown(self):
        """
        1. Restoring the system with turning on all the core's and smt on.
        """
        process.run('ppc64_cpu --cores-on=all', shell=True)
        process.run('ppc64_cpu --smt=on', shell=True)
