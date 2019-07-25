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
# Copyright: 2019 IBM
# Author: Nageswara R Sastry <rnsastry@linux.vnet.ibm.com>

import os
import platform
from avocado import Test
from avocado import main
from avocado.utils import cpu, distro, memory, process
from avocado.utils.software_manager import SoftwareManager


class hv_24x7_all_events(Test):

    """
    This tests all hv_24x7 events
    :avocado: tags=perf,24x7,events
    """
    # Initializing fail command list
    fail_cmd = list()

    def setUp(self):
        """
        Setup checks :
        0. Processor should be ppc64.
        1. Perf package
        2. 24x7 is not supported on guest
        3. 24x7 is present
        4. Performance measurement is enabled in LPAR through BMC
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

        self.cpu_arch = cpu.get_cpu_arch().lower()
        self.perf_args = "perf stat -v -C 0 -e"
        if self.cpu_arch == 'power8':
            self.perf_stat = "%s hv_24x7/HPM_0THRD_NON_IDLE_CCYC" % self.perf_args
        if self.cpu_arch == 'power9':
            self.perf_stat = "%s hv_24x7/CPM_TLBIE" % self.perf_args
        self.event_sysfs = "/sys/bus/event_source/devices/hv_24x7"

        # Check if this is a guest
        # 24x7 is not suported on guest
        if "emulated by" in cpu._get_cpu_info():
            self.cancel("This test is not supported on guest")

        # Check if 24x7 is present
        if os.path.exists(self.event_sysfs):
            self.log.info('hv_24x7 present')
        else:
            self.cancel("%s doesn't exist.This test is supported"
                        " only on PowerVM" % self.event_sysfs)

        # Performance measurement has to be enabled in lpar through BMC
        # Check if its enabled
        result_perf = process.run("%s,domain=2,core=1/ sleep 1"
                                  % self.perf_stat, ignore_status=True)
        if "not supported" in result_perf.stderr:
            self.cancel("Please enable LPAR to allow collecting"
                        " the 24x7 counters info")

        # Getting the number of cores
        output = process.run("lscpu")
        for line in output.stdout.split('\n'):
            if 'Core(s) per socket:' in line:
                self.cores = int(line.split(':')[1].strip())

        # Getting the number of chips available in the machine
        self.chip = memory.numa_nodes()

        # Collect all hv_24x7 events
        self.list_of_hv_24x7_events = []
        for line in process.get_perf_events('hv_24x7'):
            line = line.split(',')[0].split('/')[1]
            self.list_of_hv_24x7_events.append(line)

        # Clear the dmesg, by that we can capture the delta at the end of the test.
        process.run("dmesg -c", sudo=True)

    def test_all_events(self):
        perf_args = "-C 9 -v -e"
        for line in self.list_of_hv_24x7_events:
            if line.startswith('HP') or line.startswith('CP'):
                # Running for domain range from 1-6
                for domain in range(1, 7):
                    for core in range(0, self.cores + 1):
                        events = "hv_24x7/%s,domain=%s,core=%s/" % (line, domain, core)
                        cmd = 'perf stat %s %s sleep 1' % (perf_args, events)
                        if process.system(cmd, ignore_status=True):
                            self.fail_cmd.append(cmd)
            else:
                for chip_item in self.chip:
                    events = "hv_24x7/%s,chip=%s/" % (line, chip_item)
                    cmd = "perf stat %s %s sleep 1" % (perf_args, events)
                    if process.system(cmd, ignore_status=True):
                        self.fail_cmd.append(cmd)

        if len(self.fail_cmd) > 0:
            for cmd in range(len(self.fail_cmd)):
                self.log.info("Failed command: %s" % self.fail_cmd[cmd])
            self.fail("hv_24x7: some of the commands failed, refer to log")

    def tearDown(self):
        # Collect the dmesg
        process.run("dmesg -T")


if __name__ == "__main__":
    main()
