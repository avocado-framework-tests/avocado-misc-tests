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
# Copyright: 2017 IBM
# Author: Athira Rajeev<atrajeev@linux.vnet.ibm.com>
# Author: Shriya Kulkarni <shriyak@linux.vnet.ibm.com>

import os
import re
import platform
from avocado import Test
from avocado.utils import process, distro, cpu, genio
from avocado.utils.software_manager.manager import SoftwareManager
from avocado import skipIf

IS_POWER_NV = 'PowerNV' in genio.read_file('/proc/cpuinfo').rstrip('\t\r\n\0')
IS_KVM_GUEST = 'qemu' in genio.read_file('/proc/cpuinfo').rstrip('\t\r\n\0')


class EliminateDomainSuffix(Test):

    """
    This tests domain name suffix in event names
    :avocado: tags=perf,24x7,events
    """

    @skipIf(IS_POWER_NV or IS_KVM_GUEST,
            "This test is not supported on KVM guest or Power non-virtualized platform")
    def setUp(self):
        """
        Setup checks :
        0. Processor should be ppc64.
        1. Perf package
        2. 24x7 is present
        3. Performance measurement is enabled in lpar through BMC
        """
        smm = SoftwareManager()
        detected_distro = distro.detect()
        processor = process.system_output(
            "uname -m", ignore_status=True).decode("utf-8")
        if 'ppc' not in processor:
            if 'unknown' in processor and 'ppc' not in os.uname():
                self.cancel("Processor is not ppc64")
        deps = ['gcc', 'make']
        if 'Ubuntu' in detected_distro.name:
            deps.extend(['linux-tools-common', 'linux-tools-%s'
                         % platform.uname()[2]])
        elif detected_distro.name in ['debian']:
            deps.extend(['linux-perf', 'perf-tools-unstable'])
        elif detected_distro.name in ['rhel', 'SuSE', 'fedora', 'centos']:
            deps.extend(['perf'])
        else:
            self.cancel("Install the package for perf supported by %s"
                        % detected_distro.name)
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

        self.cpu_family = cpu.get_family()
        self.perf_args = "perf stat -v -e"
        if self.cpu_family == 'power8':
            self.perf_stat = "%s hv_24x7/HPM_0THRD_NON_IDLE_CCYC" % self.perf_args
        if self.cpu_family == 'power9':
            self.perf_stat = "%s hv_24x7/CPM_TLBIE" % self.perf_args
        if self.cpu_family == 'power10':
            self.perf_stat = "%s hv_24x7/CPM_TLBIE_FIN" % self.perf_args
        self.event_sysfs = "/sys/bus/event_source/devices/hv_24x7"

        # Check if 24x7 is present
        if os.path.exists("%s" % self.event_sysfs):
            self.log.info('hv_24x7 present')
        else:
            self.cancel("%s doesn't exist.This feature is supported"
                        " only on LPAR" % self.event_sysfs)

        # Performance measurement has to be enabled in lpar through BMC
        # Check if its enabled
        result_perf = process.run("%s,domain=2,core=1/ sleep 1"
                                  % self.perf_stat, ignore_status=True)
        if "operations is limited" in result_perf.stderr.decode("utf-8"):
            self.cancel("Please enable lpar to allow collecting"
                        " the 24x7 counters info")

        # Initializing the values of chips and cores using lspcu
        self.chips = cpu.lscpu()["chips"]
        self.phys_cores = cpu.lscpu()["physical_cores"]
        self.vir_cores = cpu.lscpu()["virtual_cores"]

    # Features testing
    def test_display_domain_indices_in_sysfs(self):
        pattern = re.compile('1: Physical Chip\n2: Physical Core\n3:'
                             ' VCPU Home Core\n4: VCPU Home Chip\n5:'
                             ' VCPU Home Node\n6: VCPU Remote Node')
        result = process.run('cat %s/interface/domains' % self.event_sysfs)
        result_search = pattern.search(result.stdout.decode("utf-8"))
        if result_search:
            self.log.info('Displayed domain indices in sysfs')
        else:
            self.fail('Unable to display domain indices in sysfs')

    def test_event_phys_core_param(self):
        found_flag = False
        for lne in process.get_command_output_matching('perf list', 'hv_24x7'):
            lne = lne.split(',')[0].split('/')[1]
            if 'HPM_0THRD_NON_IDLE_CCYC__PHYS_CORE' in lne:
                found_flag = True
                break
        if not found_flag:
            self.cancel("HPM_0THRD_NON_IDLE_CCYC__PHYS_CORE not found")
        result1 = self.event_stat('__PHYS_CORE,core=1/ sleep 1')
        if "Invalid event/parameter" not in result1.stdout.decode("utf-8"):
            self.fail('perf unable to recognize'
                      ' hv_24x7/HPM_0THRD_NON_IDLE_CCYC__PHYS_CORE'
                      ' has invalid event')
        else:
            self.log.info('perf recognized Invalid event')

    def test_event_wo_domain_param(self):
        result1 = self.event_stat('/ sleep 1')
        if "Required parameter 'domain' not specified" not in result1.stdout.decode("utf-8"):
            self.fail('Domain is not specified, perf unable'
                      ' to recognize it has invalid event')
        else:
            self.log.info('perf recognized unsupported event')

    def test_check_all_domains(self):
        # supported domain range 1-6 and max 15
        # check all valid domains
        # TODO get lpar id value from command line
        for domain in range(2, 7):
            if domain == 2:
                core_range = self.phys_cores
            else:
                core_range = self.vir_cores
            for core in range(0, core_range):
                result1 = self.event_stat(
                    ',domain=%s,core=%s,lpar=1/ sleep 1' % (domain, core))
                if "Performance counter stats for" not in result1.stderr.decode("utf-8"):
                    self.fail('perf unable to recognize domain name in'
                              ' param=value format for all domains')
                else:
                    self.log.info('perf recognized domain name in param=value'
                                  ' format for all 6 domains')

    def test_check_invalid_domains(self):
        # check invalid domains
        invalid_domains = [0, 7, 16]
        for domain in invalid_domains:
            result = self.event_stat(',domain=%s,core=1/ sleep 1' % domain)
            if result.exit_status == 0 and b"not supported" in result.stderr:
                self.log.info("perf recognized domain as invalid domains")
            elif domain == 16 and result.exit_status != 0:
                self.log.info("perf recognized domain as invalid domain")
            else:
                self.fail("perf unable to recognize invalid domain")

    def test_check_invalid_core(self):
        """
        for domain 2, supported core value is physical core range
        physical_core = Physical Sockets * Physical chips * Physical cores/chip
        check invalid core value
        """
        result = self.event_stat(',domain=2,core=%s/ sleep 1' % self.phys_cores)
        if result.exit_status == 0:
            self.fail('perf unable to recognize out of range core value')

    def test_event_w_chip_param(self):
<<<<<<< HEAD
        if self.rev in ['004b', '004e']:
            event_out = genio.read_file(
                "%s/events/PM_PB_CYC" % self.event_sysfs).rstrip('\t\r\n\0')
        if self.rev in ['0080', '0082']:
=======
        if self.cpu_family in ['power8', 'power9']:
            event_out = genio.read_file(
                "%s/events/PM_PB_CYC" % self.event_sysfs).rstrip('\t\r\n\0')
        if self.cpu_family == 'power10':
>>>>>>> 303037e1 (misc-test/ci: Customization for ci runs)
            event_out = genio.read_file(
                "%s/events/PM_PHB0_0_CYC" % self.event_sysfs).rstrip('\t\r\n\0')
        if "chip=?" in event_out:
            self.log.info('sysfs entry has chip entry')
        else:
            self.fail('sysfs does not have chip entry')

        if os.path.exists("%s/format/chip" % self.event_sysfs):
            self.log.info('chip file exists')
        else:
            self.fail('chip file does not exist')

    def test_event_wo_chip_param(self):
<<<<<<< HEAD
        if self.rev in ['004b', '004e']:
            cmd = "hv_24x7/PM_PB_CYC,domain=1/ /bin/true"
        if self.rev in ['0080', '0082']:
=======
        if self.cpu_family in ['power8', 'power9']:
            cmd = "hv_24x7/PM_PB_CYC,domain=1/ /bin/true"
        if self.cpu_family == 'power10':
>>>>>>> 303037e1 (misc-test/ci: Customization for ci runs)
            cmd = "hv_24x7/PM_PHB0_0_CYC,domain=1/ /bin/true"
        chip_miss = self.event_stat1(cmd)
        if "Required parameter 'chip' not specified" not in chip_miss.stdout.decode("utf-8"):
            self.fail('perf unable to detect chip'
                      ' parameter missing')
        else:
            self.log.info('perf detected chip parameter missing')

    def test_check_valid_chip(self):
        """
        Valid chip value ranges from 0 to self.chips-1 and max 65535
        Test chip value in range self.chips-1 and max 65535
        """
        for chip_val in range(0, self.chips):
            if self.rev in ['004b', '004e']:
                cmd = "hv_24x7/PM_PB_CYC,domain=1,chip=%s/ /bin/true" % chip_val
            if self.rev in ['0080', '0082']:
                cmd = "hv_24x7/PM_PHB0_0_CYC,domain=1,chip=%s/ /bin/true" % chip_val
            output_chip = self.event_stat1(cmd)
            if "Performance counter stats for" not in output_chip.stderr.decode("utf-8"):
                self.fail('performance counter stats are missing')

    def test_check_invalid_chip(self):
        """
        Test invalid out of range chip value
        """
        invalid_chip = [self.chips, 65536]
        for chip_val in invalid_chip:
            if self.rev in ['004b', '004e']:
                cmd = "hv_24x7/PM_PB_CYC,domain=1,chip=%s/ /bin/true" % chip_val
            if self.rev in ['0080', '0082']:
                cmd = "hv_24x7/PM_PHB0_0_CYC,domain=1,chip=%s/ /bin/true" % chip_val
            res = self.event_stat1(cmd)
            if res.exit_status == 0:
                self.fail("perf unable to recognise invalid chip value")

    def test_domain_chip_offset(self):
        cmd = "perf stat -r 10 -x ' ' perf stat -r 10 -x ' ' \
               -e hv_24x7/domain=2,offset=0xe0,core=0/ sleep 1"
        process.run(cmd)

    # Helper functions
    def event_helper(self, event):
        search_suffix = process.run('ls %s/events' % (self.event_sysfs),
                                    ignore_status=True)
        if event in search_suffix.stdout.decode("utf-8"):
            self.fail('Found %s  suffixes in event name' % event)
        else:
            self.log.info('No %s  suffixes in event name', event)

    def test_event_helper_phys_core(self):
        self.event_helper('__PHYS_CORE')

    def test_event_helper_vcpu(self):
        self.event_helper('VCPU')

    def event_stat(self, cmd):
        return process.run('%s%s' % (self.perf_stat, cmd), ignore_status=True)

    def event_stat1(self, cmd):
        return process.run('%s %s' % (self.perf_args, cmd), ignore_status=True)
