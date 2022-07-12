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
# Copyright: 2021 IBM.
# Author: Nageswara R Sastry <rnsastry@linux.ibm.com>

import os
import re
import platform
from avocado import Test
from avocado.utils import cpu, dmesg, distro, genio, linux_modules, process
from avocado.utils.software_manager.manager import SoftwareManager


class perfNMEM(Test):
    """
    Testing perf nmem PMU
    :avocado: tags=privileged,perf,pmu

    1. Check for nmem PMUs in sysfs
    2. Check for CONFIG_PAPR_SCM kernel configuration
    3. Check for nmem PMU register messages in dmesg
    4. Check PMUs found in sysfs and dmesg are matching
    5. Count the number of PMU events
    6. Run all events one by one per PMU
    7. Run events by grouping per PMU
    8. Run mixed PMU events - negative test case
    9. Check PMU cpumask exists or not
    10. Check cpumask is same for all the PMUs or not
    11. Check cpumask by on and off cpu
    """

    def setUp(self):
        # Check the required kernel config parameter set or not.
        cfg_param = "CONFIG_PAPR_SCM"
        ret = linux_modules.check_kernel_config(cfg_param)
        if ret == linux_modules.ModuleConfig.NOT_SET:
            self.cancel("%s not set." % cfg_param)
        else:
            self.log.info("%s set." % cfg_param)
        # Install required packages
        smm = SoftwareManager()
        detected_distro = distro.detect()
        if 'ppc64' not in detected_distro.arch:
            self.cancel("Processor is not PowerPC")
        deps = ['gcc', 'make']
        if 'Ubuntu' in detected_distro.name:
            deps.extend(['linux-tools-common', 'linux-tools-%s'
                         % platform.uname()[2]])
        elif detected_distro.name in ['rhel', 'SuSE', 'fedora', 'centos']:
            deps.extend(['perf'])
        else:
            self.cancel("Install the package for perf supported by %s"
                        % detected_distro.name)
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        # Set required variables
        self.base_dir = "/sys/devices/"
        self.pmu_list = []
        self.all_events = {}
        # Collect the PMU names from sysfs dir.
        for files in os.listdir(self.base_dir):
            if "nmem" in files:
                self.pmu_list.append(files)
        if self.pmu_list:
            self.log.info("Found PMUs: %s" % self.pmu_list)
        else:
            # If PMUs not found then cancel the test run
            self.cancel("nmem PMUs not found")
        # Once the PMUs are there, collect the list of events
        output = process.system_output('perf list nmem', shell=True,
                                       ignore_status=True)
        for ln in output.decode().splitlines():
            ln = ln.strip()
            # Skip empty line and header
            if not ln or "List of pre-defined events" in ln:
                continue
            else:
                ln = ln.split('[')[0].strip()
                for pmu in self.pmu_list:
                    if ln.split('/')[0] in pmu:
                        # Collecting the events per PMU
                        # ex:{nmem0: [ev1, ev2, ...], nmem1: [ev1, ev2, ...]}
                        self.all_events.setdefault(pmu, []).append(ln)
        if not self.all_events:
            self.cancel("Can not extract events from 'perf list nmem'")

    def test_pmu_register_dmesg(self):
        # This function tests whether performance monitor hardware support
        # registered or not. If not found any registered messages in dmesg
        # output this test will fail.
        output = dmesg.collect_errors_dmesg('NVDIMM performance monitor support registered')
        if not output:
            self.fail("NVDIMM PMUs not found in dmesg.")
        else:
            for line in output:
                # Looking for
                #nvdimm_pmu: nmem0 NVDIMM performance monitor support registered
                matchFound = re.search(r"nvdimm_pmu: (.*) NVDIMM", line)
                if matchFound:
                    pmu = matchFound.group(1)
                    if pmu not in self.pmu_list:
                        self.pmu_list.append(pmu)
            if self.pmu_list:
                self.log.info("Found PMUs: %s" % self.pmu_list)
            else:
                self.fail("dmesg: nmem PMUs not found")

    def test_sysfs(self):
        # Check registered PMUs created the sysfs directory
        not_found_list = []
        for files in self.pmu_list:
            if files not in os.listdir(self.base_dir):
                not_found_list.append(files)
        if not_found_list:
            self.fail('Not found PMU sysfs directories: %s' % not_found_list)
        else:
            self.log.info("Found PMU sysfs files list: %s" % self.pmu_list)

    def test_pmu_count(self):
        for pmu in self.pmu_list:
            # From the sysfs directory of the PMU counting number of events
            event_dir = os.path.join(self.base_dir, pmu, 'events')
            if not os.path.isdir(event_dir):
                self.fail("sysfs %s folder not found" % pmu)
            sys_fs_events = len(os.listdir(event_dir))
            if sys_fs_events < 1:
                # Fails if there are no event files exists
                self.fail("%s events not found" % pmu)
            self.log.info("%s events count = %s" % (pmu, sys_fs_events))

    def test_all_events(self):
        failed_event_list = []
        # For each pmu available, run events one by one
        for pmu in self.pmu_list:
            for event in self.all_events[pmu]:
                rc, op = process.getstatusoutput('perf stat -e %s sleep 1'
                                                 % event, shell=True,
                                                 ignore_status=True,
                                                 verbose=True)
                if rc:
                    failed_event_list.append(event)
        if failed_event_list:
            self.fail("Failed events are: %s" % failed_event_list)

    def test_all_group_events(self):
        failed_events = []
        # Run group of events based on PMU
        for key in self.all_events.keys():
            rc, op = process.getstatusoutput("perf stat -e '{%s}' sleep 1" %
                                             ','.join(self.all_events[key]),
                                             shell=True, verbose=True,
                                             ignore_status=True)
            if rc:
                failed_events.append(self.all_events[key])
        if failed_events:
            self.fail("Failed with events: %s " % failed_events)

    def test_mixed_events(self):
        # If there are more than one PMU then try running mixed events
        if len(self.pmu_list) > 1:
            mix_events = []
            for keys in self.all_events.keys():
                mix_events.append(self.all_events[keys][0])
            op = process.system_output("perf stat -e '{%s}' sleep 1"
                                       % (",".join(mix_events)), shell=True,
                                       ignore_status=True)
            er_ln = "The events in group usually have to be from the same PMU"
            output = op.stdout.decode() + op.stderr.decode()
            # Expecting failure with the string in 'er_ln'
            if er_ln in output:
                self.log.info("Expected failure with mixed events")
            else:
                self.fail("Expected a failure but test pass.")
        else:
            self.cancel("With single PMU mixed events test is not possible.")

    def _get_cpumask(self, event_type):
        # Reading the cpumask and return
        event_cpumask_file = "%s%s/cpumask" % (self.base_dir, event_type)
        return int(genio.read_file(event_cpumask_file).rstrip('\t\r\n\0'))

    def test_pmu_cpumask(self):
        # Checking whether the PMU cpumask exists or not
        failed_list = []
        for pmu in self.pmu_list:
            pmu_cpumask = self._get_cpumask(pmu)
            if not str(pmu_cpumask):
                failed_list.append(pmu_cpumask)
            self.log.info("%s contains cpumask = %s" % (pmu, pmu_cpumask))
        if failed_list:
            self.fail("Not found cpumask file for %s" % failed_list)

    def _check_cpumask(self):
        pmu_cpumask = []
        for pmu in list(self.all_events.keys()):
            pmu_cpumask.append(self._get_cpumask(pmu))
        if pmu_cpumask:
            self.log.info("Found cpumasks are = %s" % pmu_cpumask)
        else:
            self.fail("Fail to get cpumask")
        # Get the unique value from the cpumask list
        if len(set(pmu_cpumask)) != 1:
            self.fail("cpumask values are not same: %s" % pmu_cpumask)

    def test_cpumask(self):
        # Checking all the PMUs cpumask is same or not
        self._check_cpumask()

    def test_cpumask_cpu_off(self):
        # Get the online cpu list
        online_cpus = cpu.online_list()
        self.log.info("Online CPU list: %s" % online_cpus)
        pmu1 = list(self.all_events.keys())[0]
        disable_cpu = self._get_cpumask(pmu1)
        # Disable cpu with one PMU cpumask
        if cpu.offline(disable_cpu):
            self.fail("Can't offline cpumask cpu %s" % disable_cpu)
        current_cpu = self._get_cpumask(pmu1)
        self.log.info("Current CPU: %s" % current_cpu)
        self._check_cpumask()
        # After confirming cpu got disabled, enable back
        if current_cpu not in online_cpus and disable_cpu != current_cpu:
            if cpu.online(disable_cpu):
                self.fail("Can't online cpu %s" % disable_cpu)
