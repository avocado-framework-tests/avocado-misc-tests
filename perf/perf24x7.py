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
from avocado import main
from avocado.utils import process, distro
from avocado.utils.software_manager import SoftwareManager


class test_eliminate_domain_suffix(Test):

    """
    This tests domain name suffix in event names
    """

    def setUp(self):
        """
        Setup checks :
        0. Processor should be ppc64.
        1. Perf package
        2. 24x7 is not supported on guest
        3. 24x7 is present
        4. Performance measurement is enabled in lpar through BMC
        """
        smm = SoftwareManager()
        detected_distro = distro.detect()
        kernel_ver = platform.uname()[2]
        command = "uname -p"
        if 'ppc' not in process.system_output(command, ignore_status=True):
            self.skip("Processor is not ppc64")
        deps = ['gcc', 'make']
        if 'Ubuntu' in detected_distro.name:
            deps.extend(['linux-tools-common', 'linux-tools-%s'
                         % kernel_ver])
        elif detected_distro.name in ['redhat', 'SuSE', 'fedora', 'centos']:
            deps.extend(['perf'])
        else:
            self.skip("Install the package for perf supported by %s"
                      % detected_distro.name)
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.skip('%s is needed for the test to be run' % package)
        self.nfail = 0
        self.perf_args = "perf stat -v -C 0 -e"
        self.perf_stat = "%s hv_24x7/HPM_0THRD_NON_IDLE_CCYC" % self.perf_args
        self.event_sysfs = "/sys/bus/event_source/devices/hv_24x7"

        # Check if this is a guest
        # 24x7 is not suported on guest
        cpu_output = process.run("cat /proc/cpuinfo")
        if "emulated by" in cpu_output.stdout:
            self.cancel("This test is not supported on guest")

        # Check if 24x7 is present
        if os.path.exists("%s" % self.event_sysfs):
            self.log.info('hv_24x7 present')
        else:
            self.cancel("%s doesn't exist.This feature is supported"
                        "on only lpar" % self.event_sysfs)

        # Performance measurement has to be enabled in lpar through BMC
        # Check if its enabled
        # Refer https://bugzilla.linux.ibm.com/show_bug.cgi?id=139404#c21
        result_perf = process.run("%s,domain=2,core=1/ sleep 1"
                                  % self.perf_stat, ignore_status=True)
        if "You may not have permission to collect\
                stats" in result_perf.stderr:
            self.cancel("Please enable lpar to allow collecting"
                        "the 24x7 counters info")

    def test(self):
        '''
        Execute :
        1.Display domain indices in sysfs
        2.Eliminate domain suffix in event name
        3.Fix usage with chip events
        4.Check using domain which is not existing
        '''
        # Testing feature: Display domain indices in sysfs
        # Part of commit d34171e
        self.display_domain_indices_in_sysfs()
        # Verify No __PHYS_CORE or VCPU* suffixes in event name
        self.event_helper('__PHYS_CORE')
        self.event_helper('VCPU')
        # Using hv_24x7/HPM_0THRD_NON_IDLE_CCYC__PHYS_CORE should fail
        self.event_phys_core_param()
        # Check if missing parameter is reported
        self.event_wo_domain_param()
        # Check param=value format works
        self.event_w_domain_param()
        # Testing feature: Check using domain which is not existing
        self.check_domain_not_existing()
        # Check for all domains
        self.check_all_domains()
        # Testing feature: Fix usage with chip events
        self.event_w_chip_param()
        # Check missing chip parameter
        self.event_wo_chip_param()
        if self.nfail != 0:
            self.fail('Failed to verify domain name suffix'
                      'in event names')

        # Features testing
    def display_domain_indices_in_sysfs(self):
        pattern = re.compile('1: Physical Chip\n2: Physical Core\n3:'
                             ' VCPU Home Core\n4: VCPU Home Chip\n5:'
                             ' VCPU Home Node\n6: VCPU Remote Node')
        # pattern = re.compile('1: Physical Chip\n2: Physical Core\n3: VCPU
        # Home Core\n4: VCPU Home Chip\n5: VCPU Home Node\n6: VCPU Remote
        # Node')
        result = process.run('cat %s/interface/domains' % self.event_sysfs)
        Result_search = pattern.search(result.stdout)
        if Result_search:
            self.log.info('Displayed domain indices in sysfs')
        else:
            self.nfail += 1
            self.log.info('FAIL : Unable to display domain indices in sysfs')

    def event_phys_core_param(self):
        result1 = self.event_stat('__PHYS_CORE,core=1/ sleep 1')
        if "Invalid event/parameter" not in result1.stdout:
            self.nfail += 1
            self.log.info('FAIL : perf unable to recognize'
                          'hv_24x7/HPM_0THRD_NON_IDLE_CCYC__PHYS_CORE'
                          'has invalid event')
        else:
            self.log.info('perf recognized Invalid event')

    def event_wo_domain_param(self):
        result1 = self.event_stat('/ sleep 1')
        if "invalid or unsupported event" not in result1.stderr or "Required "\
                "parameter 'domain' not specified" not in result1.stdout:
            self.nfail += 1
            self.log.info('FAIL : Domain is not specified, perf unable'
                          'to recognize it has invalid event')
        else:
            self.log.info('perf recognized unsupported event')

    def event_w_domain_param(self):
        result1 = self.event_stat(',domain=2,core=1/ sleep 1')
        print result1.stderr
        if "Performance counter stats for" not in result1.stderr:
            self.nfail += 1
            self.log.info('FAIL : perf unable to recognize domain name'
                          'in param=value format')
        else:
            self.log.info('perf recognized domain name in param=value format')

    def check_domain_not_existing(self):
        result1 = self.event_stat(',domain=12,core=1/ sleep 1')
        if "not supported" not in result1.stderr:
            self.nfail += 1
            self.log.info('FAIL : domain does not exist but perf listed'
                          'has supported')
        else:
            self.log.info('perf listed non-existing domain as unsupported')

    def check_all_domains(self):
        for domain in range(1, 6):
            result1 = self.event_stat(',domain=%s,core=1/ sleep 1' % domain)
            if "Performance counter stats for" not in result1.stderr:
                self.nfail += 1
                self.log.info('FAIL : perf unable to recognize domain name in'
                              'param=value format for all domains')
            else:
                self.log.info('perf recognized domain name in param=value'
                              'format for all 6 domains')

    def event_w_chip_param(self):
        event_out = process.run("cat %s/events/"
                                "PM_XLINK_CYCLES" % self.event_sysfs)
        if "chip=?" in event_out.stdout:
            self.log.info('sysfs entry has chip entry')
        else:
            self.nfail += 1
            self.log.info('FAIL : sysfs does not have chip entry')

        if os.path.exists("%s/format/chip" % self.event_sysfs):
            self.log.info('chip file exists')
        else:
            self.nfail += 1
            self.log.info('FAIL : chip file does not exist')

    def event_wo_chip_param(self):
        cmd = "hv_24x7/PM_XLINK_CYCLES,domain=1/ /bin/true"
        chip_miss = self.event_stat1(cmd)
        if "Required parameter 'chip' not specified" not in chip_miss.stdout:
            self.nfail += 1
            self.log.info('FAIL : perf unable to detect chip'
                          'parameter missing')
        else:
            self.log.info('perf detected chip parameter missing')
        cmd = "hv_24x7/PM_XLINK_CYCLES,domain=1,chip=1/ /bin/true"
        output_chip = self.event_stat1(cmd)
        if "Performance counter stats for" not in output_chip.stderr:
            self.nfail += 1
            self.log.info('FAIL : performance counter stats for missing')

    # Helper functions
    def event_helper(self, event):
        search_suffix = process.run('ls %s/events |grep -E '
                                    '%s' % (self.event_sysfs, event),
                                    ignore_status=True)
        if search_suffix.stdout:
            self.nfail += 1
            self.log.info('FAIL : Found %s  suffixes in event name' % event)
        else:
            self.log.info('No %s  suffixes in event name' % event)

    def event_stat(self, cmd):
        return process.run('%s%s' % (self.perf_stat, cmd), ignore_status=True)

    def event_stat1(self, cmd):
        return process.run('%s %s' % (self.perf_args, cmd), ignore_status=True)


if __name__ == "__main__":
    main()
