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
# Copyright: 2021 IBM
# Author: Nageswara R Sastry <rnsastry@linux.ibm.com>

import platform
from avocado import Test
from avocado.utils import distro, dmesg, genio, process
from avocado.utils.software_manager.manager import SoftwareManager

IS_POWER_NV = 'PowerNV' in genio.read_file('/proc/cpuinfo').rstrip('\t\r\n\0')


class perf_metric(Test):

    """
    This tests all metric/metric group events
    :avocado: tags=perf,metric,events
    """
    # Initializing fail command list
    fail_cmd = list()

    def _create_all_metric_events(self, match):
        cmd = "perf list %s" % match
        output = process.system_output(cmd, shell=True, ignore_status=True)
        for ln in output.decode().splitlines():
            ln = ln.strip()
            # Skipping empty line, header and comment
            if not ln or "List of pre-defined events" in ln or "[" in ln or\
               "Metrics:" in ln or "Metric Groups:" in ln:
                continue
            else:
                self.list_of_metric_events.append(ln)

    def setUp(self):
        """
        Setup checks :
        0. Processor should be ppc64.
        1. Install perf package
        2. Check for metric/metric group
        3. When found metric/metric group run all the events
        """
        smm = SoftwareManager()

        detected_distro = distro.detect()
        if 'ppc64' not in detected_distro.arch:
            self.cancel("Processor is not PowerPC")

        deps = ['gcc', 'make']
        if 'Ubuntu' in detected_distro.name:
            deps.extend(['linux-tools-common', 'linux-tools-%s'
                         % platform.uname()[2]])
        elif detected_distro.name in ['rhel', 'SuSE', 'fedora', 'centos']:
            deps.extend(['perf', 'numactl'])
        else:
            self.cancel("Install the package for perf supported by %s"
                        % detected_distro.name)
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

        # Collect all metric events and metric group events
        self.list_of_metric_events = []
        self._create_all_metric_events('metric')
        self._create_all_metric_events('metricgroup')
        if not self.list_of_metric_events:
            self.cancel("perf tool Metric events not found.")

        # Clear the dmesg to capture the delta at the end of the test.
        dmesg.clear_dmesg()

    def _run_cmd(self, option):
        for line in self.list_of_metric_events:
            cmd = "perf stat %s %s sleep 1" % (option, line)
            rc, output = process.getstatusoutput(cmd, ignore_status=True,
                                                 shell=True, verbose=True,
                                                 allow_output_check='combined')
            # When the command failed, checking for expected failure or not.
            if rc:
                found_imc = False
                found_hv_24_7 = False
                for ln in output.splitlines():
                    if "hv_24x7" in ln:
                        found_hv_24_7 = True
                        break
                    if "imc" in ln:
                        found_imc = True
                        break
                # IMC errors in PowerVM - Expected
                # hv_24x7 errors in PowerNV - Expected
                # IMC failed in PowerNV environment - Fail
                # HV_24X7 failed in PowerVM environment - Fail
                if (found_imc and not IS_POWER_NV) or\
                   (found_hv_24_7 and IS_POWER_NV):
                    self.log.info("%s failed, due to non supporting"
                                  " environment" % cmd)
                else:
                    self.fail_cmd.append(cmd)
        if self.fail_cmd:
            self.fail("perf_metric: commands failed are %s" % self.fail_cmd)

    def test_all_metric_events_with_M(self):
        self._run_cmd("-M")

    def test_all_metric_events_with_metric(self):
        self._run_cmd("--metric-only -M")

    def tearDown(self):
        # Collect the dmesg
        dmesg.collect_dmesg()
