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
#
# Copyright: 2024 IBM
# Author: Disha Goel <disgoel@linux.ibm.com>

import os
import platform
import json
import shutil
from avocado import Test
from avocado.utils import cpu, distro, dmesg, process
from avocado.utils.software_manager.manager import SoftwareManager


class perf_json(Test):

    """
    This tests all pmu events
    :avocado: tags=perf,json,events
    """
    testdir = 'tools/perf/pmu-events/arch/powerpc/'

    # Initializing fail command list
    fail_cmd = list()

    def setUp(self):
        """
        Setup checks:
        0. Processor should be ppc64.
        1. Install perf package
        2. Install and build kernel source
        3. Collect all the pmu events from perf list
        4. Run all the pmu events using perf stat
        5. Collect all the events and event code from json files
        6. Compare both the events list and event code
        """
        smm = SoftwareManager()

        detected_distro = distro.detect()
        if 'ppc64' not in detected_distro.arch:
            self.cancel("Processor is not PowerPC")

        # make sure kernel source repo is configured
        deps = ['gcc', 'make', 'perf']
        if 'Ubuntu' in detected_distro.name:
            deps.extend(['linux-tools-common', 'linux-tools-%s'
                         % platform.uname()[2]])
            self.buldir = smm.get_source('linux', self.workdir)
        elif detected_distro.name in ['rhel', 'fedora', 'centos']:
            self.buldir = smm.get_source('kernel', self.workdir)
            self.buldir = os.path.join(self.buldir, os.listdir(self.buldir)[0])
        elif 'SuSE' in detected_distro.name:
            if not smm.check_installed("kernel-source") and not smm.install("kernel-source"):
                self.cancel("Failed to install kernel-source for this test")
            if not os.path.exists("/usr/src/linux"):
                self.cancel("kernel source missing after install")
            self.buldir = "/usr/src/linux"
        else:
            self.cancel("Install the package for perf supported by %s"
                        % detected_distro.name)
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

        self.rev = cpu.get_revision()
        rev_to_power = {'004b': 'power8', '004e': 'power9', '0080': 'power10'}
        if self.rev in rev_to_power:
            self.testdir += rev_to_power[self.rev] + '/'
        self.sourcedir = os.path.join(self.buldir, self.testdir)

        # Collect all pmu events from perf list and json files
        self.perf_list_pmu_events = set()
        self.json_pmu_events = set()
        self.json_event_info = {}

        output = process.system_output("perf list --raw-dump pmu", shell=True)
        for ln in output.decode().split():
            if ln.startswith('pm_') and ln not in ("hv_24x7" or "hv_gpci"):
                self.perf_list_pmu_events.add(ln)

        # Clear the dmesg to capture the delta at the end of the test.
        dmesg.clear_dmesg()

    def test_pmu_events(self):
        # run all pmu events with perf stat
        for event in self.perf_list_pmu_events:
            cmd = "perf stat -e %s -I 1000 sleep 1" % event
            res = process.run(cmd, shell=True, verbose=True)
            if (b"not counted" in res.stderr) or (b"not supported" in res.stderr):
                self.fail_cmd.append(cmd)
        if self.fail_cmd:
            self.fail("perf pmu events failed are %s" % self.fail_cmd)

    def test_compare(self):
        # collect events from json files and compare with perf list
        for file_name in [file for file in os.listdir(self.sourcedir) if file.endswith('.json')]:
            with open(self.sourcedir + file_name) as json_file:
                data1 = json.load(json_file)
                for i in data1:
                    if "EventName" and "EventCode" in i:
                        event_name = i["EventName"].lower()
                        event_code = i["EventCode"]
                        self.json_pmu_events.add(event_name)
                        self.json_event_info[event_name] = event_code
        if self.perf_list_pmu_events != self.json_pmu_events:
            self.fail("mismatch in event list between perf list and json files")

        # compare event code from perf and json files
        for event in self.perf_list_pmu_events:
            perf_event_code = self._get_perf_event_code(event)
            json_event_code = self.json_event_info.get(event, None)
            self.log.info(
                f"Event code for event {event}: Perf code={perf_event_code}, JSON code={json_event_code}")
            if json_event_code is not None and perf_event_code.lower() != json_event_code.lower():
                self.log.info("event code did not matched, checking decimal value")
                perf_decimal_integer = int(perf_event_code, 16)
                json_decimal_integer = int(json_event_code, 16)
                self.log.info(
                    f"Decimal code for event {event}: Perf decimal value={perf_decimal_integer}, JSON decimal value={json_decimal_integer}")
                if perf_decimal_integer != json_decimal_integer:
                    self.fail(
                        f"Mismatch in event code for event {event} Perf code={perf_event_code}, JSON code={json_event_code}")

    def _get_perf_event_code(self, event):
        # Helper function to get event code from perf stat command
        cmd = "perf stat -vv -e %s sleep 1" % event
        output = process.run(cmd, shell=True)
        res = output.stdout.decode() + output.stderr.decode()
        for ln in res.split('\n'):
            if 'config' in ln:
                parts = ln.split()
                config_index = parts.index('config')
                if config_index + 1 < len(parts):
                    return parts[config_index + 1]
        return None

    def tearDown(self):
        if os.path.exists(self.workdir):
            shutil.rmtree(self.workdir)
        # Collect the dmesg
        dmesg.collect_dmesg()
