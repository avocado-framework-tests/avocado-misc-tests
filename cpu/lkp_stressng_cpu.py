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
# Copyright: 2026 Advanced Micro Devices, Inc.
# Author: Sumit Kumar <sumitkum@amd.com>

"""
Run the Intel LKP stress-ng CPU saturation microbenchmark under Avocado and
report how long it takes for the CPUs to reach a target busy percentage,
using the mpstat monitor samples collected during the run.
"""

import json
import os
import socket

import yaml

from autils.devel import lkp
from avocado import Test
from avocado.utils.software_manager.manager import SoftwareManager

# lkp's mpstat monitor aggregates utilisation across all CPUs under this key.
_IDLE_KEY = "mpstat.cpu.all.idle%"


class StressNgCpuLkp(Test):

    """
    Intel LKP stress-ng CPU saturation test.

    Run with a coherent job timeout, e.g.::

        avocado run --job-timeout=600 cpu/stress_ng_cpu.py

    :avocado: enable
    :avocado: tags=cpu,lkp,stress-ng,privileged
    """

    def setUp(self):
        smm = SoftwareManager()
        for package in ("make", "git", "gcc"):
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel("%s is required to build lkp-tests." % package)

        self.run_timeout = self.params.get("timeout", default=3600)
        self.saturation_pct = self.params.get("cpu_saturation_pct",
                                              default=95)
        self.max_seconds = self.params.get("cpu_saturation_max_seconds",
                                           default=0)
        self.install_extra = self.params.get("lkp_install_extra", default="")
        repo_url = self.params.get("lkp_repo_url")
        if not repo_url:
            self.cancel("lkp_repo_url must be set in the test parameters.")
        repo_branch = self.params.get("lkp_repo_branch", default="master")
        job = {
            "suite": self.params.get("suite", default="stress-ng"),
            "testcase": self.params.get("testcase", default="stress-ng"),
            "nr_threads": self.params.get("nr_threads", default="100%"),
            "testtime": self.params.get("testtime", default=60),
            "monitors": {
                "mpstat": {
                    "interval": self.params.get("mpstat_interval",
                                                default=1),
                },
            },
            "stress-ng": {
                "test": ["cpu"],
            },
        }
        self.job_yaml = os.path.join(self.workdir, "stress_ng_cpu_job.yaml")
        with open(self.job_yaml, "w", encoding="utf-8") as handle:
            yaml.safe_dump(job, handle, default_flow_style=False)

        self.lkp_dir = lkp.clone(
            repo_url, os.path.join(self.workdir, "lkp-tests"),
            branch=repo_branch)
        lkp.install(self.lkp_dir, extra=self.install_extra or None)

        self.testbox = socket.gethostname()

    def _saturation_seconds(self):
        mpstat = lkp.find_result_file(self.lkp_dir, "mpstat.json")
        if not mpstat:
            self.fail("No mpstat.json produced by the stress-ng run.")
        self.log.info("Reading mpstat data from %s", mpstat)
        with open(mpstat, "r", encoding="utf-8") as handle:
            data = json.load(handle)

        idle = data.get(_IDLE_KEY)
        if not idle:
            self.fail("'%s' series not found in %s" % (_IDLE_KEY, mpstat))

        for index, value in enumerate(idle):
            if (100.0 - float(value)) >= self.saturation_pct:
                return index + 1
        return None

    def test(self):
        subs = lkp.install_job(
            self.lkp_dir, self.job_yaml, self.testbox)
        for sub in subs:
            result = lkp.run_job(self.lkp_dir, sub, timeout=self.run_timeout)
            if result.exit_status != 0:
                lkp.archive_results(self.lkp_dir, "mpstat.json",
                                    os.path.join(self.outputdir, "lkp-results"))
                self.fail("lkp run failed for %s (exit %s)" %
                          (os.path.basename(sub), result.exit_status))

        lkp.archive_results(self.lkp_dir, "mpstat.json",
                            os.path.join(self.outputdir, "lkp-results"))
        seconds = self._saturation_seconds()
        if seconds is None:
            self.fail("CPUs never reached %s%% busy during the run." %
                      self.saturation_pct)
        self.log.info("cpu_saturation_seconds: %s", seconds)
        if self.max_seconds > 0 and seconds > self.max_seconds:
            self.fail("CPU saturation took %ss, exceeds limit %ss" %
                      (seconds, self.max_seconds))
