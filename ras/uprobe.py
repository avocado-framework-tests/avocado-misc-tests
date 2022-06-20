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
from avocado import Test
from avocado.utils import genio
from avocado.utils import distro
from avocado.utils import process
from avocado.utils.software_manager.manager import SoftwareManager


class Uprobe(Test):

    """
    Test kernel uprobes
    :avocado: tags=privileged
    """
    def run_cmd(self, cmd):
        self.log.info("executing ============== %s =================", cmd)
        if process.system(cmd, ignore_status=True, sudo=True, shell=True):
            self.is_fail += 1
        return

    @staticmethod
    def run_cmd_out(cmd):
        """
        Run the linux terminal command
        Ex: cat, ldd ..etc.
        """
        return process.system_output(cmd,
                                     shell=True, ignore_status=True,
                                     sudo=True).decode("utf-8")

    def clear_trace(self):
        """
        Clear the tracepoint and uprobe events
        before enable and disable the probe.
        """
        try:
            self.debugfs = "/sys/kernel/debug/tracing/"
            self.tracefs = os.path.join(self.debugfs, "trace")
            uprobes_en = "events/uprobes/enable"
            self.uprobes_enable_fs = os.path.join(self.debugfs, uprobes_en)
            uprobes_umall = "events/uprobes/u_malloc/enable"
            self.uprobes_event_fs = os.path.join(self.debugfs, uprobes_umall)
            uprobe_eve = "uprobe_events"
            self.uprobes_events_fs = os.path.join(self.debugfs, uprobe_eve)
            genio.write_one_line(self.tracefs, "")
            genio.write_one_line(self.uprobes_events_fs, "")
        except IOError:
            self.cancel("There is issue with kernel system resources")

    def ena_dis_uprobes(self, prob_value):
        """
        Enable and Disable the uprobes.
        Enable_uprobes:
        prob_value = 1

        Disable_uprobes:
        prob_value = 0
        """
        try:
            genio.write_one_line(self.uprobes_enable_fs, prob_value)
            genio.write_one_line(self.uprobes_event_fs, prob_value)
        except IOError:
            self.cancel("There is issue with kernel system resources")

    def setUp(self):
        """
        Setup the system for test.
        """
        self.enable_prob = "1"
        self.disable_prob = "0"
        dist = distro.detect()
        smg = SoftwareManager()
        if dist.name in ["Ubuntu", "unknown", 'debian']:
            deps = ['libc-bin']
        elif 'SuSE' in dist.name:
            deps = ['glibc-devel']
        else:
            deps = ['glibc-common']
        for package in deps:
            if not smg.check_installed(package) and not smg.install(package):
                self.cancel('%s is needed for the test to be run' % package)

    def execute_test(self):
        """
        -> This function is responsible to insert tracepoints in the kernel.
        -> It will enable and disable the uprobes.
        """
        self.log.info("============== Testing uprobes =================")
        self.is_fail = 0
        self.clear_trace()
        libcpath_cmd = "ldd /bin/bash|grep -i libc"
        libc_path = self.run_cmd_out(libcpath_cmd).split(" ")[2]
        libcaddr_cmd = "objdump -T %s | grep -w malloc"
        libc_addr = self.run_cmd_out(libcaddr_cmd % libc_path).split(" ")[0]
        uprobes = "echo 'p:u_malloc %s:0x%s' > %s"
        uprobes_cmd = uprobes % (libc_path, libc_addr, self.uprobes_events_fs)
        self.run_cmd(uprobes_cmd)
        if self.is_fail:
            self.fail("Cannot plant a uprobes with %s", uprobes_cmd)

        self.ena_dis_uprobes(self.enable_prob)
        cmd_list = ["date", "ls"]
        for cmd in cmd_list:
            self.run_cmd(cmd)
        cmd_trace = "cat /sys/kernel/debug/tracing/trace"
        if "u_malloc" not in (self.run_cmd_out(cmd_trace)):
            self.fail("Uprobe probe was not hit.")
        self.ena_dis_uprobes(self.disable_prob)
        self.clear_trace()

    def test(self):
        self.execute_test()
