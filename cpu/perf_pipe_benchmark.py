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
from avocado.utils import process
from avocado.utils.software_manager.manager import SoftwareManager


class perf_sched_pip_workload(Test):
    def setUp(self):
        """
        Here in this test case  the command is running a scheduler benchmark
        using perf with the perf bench subcommand, specifically testing the
        scheduler's performance with a pipeline workload. The benchmark is
        repeated 5 times for accuracy, and the pipeline length is set to
        10,000,000 tasks. The perf stat command is used to collect performance
        statistics during the benchmarking process.
        """
        pkgs = []
        smm = SoftwareManager()
        pkgs.extend(["perf"])
        for pkg in pkgs:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel("Not able to install %s" % pkg)

    def run_workload(self, cmd):
        perf_stats_data = process.run(cmd)
        self.log.info("successfully run cmd: %s", cmd)
        return perf_stats_data

    def extract_data(self, payload_data):
        data = (payload_data.stderr)
        lines = data.decode("utf-8").split("\n")
        filtered_data = [line.strip() for line in lines if line.strip()]
        return filtered_data

    def test(self):
        """
        This command runs a performance measurement using the perf tool in
        Linux to benchmark the scheduler's performance under high
        contention for a piped communication scenario.
        """
        cmd = "perf stat -r 5 -a perf bench sched pipe -l 10000000"
        payload_data = self.run_workload(cmd)
        filtered_data = self.extract_data(payload_data)
        self.log.info("Perf stat data : \n%s", filtered_data[-1])

        cmd = "perf stat -n -r 5 perf bench sched pipe"
        payload_data = self.run_workload(cmd)
        filtered_data = self.extract_data(payload_data)
        self.log.info("Perf stat data: \n %s", filtered_data[-1])
