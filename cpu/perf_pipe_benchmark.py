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

from avocado import Test
from avocado.utils import process
from avocado.utils.software_manager.manager import SoftwareManager


class perf_sched_pip_workload(Test):

    def setUp(self):
        """
        In This test case command runs a scheduler benchmark using
        perf bench to test pipeline workload performance, repeating
        it 5 times for accuracy with 10,000,000 iterations.
        perf stat collects performance statistics during the benchmark.
        """
        pkgs = []
        smm = SoftwareManager()
        pkgs.extend(["perf"])
        for pkg in pkgs:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel(f"Not able to install {pkg}")

        self.stat_loop = self.params.get("stat_loop", default=5)
        self.load_iteration = self.params.get(
            "load_iteration", default=10000000)

    def run_workload(self, cmd):
        perf_stats_data = process.run(cmd)
        self.log.info(f"successfully run cmd: {cmd}")
        return perf_stats_data

    def extract_data(self, payload_data):
        data = (payload_data.stderr)
        lines = data.decode("utf-8").split("\n")
        filtered_data = [line.strip() for line in lines if line.strip()]
        return filtered_data

    def test(self):
        """
        In this function we are running the perf benchmark
        for scheduler pipeline.
        """
        cmd = "perf stat -r %s -a perf bench sched pipe \
                -l %s" % (self.stat_loop, self.load_iteration)
        payload_data = self.run_workload(cmd)
        filtered_data = self.extract_data(payload_data)
        self.log.info(f"Performance matrix : \n {filtered_data[-1]}")

        cmd = "perf stat -n -r %s perf bench sched pipe" % (self.stat_loop)
        payload_data = self.run_workload(cmd)
        filtered_data = self.extract_data(payload_data)
        self.log.info(f"Performance matrix: \n {filtered_data[-1]}")
