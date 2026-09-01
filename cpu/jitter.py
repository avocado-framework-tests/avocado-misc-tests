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
Run the Intel LKP "jitter" PMA instruction-jitter microbenchmark under
Avocado and assert on the maximum instruction jitter (in cycles).
"""

import json
import os
import socket

import yaml

from autils.devel import lkp
from avocado import Test
from avocado.utils.software_manager.manager import SoftwareManager

# lkp's jitter parser emits the worst-case (99th percentile) instruction jitter
# under this key; it is the "maximum" jitter metric of interest.
_STAT_KEY = "jitter.Instantaneous_jitter_99th_percentile"


class Jitter(Test):

    """
    Intel LKP instruction jitter test.

    :avocado: enable
    :avocado: tags=cpu,lkp,jitter,privileged
    """

    def setUp(self):
        smm = SoftwareManager()
        for package in ("make", "git", "gcc"):
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel("%s is required to build lkp-tests." % package)

        self.run_timeout = self.params.get("timeout", default=3600)
        self.threshold = self.params.get("jitter_threshold_cycles", default=0)
        self.install_extra = self.params.get("lkp_install_extra", default="")
        repo_url = self.params.get("lkp_repo_url")
        if not repo_url:
            self.cancel("lkp_repo_url must be set in the test parameters.")
        repo_branch = self.params.get("lkp_repo_branch", default="master")
        job = {
            "suite": self.params.get("suite", default="jitter"),
            "testcase": self.params.get("testcase", default="jitter"),
            "jitter": {
                "core_id": self.params.get("core_id", default=2),
                "rate": self.params.get("rate", default=1000),
                "loops": self.params.get("loops", default=10000),
                "samples": self.params.get("samples", default=20),
            },
        }
        self.job_yaml = os.path.join(self.workdir, "jitter_job.yaml")
        with open(self.job_yaml, "w", encoding="utf-8") as handle:
            yaml.safe_dump(job, handle, default_flow_style=False)

        self.lkp_dir = lkp.clone(
            repo_url, os.path.join(self.workdir, "lkp-tests"),
            branch=repo_branch)
        lkp.install(self.lkp_dir, extra=self.install_extra or None)

        self.testbox = socket.gethostname()

    def _read_max_jitter(self):
        stats = lkp.find_result_file(self.lkp_dir, "stats.json")
        if not stats:
            self.fail("No stats.json produced by the jitter run.")
        self.log.info("Reading jitter stats from %s", stats)
        with open(stats, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        value = data.get(_STAT_KEY)
        if value is None:
            self.fail("'%s' not found in %s" % (_STAT_KEY, stats))
        return float(value)

    def test(self):
        subs = lkp.install_job(
            self.lkp_dir, self.job_yaml, self.testbox)
        for sub in subs:
            result = lkp.run_job(self.lkp_dir, sub, timeout=self.run_timeout)
            if result.exit_status != 0:
                lkp.archive_results(self.lkp_dir, "stats.json",
                                    os.path.join(self.outputdir, "lkp-results"))
                self.fail("lkp run failed for %s (exit %s)" %
                          (os.path.basename(sub), result.exit_status))

        lkp.archive_results(self.lkp_dir, "stats.json",
                            os.path.join(self.outputdir, "lkp-results"))
        max_jitter = self._read_max_jitter()
        self.log.info("Maximum instruction jitter: %s cycles", max_jitter)
        if self.threshold > 0 and max_jitter > self.threshold:
            self.fail("Instruction jitter %s cycles exceeds threshold %s" %
                      (max_jitter, self.threshold))
