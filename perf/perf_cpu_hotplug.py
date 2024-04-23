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

import os
import platform
import random
from avocado import Test
from avocado.utils import cpu, dmesg, distro, genio
from avocado.utils.software_manager.manager import SoftwareManager
from avocado import skipIf

IS_POWER_NV = 'PowerNV' in genio.read_file('/proc/cpuinfo').rstrip('\t\r\n\0')


class perf_cpu_hotplug(Test):

    """
    This tests hv_24x7 and hv_gpci cpu_hotplug
    :avocado: tags=perf,cpu_hotplug,events
    """
    # Initializing fail command list
    fail_cmd = list()

    def _check_file(self, event_type):
        event_sysfs = "/sys/bus/event_source/devices/%s" % event_type
        event_cpumask = "/sys/devices/%s/cpumask" % event_type
        flag1 = False
        flag2 = False
        if os.path.exists("%s" % event_sysfs):
            self.log.info('%s present' % event_type)
            flag1 = True
            if os.path.exists("%s" % event_cpumask):
                self.log.info("%s cpumask present" % event_type)
                flag2 = True
        return (flag1, flag2)

    @skipIf(IS_POWER_NV, "This test is supported on PowerVM environment")
    def setUp(self):
        """
        Setup checks :
        0. Processor should be ppc64.
        1. Install perf package
        2. Check for hv_24x7/hv_gpci cpumask
        3. Offline the cpumask CPU and check cpumask moved to new CPU or not
        """
        smm = SoftwareManager()
        processor_type = genio.read_file("/proc/cpuinfo")

        detected_distro = distro.detect()
        # Offline cpu list during the test
        self.cpu_off = []

        if 'ppc64' not in detected_distro.arch:
            self.cancel("Processor is not PowerPC")
        for line in processor_type.splitlines():
            if 'revision' in line:
                self.rev = (line.split(':')[1])
                if '0080' not in self.rev:
                    self.cancel("Test is supported only on Power10")

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

        hv24x7_present = False
        hvgpci_present = False
        self.hv24x7_cpumask = False
        self.hvpgci_cpumask = False
        self.events = ["hv_24x7", "hv_gpci"]
        hv24x7_present, self.hv24x7_cpumask = self._check_file("hv_24x7")
        hvgpci_present, self.hvpgci_cpumask = self._check_file("hv_gpci")

        # To proceed with the test we need either of hv_24x7 or hv_gpci
        if not (hv24x7_present and hvgpci_present):
            self.fail("hv_24x7 and hv_gpci both events not found")

        # Collect the cpu list
        self.online_cpus = cpu.online_list()
        self.log.info("Online CPU list: %s" % self.online_cpus)

        # Clear the dmesg to capture the delta at the end of the test.
        dmesg.clear_dmesg()

    def _get_cpumask(self, event_type):
        event_cpumask_file = "/sys/devices/%s/cpumask" % event_type
        return int(genio.read_file(event_cpumask_file).rstrip('\t\r\n\0'))

    def _cpu_on_off(self, cpu_number, disable_flag=True):
        cpu_file = "/sys/bus/cpu/devices/cpu%s/online" % cpu_number
        if disable_flag:
            genio.write_one_line(cpu_file, "0")
            self.log.info("Offlined CPU: %s" % cpu_number)
        else:
            genio.write_one_line(cpu_file, "1")
            self.log.info("Onlined CPU: %s" % cpu_number)

    def test_cpumask_cpu_off_random(self):
        """ Checks if the events hv_24X7 and hv_gpci points to any
        offline cpu while randomly offlining n-1 CPUs """
        for event in self.events:
            for i in range(0, len(self.online_cpus)-1):
                cpuno = random.choice(self.online_cpus)
                self.log.info("Randomly offlining cpu no : %s" % cpuno)
                self._cpu_on_off(cpuno)
                self.cpu_off.append(cpuno)
                new_event_cpu = self._get_cpumask(event)
                self.log.info("Current cpumask of the %s event : %s " %
                              (event, new_event_cpu))
                self.online_cpus = cpu.online_list()
                self.log.info("Updated online CPU list: %s" % self.online_cpus)
                self.log.info("Updated offline CPU list:%s" % self.cpu_off)
                if new_event_cpu not in self.online_cpus:
                    self.fail("%s points to an offline cpu" % event)
            for cpus in self.cpu_off:
                self._cpu_on_off(cpus, disable_flag=False)
                self.online_cpus = cpu.online_list()

    def test_cpumask_cpu_off_sequence(self):
        """ Offlines the cpu pointed to by events hv_24X7 and hv_gpci
        for n-1 times and  checks each time if the new cpu pointed
        to by the events is an offline cpu """
        for event in self.events:
            for i in range(0, len(self.online_cpus)-1):
                event_cpu = self._get_cpumask(event)
                self.log.info("Offlining current cpu %s of %s event"
                              % (event_cpu, event))
                self._cpu_on_off(event_cpu)
                self.cpu_off.append(event_cpu)
                new_event_cpu = self._get_cpumask(event)
                self.log.info("New cpumask of %s event : %s" %
                              (event, new_event_cpu))
                self.online_cpus = cpu.online_list()
                self.log.info("Updated online CPU list: %s" % self.online_cpus)
                self.log.info("Updated offline CPU list:%s" % self.cpu_off)
                if event_cpu in self.online_cpus:
                    self.fail("CPU offlining failed")
                elif new_event_cpu == event_cpu | new_event_cpu not in self.online_cpus:
                    self.fail("%s points to an offline cpu" % event)
            for cpus in self.cpu_off:
                self._cpu_on_off(cpus, disable_flag=False)
                self.online_cpus = cpu.online_list()
