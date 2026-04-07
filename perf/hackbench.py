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
# Copyright: 2016 IBM
# Author: Praveen K Pandey <praveen@linux.vnet.ibm.com>
# Modified by: Samir A Mulani <samir@linux.vnet.ibm.com>
#

import os
from datetime import datetime
from avocado import Test
from avocado.utils import process, archive, build
from avocado.utils.software_manager.manager import SoftwareManager


class Hackbench(Test):

    """
    Hackbench is both a benchmark and a stress test for the Linux kernel
    scheduler.  It's  main  job  is  to create  a  specified  number  of
    pairs of schedulable entities (either threads or traditional processes)
    which communicate via either sockets or pipes and time how long it takes
    for each pair to send data  back and forth.
    """

    def setUp(self):
        '''
        Setting up the hackbench benchmark from the Linux Test Project (LTP).
        repo: https://github.com/linux-test-project/ltp/archive/master.zip

        This function downloads the LTP source as a ZIP archive, extracts it
        under the /tmp/ltp directory, and builds the hackbench binary
        located at: /tmp/ltp/ltp-master/testcases/kernel/sched/cfs-scheduler/
        After a successful build, the hackbench binary is ready to be used
        for benchmark runs.

        This setup is intended to prepare the environment before executing
        hackbench-based performance tests.
        '''
        sm = SoftwareManager()
        deps = ['gcc', 'make']
        for package in deps:
            if not sm.check_installed(package) and not sm.install(package):
                self.cancel("%s is needed for the test to be run" % package)

        url = self.params.get(
            'ltp_url', default='https://github.com/linux-test-project/ltp/archive/master.zip')  # noqa
        match = next((ext for ext in [".zip", ".tar"] if ext in url), None)
        tarball = ''
        if match:
            tarball = self.fetch_asset(
                "ltp-master%s" % match, locations=[url], expire='7d')
        else:
            self.cancel("Provided LTP Url is not valid")

        self.ltpdir = '/tmp/ltp'

        if not os.path.exists(self.ltpdir):
            os.mkdir(self.ltpdir)
        archive.extract(tarball, self.ltpdir)

        ltp_hackbench_dir = os.path.join(
            self.ltpdir, "ltp-master/testcases/kernel/sched/cfs-scheduler/")
        self.ltp_dir = os.path.join(self.ltpdir, "ltp-master")
        os.chdir(self.ltp_dir)
        build.make(self.ltp_dir, extra_args='autotools')
        process.run("./configure")

        os.chdir(ltp_hackbench_dir)
        build.make(ltp_hackbench_dir)

        self.workload_iteration = self.params.get("workload_iter",
                                                  default="10")
        self.data_op = self.params.get("data_op", default="")
        self.num_groups = self.params.get("num_groups", default="10")
        self.test_type = self.params.get("test_type", default="thread")
        self.loop = self.params.get("loops", default="100000")

    def parse_hackbench_data(self, file_path):
        """
        Parse hackbench output data to extract performance metrics.

        This function reads the benchmark output and computes the following:
        - min: Minimum time taken to run hackbench across all iterations
        - max: Maximum time taken to run hackbench across all iterations
        - avg: Average time across all iterations
        """
        hackbench_times = []
        with open(file_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line.startswith("Time:"):
                    try:
                        time_value = float(line.split("Time:")[1].strip())
                        hackbench_times.append(time_value)
                    except ValueError:
                        continue  # Skip malformed lines
        if not hackbench_times:
            print("No time values found.")
            return

        min_time = min(hackbench_times)
        max_time = max(hackbench_times)
        avg_time = sum(hackbench_times) / len(hackbench_times)

        self.log.info(f"Parsed {len(hackbench_times)} iterations.")
        self.log.info(f"Min Time: {min_time:.3f} sec")
        self.log.info(f"Max Time: {max_time:.3f} sec")
        self.log.info(f"Avg Time: {avg_time:.3f} sec")

    def test(self):
        """
        Run the hackbench benchmark with user-specified arguments and
        save logs.
        This function runs:
            hackbench [-pipe] <num_groups> [process|thread] [loops]
            Here where test_type is either [process|thread]
            -p, --pipe
              -> Sends the data via a pipe instead of the socket (default)

        It captures the output and stores timestamped logs under the test job
        directory (e.g., ./hackbench_logs) for performance analysis.

        Example:
        pipe=True num_groups=25, mode='thread', loops=100000)
        """
        hack_bench = self.logdir + "/hackbench_logs"
        os.makedirs(hack_bench, exist_ok=True)
        payload_file = os.path.join(hack_bench, "hackbench_payload.log")

        if self.data_op:
            cmd = "./hackbench -pipe " + self.num_groups + \
                " " + self.test_type + " " + self.loop
        else:
            cmd = "./hackbench " + self.num_groups + " " + self.test_type + \
                " " + self.loop

        for ite in range(1, int(self.workload_iteration) + 1):
            self.log.info(f"Running hackbench iteration {ite}...")

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_filename = f"hackbench_run_{ite}_{timestamp}.log"
            log_path = os.path.join(hack_bench, log_filename)
            # Run the command
            res = process.run(cmd, ignore_status=True, shell=True)
            data = res.stdout.decode().splitlines()
            # Write output to log file
            with open(payload_file, "a") as fd:
                fd.write("==================Iteration {}=============\
                        \n".format(str(ite)))
                for info in data:
                    fd.write(info)
                    fd.write("\n")

            with open(log_path, "w") as fd:
                for info in data:
                    fd.write(info)
                    fd.write("\n")

        self.parse_hackbench_data(payload_file)
