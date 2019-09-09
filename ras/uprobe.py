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
from avocado import main
from avocado.utils import genio
from avocado.utils import distro
from avocado.utils import process
from avocado.utils.software_manager import SoftwareManager


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
        return process.system_output(cmd, shell=True, ignore_status=True,
                                     sudo=True).decode("utf-8")

    def clear_trace(self):
        self.debugfs = "/sys/kernel/debug/tracing/"
        self.tracefs = os.path.join(self.debugfs, "trace")
        self.uprobes_enable_fs = os.path.join(self.debugfs, "events/uprobes/enable")
        self.uprobes_event_fs = os.path.join(self.debugfs, "events/uprobes/u_malloc/enable")
        self.uprobes_events_fs = os.path.join(self.debugfs, "uprobe_events")
        genio.write_one_line(self.tracefs, "")
        genio.write_one_line(self.uprobes_events_fs, "")

    def enable_uprobes(self):
        genio.write_one_line(self.uprobes_enable_fs, "1")
        genio.write_one_line(self.uprobes_event_fs, "1")

    def disable_uprobes(self):
        genio.write_one_line(self.uprobes_event_fs, "0")
        genio.write_one_line(self.uprobes_enable_fs, "0")

    def setUp(self):
        dist = distro.detect()
        smg = SoftwareManager()
        if dist.name == "Ubuntu" or dist.name == "unknown":
            deps = ['libc-bin']
        else:
            deps = ['glibc-common']
        for package in deps:
            if not smg.check_installed(package) and not smg.install(package):
                self.cancel('%s is needed for the test to be run' % package)

    def execute_test(self):
        self.log.info("============== Testing uprobes =================")
        self.is_fail = 0
        self.clear_trace()

        libc_path = self.run_cmd_out("ldd /bin/bash|grep -i libc").split(" ")[2]
        libc_addr = self.run_cmd_out("objdump -T %s | grep -w malloc" % libc_path).split(" ")[0]
        uprobes_cmd = "echo 'p:u_malloc %s:0x%s' > %s" % (libc_path, libc_addr, self.uprobes_events_fs)
        self.run_cmd(uprobes_cmd)
        if self.is_fail:
            self.fail("Cannot plant a uprobes with %s", uprobes_cmd)

        self.enable_uprobes()
        self.run_cmd("date")
        self.run_cmd("ls")
        if "u_malloc" not in self.run_cmd_out("cat /sys/kernel/debug/tracing/trace"):
            self.fail("Uprobe probe was not hit.")
        self.disable_uprobes()
        self.clear_trace()

    def test(self):
        self.execute_test()


if __name__ == "__main__":
    main()
