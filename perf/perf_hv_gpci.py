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
# Author: Nageswara R Sastry <rnsastry@linux.vnet.ibm.com>

import platform
from avocado import Test
from avocado.utils import distro, process, genio, dmesg
from avocado.utils.software_manager.manager import SoftwareManager


class perf_hv_gpci(Test):

    """
    Tests hv_gpci events
    :avocado: tags=perf,hv_gpci,events
    """
    # Initializing fail command list
    fail_cmd = list()

    def setUp(self):
        '''
        Install the basic packages to support perf
        '''

        # Check for basic utilities
        smm = SoftwareManager()
        detected_distro = distro.detect()
        self.distro_name = detected_distro.name

        if 'ppc64' not in detected_distro.arch:
            self.cancel('This test is not supported on %s architecture'
                        % detected_distro.arch)
        if 'PowerNV' in genio.read_file('/proc/cpuinfo'):
            self.cancel('This test is only supported on LPAR')

        deps = ['gcc', 'make']
        if 'Ubuntu' in self.distro_name:
            deps.extend(['linux-tools-common', 'linux-tools-%s' %
                         platform.uname()[2]])
        elif self.distro_name in ['rhel', 'SuSE', 'fedora', 'centos']:
            deps.extend(['perf'])
        else:
            self.cancel("Install the package for perf supported \
                         by %s" % detected_distro.name)
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

        # create temporary user
        if process.system('useradd test', sudo=True, ignore_status=True):
            self.log.warn('test useradd failed')

        # Collect all hv_gpci events
        self.list_phys = []
        self.list_sibling = []
        self.list_partition = []
        self.list_hw = []
        self.list_noid = []
        # Equivalent Python code for bash command
        # "perf list | grep 'hv_gpci' | grep -v 'descriptor'"
        for line in process.get_command_output_matching("perf list", 'hv_gpci'):
            if 'descriptor' not in line:
                line = "%s/%s" % (line.split('/')[0], line.split('/')[1])
                if 'phys_processor_idx' in line:
                    self.list_phys.append(line)
                elif 'sibling_part_id' in line:
                    self.list_sibling.append(line)
                elif 'partition_id' in line:
                    self.list_partition.append(line)
                elif 'hw_chip_id' in line:
                    self.list_hw.append(line)
                else:
                    self.list_noid.append(line)

        # Clear the dmesg, by that we can capture the delta at the end of
        # the test.
        dmesg.clear_dmesg()

    def error_check(self):
        if len(self.fail_cmd) > 0:
            for cmd in range(len(self.fail_cmd)):
                self.log.info("Failed command: %s" % self.fail_cmd[cmd])
            self.fail("perf hv_gpci: some of the events failed,"
                      "refer to log")

    def run_cmd(self, cmd):
        result = process.run(cmd, shell=True, ignore_status=True)
        output = result.stdout.decode() + result.stderr.decode()
        if (result.exit_status != 0) or ("not supported" in output):
            self.fail_cmd.append(cmd)

        # test hv_gpci events with normal user
        if not process.system('id test', sudo=True, ignore_status=True):
            result = process.run("su - test -c '%s'" % cmd, shell=True,
                                 ignore_status=True)
            err_ln = "kernel.perf_event_paranoid=2, trying to fall back to "
            "excluding kernel and hypervisor  samples"
            if err_ln not in result.stderr.decode():
                self.fail("able to read hv_gpci counter data as normal user")
        else:
            self.log.warn('User test does not exist, skipping test')

    def gpci_events(self, val):
        for line in val:
            if line in self.list_phys:
                line = "%s,%s/" % (line.split(',')[0], line.split(',')[1].replace(
                    'phys_processor_idx=?', 'phys_processor_idx=1'))
            if line in self.list_sibling:
                line = "%s,%s/" % (line.split(',')[0], line.split(',')[1].replace(
                    'sibling_part_id=?', 'sibling_part_id=2'))
            if line in self.list_partition:
                lparcfg = genio.read_file('/proc/powerpc/lparcfg')
                for newline in lparcfg.split('\n'):
                    if "partition_id" in newline:
                        part_id = newline.strip().split('=')[1]
                line = "%s,%s/" % (line.split(',')[0], line.split(',')
                                   [1].replace('?', part_id))
            if line in self.list_hw:
                line = "%s,%s/" % (line.split(',')[0], line.split(',')[1].replace(
                    'hw_chip_id=?', 'hw_chip_id=12'))
            if line in self.list_noid:
                line = "%s/" % line

            cmd = "perf stat -v -e %s sleep 1" % line
            self.run_cmd(cmd)
        self.error_check()

    def test_gpci_events(self):
        for event in [self.list_phys, self.list_sibling, self.list_partition,
                      self.list_hw, self.list_noid]:
            self.gpci_events(event)

    def tearDown(self):
        if not (process.system('id test', sudo=True, ignore_status=True)):
            process.system('userdel -f test', sudo=True)
        # Collect the dmesg
        process.run("dmesg -T")
