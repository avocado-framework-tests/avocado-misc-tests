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
from avocado.utils import cpu, distro, dmesg, process, archive
from avocado.utils.software_manager.manager import SoftwareManager

# Global variable to track whether the kernel has been built
kernel_built = False


class perf_json(Test):

    """
    This tests all pmu events
    :source: https://github.com/torvalds/linux/archive/master.zip
    :avocado: tags=perf,json,events,kernel
    """
    testdir = 'tools/perf/pmu-events/arch/powerpc/'

    # Initializing fail command list
    fail_cmd = list()

    def _obtain_kernel_source(self, smm, detected_distro):
        # Obtain the kernel source directory based on the detected distribution
        if 'Ubuntu' in detected_distro.name:
            return smm.get_source('linux', self.workdir)
        if detected_distro.name in ['rhel', 'fedora', 'centos']:
            buldir = smm.get_source('kernel', self.workdir)
            return os.path.join(buldir, os.listdir(buldir)[0])
        elif 'SuSE' in detected_distro.name:
            if not smm.check_installed("kernel-source") and not smm.install("kernel-source"):
                self.cancel("Failed to install kernel-source for this test")
            if not os.path.exists("/usr/src/linux"):
                self.cancel("kernel source missing after install")
            return "/usr/src/linux"

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
        super().setUp()
        global kernel_built

        run_type = self.params.get('type', default='distro')
        smm = SoftwareManager()
        detected_distro = distro.detect()
        if 'ppc64' not in detected_distro.arch:
            self.cancel("Processor is not PowerPC")

        deps = ['gcc', 'make', 'perf']
        if 'Ubuntu' in detected_distro.name:
            deps.extend(['linux-tools-common', 'linux-tools-%s'
                         % platform.uname()[2]])
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

        # make sure kernel source repo is configured
        if run_type == 'distro' and not kernel_built:
            self.buldir = self._obtain_kernel_source(smm, detected_distro)
            kernel_built = True
        else:
            # Build kernel using upstream source code
            url = 'https://github.com/torvalds/linux/archive/master.zip'
            self.location = self.params.get('location', default=url)
            self.tarball = self.fetch_asset("master.zip", locations=[self.location], expire='1d')
            archive.extract(self.tarball, self.workdir)
            self.buldir = os.path.join(self.workdir, 'linux-master')
            self.sourcedir = self.buldir + '/tools/perf'
            process.system("make headers -C %s" % self.buldir, shell=True, sudo=True)
            process.system("make prefix=/usr/local install -C %s" % self.sourcedir, shell=True, sudo=True)

        self.rev = cpu.get_revision()
        rev_to_power = {'004b': 'power8', '004e': 'power9', '0080': 'power10', '0082': 'power10'}
        if self.rev in rev_to_power:
            self.testdir += '%s/' % rev_to_power[self.rev]
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
                json_data = json.load(json_file)
                for line in json_data:
                    if "EventName" and "EventCode" in line:
                        event_name = line["EventName"].lower()
                        event_code = line["EventCode"]
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
        if os.path.exists('/usr/local/bin/perf'):
            os.remove('/usr/local/bin/perf')
        # Collect the dmesg
        dmesg.collect_dmesg()
