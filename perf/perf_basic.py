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
# Author: Nageswara R Sastry <rnsastry@linux.vnet.ibm.com>

import os
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils import distro
from avocado.utils.software_manager import SoftwareManager


class PerfBasic(Test):

    """
    Performance analysis tools for Linux
    :avocado: tags=privileged,perf

    execute basic perf testcases:
    - help
    - version
    - 'list' -> List all symbolic event types
    - 'record' -> Run a command and record its profile into perf.data
    - 'report' -> Read perf.data (created by perf record) and display the profile

    execute perf commands:
    - 'kallsyms' -> Searches running kernel for symbols
    - 'annotate' -> Read perf.data (created by perf record) and display annotated code
    - 'evlist' -> List the event names in a perf.data file
    - 'script' -> Read perf.data (created by perf record) and display trace output
    - 'stat' -> Run a command and gather performance counter statistics
    - 'bench' -> General framework for benchmark suites
    """

    fail_cmd = list()

    def run_cmd(self, cmd, verbose=True):
        self.log.info("executing ============== %s =================", cmd)
        if process.system(cmd, verbose=verbose, ignore_status=True, sudo=True, shell=True):
            self.fail("perf: failed to execute command %s" % cmd)

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
                self.cancel(
                    "Package %s is missing/could not be installed" % pkg)

    def test_perf_help(self):
        self.run_cmd("perf --help", False)

    def test_perf_version(self):
        self.run_cmd("perf --version", False)

    def test_perf_list(self):
        self.run_cmd("perf list", False)

    def test_perf_record(self):
        self.run_cmd("perf record -o perf.data -a sleep 5")
        if os.path.exists("perf.data"):
            if not os.stat("perf.data").st_size:
                self.fail("perf.data sample not captured")
            else:
                self.run_cmd("perf report --stdio")

    def test_perf_cmd_kallsyms(self):
        self.run_cmd("perf kallsyms __schedule")

    def test_perf_cmd_annotate(self):
        self.run_cmd("perf annotate --stdio")

    def test_perf_cmd_evlist(self):
        self.run_cmd("perf evlist -v")

    def test_perf_cmd_script(self):
        self.run_cmd("perf script")

    def test_perf_stat(self):
        self.run_cmd("perf stat -a sleep 5")

    def test_perf_bench(self):
        self.run_cmd("perf bench sched")

    def tearDown(self):
        self.variant = getattr(self.job.args, "avocado_variants", None)
        self.variant.parse(self.job.args)
        if self.name.uid == 10:
            self.run_cmd("rm -f perf.data")


if __name__ == "__main__":
    main()
