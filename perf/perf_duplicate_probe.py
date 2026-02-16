#!/usr/bin/env python
#
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
# Copyright: 2019 IBM
# Author: Shirisha G <shiganta@in.ibm.com>

import os
from avocado import Test
from avocado.utils import process, genio
from avocado.utils.software_manager.distro_packages import ensure_tool


class PerfDuplicateProbe(Test):

    def setUp(self):
        '''
        Install the basic packages to support perf and systemtap-sdt-devel
        '''
        # Check for basic utilities
        perf_path = self.params.get('perf_bin', default='')
        distro_pkg_map = {
            "Ubuntu": [f"linux-tools-{os.uname()[2]}", "linux-tools-common", "gcc", "make"],
            "debian": ["linux-perf"],
            "centos": ["perf"],
            "fedora": ["perf"],
            "rhel": ["perf"],
            "SuSE": ["perf"],
        }
        try:
            perf_version = ensure_tool("perf", custom_path=perf_path, distro_pkg_map=distro_pkg_map)
            self.log.info(f"Perf version: {perf_version}")
            self.perf_bin = perf_path if perf_path else "perf"
        except RuntimeError as e:
            self.cancel(str(e))
        self.fail_flag = False

    def _check_duplicate_probe(self, outpt):
        if 'select_task_rq_fair' in outpt and 'select_task_rq_fair_' in outpt:
            self.fail_flag = True

    def test_duplicate_probe(self):
        outpt = process.run("perf probe select_task_rq_fair:0", sudo=True)
        outpt = outpt.stderr.decode("utf-8")
        self._check_duplicate_probe(outpt)
        outpt = genio.read_all_lines("/sys/kernel/debug/tracing/kprobe_events")
        self._check_duplicate_probe(outpt)
        if self.fail_flag:
            self.fail("perf is placing multiple probes at the same location ")

    def tearDown(self):
        # Check for active probes
        if process.run("perf probe --list", sudo=True).stdout:
            # Deleting all the probed events
            process.run('perf probe -d \\*')
