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
# Copyright: 2016 IBM
# Author: Athira Rajeev<atrajeev@linux.vnet.ibm.com>

import os
import sys
import re
from avocado import Test
from avocado import main
from avocado.utils import process


class test_eliminate_domain_suffix(Test):
    """
    This tests domain name suffix in event names
    """

    def setUp(self):
        """
        Check if kernel version has the supported feature
        This feature is enabled from 3.10.0.419
        """

        # Compare kernel version
        kernel_ver = os.uname()[2]
        split_value = kernel_ver.split('.')
        kernel_Version = ".".join(split_value[0:3]).replace("-", ".")
        kernel_to_compare = "3.10.0.419"

        result_comparison = 0

        for cur_ker, supported_ker in zip(kernel_Version.split(".")[:4],
                                          kernel_to_compare.split(".")[:4]):
            if cur_ker > supported_ker:
                result_comparison = 1

        if result_comparison != 1:
            raise self.log.warn(
                "This test is not supported on this kernel version")

    def test(self):
        nfail = 0

        # Check if this is a guest
        # 24x7 is not suported on guest
        cpu_output = process.run("cat /proc/cpuinfo")
        if "emulated by" in cpu_output.stdout:
            self.skipTest("This test is not supported on guest")

        # Check if 24x7 is present
        if os.path.exists("/sys/bus/event_source/devices/hv_24x7"):
            self.log.info('/sys/bus/event_source/devices/hv_24x7 present')
        else:
            raise self.error("hv_24x7 doesn't exist.
                             This feature is supported on only lpar")

        # Performance measurement has to be enabled in lpar through BMC
        # Check if its enabled
        # Refer https://bugzilla.linux.ibm.com/show_bug.cgi?id=139404#c21
        result_perf = process.run("perf stat -v -C 0 -e\
            hv_24x7/HPM_0THRD_NON_IDLE_CCYC,domain = 2,\
            core = 1/ sleep 1", ignore_status=True)
        if "You may not have permission to collect stats" in\
                result_perf.stderr:
            raise self.error("Please enable lpar to allow\
                             collecting the 24x7 counters info")

        # Testing feature: Display domain indices in sysfs
        # Part of commit d34171e
        EVENT_SYSFS = "/sys/bus/event_source/devices/hv_24x7/events"
        pattern = re.compile('1: Physical Chip\n2: Physical Core\n
                             3: VCPU Home Core\n4: VCPU Home Chip\n
                             5: VCPU Home Node\n6: VCPU Remote Node')
        result = process.run(
            'cat /sys/bus/event_source/devices/hv_24x7/interface/domains')
        Result_search = pattern.search(result.stdout)
        if Result_search:
            self.log.info('Displayed domain indices in sysfs')
        else:
            nfail += 1

        # Testing feature: Eliminate domain suffix in event name
        # Verify No __PHYS_CORE or VCPU* suffixes in event name
        search_suffix = process.run(
            'ls %s |grep -E __PHYS_CORE' % EVENT_SYSFS, ignore_status=True)
        if search_suffix.stdout:
            nfail += 1
            self.log.info('Found __PHYS_CORE or VCPU* suffixes in event name')
        else:
            self.log.info('No __PHYS_CORE or VCPU* suffixes in event name')

        # Using hv_24x7/HPM_0THRD_NON_IDLE_CCYC__PHYS_CORE should fail
        result1 = process.run('perf stat - v - C 0 - e\
            hv_24x7/HPM_0THRD_NON_IDLE_CCYC__PHYS_CORE,\
            core=1 / sleep 1', ignore_status=True)
        if "Invalid event/parameter" not in result1.stdout:
            nfail += 1
        else:
            self.log.info('perf recognized Invalid event')

        # Check if missing parameter is reported
        result1 = process.run(
            'perf stat -v -C 0 -e hv_24x7/HPM_0THRD_NON_IDLE_CCYC/ sleep 1',
            ignore_status=True)
        if "invalid or unsupported event" not in result1.stderr or\
                "Required parameter 'domain' not specified" not in\
                result1.stdout:
            nfail += 1
        else:
            self.log.info('perf recognized unsupported event')

        # Check param=value format works
        result2 = process.run('perf stat -v -C 0 -e\
            hv_24x7/HPM_0THRD_NON_IDLE_CCYC,domain = 2,\
            core = 1/ sleep 1', ignore_status=True)
        if "Performance counter stats for 'CPU(s) 0'" not in result2.stderr:
            nfail += 1
        else:
            self.log.info('perf recognized domain name in param=value format')

        # Testing feature: Check using domain which is not existing
        result2 = process.run(
            'perf stat -v -C 0 -e hv_24x7/HPM_0THRD_NON_IDLE_CCYC,\
            domain = 12,core = 1/ sleep 1', ignore_status=True)
        if "not supported" not in result2.stderr:
            nfail += 1
        else:
            self.log.info('perf listed non-existing domain as unsupported')

        # Check for all domains
        for domain in range(1, 6):
            result_perf = process.run(
                'perf stat -v -C 0 -e hv_24x7/HPM_0THRD_NON_IDLE_CCYC,\
                domain = %s,core = 1/ sleep 1' % domain, ignore_status=True)
            if "Performance counter stats for 'CPU(s) 0'" not in\
                    result_perf.stderr:
                nfail += 1
            else:
                self.log.info(
                    'perf recognized domain name in param=value\
                    format for all 6 domains')

        # Check for all domains
        # Testing feature: Fix usage with chip events

        event_out = process.run("cat %s/PM_XLINK_CYCLES" % EVENT_SYSFS)
        if "chip=?" in event_out.stdout:
            self.log.info('sysfs entry has chip entry')
        else:
            nfail += 1

        if os.path.exists("/sys/bus/event_source/devices/hv_24x7/format/chip"):
            self.log.info('chip file exists')
        else:
            nfail += 1

        # Check missing chip parameter
        output_chip_missing = process.run(
            'perf stat -C 0 -v -e hv_24x7/PM_XLINK_CYCLES,\
            domain = 1/ /bin/true', ignore_status=True)
        if "Required parameter 'chip' not specified"\
                not in output_chip_missing.stdout:
            nfail += 1
        else:
            self.log.info('perf detected chip parameter missing')

        output_chip = process.run(
            'perf stat -C 0 -v -e hv_24x7/PM_XLINK_CYCLES,\
            domain = 1,chip = 1/ /bin/true')
        if "Performance counter stats for" not in output_chip.stderr:
            nfail += 1

        if nfail != 0:
            raise self.error(
                'Failed to verify domain name suffix in event names')


if __name__ == "__main__":
    main()
