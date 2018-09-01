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
from avocado.utils import process
from avocado.utils import distro
from avocado.utils.software_manager import SoftwareManager


class Perf(Test):

    """
    Performance analysis tools for Linux
    :avocado: tags=privileged
    """

    fail_cmd = list()

    def run_cmd(self, cmd, verbose=True):
        self.log.info("executing ============== %s =================", cmd)
        if process.system(cmd, verbose=verbose, ignore_status=True, sudo=True, shell=True):
            self.is_fail += 1
            self.fail_cmd.append(cmd)

    @staticmethod
    def run_cmd_out(cmd):
        return process.system_output(cmd, shell=True,
                                     ignore_status=True, sudo=True)

    def setUp(self):
        smg = SoftwareManager()
        dist = distro.detect()
        if 'Ubuntu' in dist.name:
            linux_tools = "linux-tools-" + os.uname()[2]
            pkgs = ['linux-tools-common', linux_tools]
        elif dist.name in ['centos', 'fedora', 'rhel', 'SuSE']:
            pkgs = ['perf']
        else:
            self.cancel("perf is not supported on %s" % dist.name)

        for pkg in pkgs:
            if not smg.check_installed(pkg) and not smg.install(pkg):
                self.cancel("Package %s is missing/could not be installed" % pkg)

    def test_perf_short(self):
        """
        execute basic perf testcases:
        - help
        - version
        - 'list' -> List all symbolic event types
        - 'record' -> Run a command and record its profile into perf.data
        - 'report' -> Read perf.data (created by perf record) and display the profile
        """
        self.log.info("===============Executing perf test (short)===="
                      "===========")
        self.is_fail = 0
        self.run_cmd("perf --help", False)
        self.run_cmd("perf --version", False)
        self.run_cmd("perf list", False)
        self.run_cmd("perf record -o perf.data -a sleep 5")
        if os.path.exists("perf.data"):
            if not os.stat("perf.data").st_size:
                self.is_fail += 1
                self.log.info("perf.data sample not captured")
            else:
                self.run_cmd("perf report --stdio")

        if self.is_fail >= 1:
            self.fail("%s command(s) failed to execute  "
                      % self.fail_cmd)

    def test_perf_test(self):
        """
        execute inbuilt test
        """
        self.log.info("===============Executing perf test (builtin tests)===="
                      "===========")
        self.is_fail = 0
        for testcase in self.run_cmd_out("perf test 2>& 1|grep -ie failed -ie skip").splitlines():
            if "failed" in testcase.lower():
                self.is_fail += 1
            elif "not compiled in" in testcase.lower():
                self.is_fail += 1
        if self.is_fail >= 1:
            self.fail("%s command(s) failed to execute  " % self.fail_cmd)

    def test_perf_cmds(self):
        """
        execute perf commands:
        - 'kallsyms' -> Searches running kernel for symbols
        - 'annotate' -> Read perf.data (created by perf record) and display annotated code
        - 'evlist' -> List the event names in a perf.data file
        - 'script' -> Read perf.data (created by perf record) and display trace output
        - 'stat' -> Run a command and gather performance counter statistics
        - 'bench' -> General framework for benchmark suites
        """
        self.is_fail = 0
        self.run_cmd("perf kallsyms __schedule")
        subcmds = ["perf annotate --stdio", "perf evlist -v", "perf script"]
        if os.path.exists("perf.data"):
            for subcmd in subcmds:
                self.run_cmd(subcmd)
            os.remove("perf.data")
        else:
            self.is_fail += 1
            for subcmd in subcmds:
                self.fail_cmd.append(subcmd)

        self.run_cmd("perf stat -a sleep 5")
        self.run_cmd("perf bench sched")
        if self.is_fail >= 1:
            self.fail("%s command(s) failed to execute  " % self.fail_cmd)


if __name__ == "__main__":
    main()
