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

import os
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
        kernel_Version = re.match(r"[\d+-.]+\d", os.uname()[2]).group()
        kernel_to_compare = "3.10.0.419"

        result_comparison = 0

        for cur_ker, supported_ker in zip(kernel_Version.split(".")[:4],
                                          kernel_to_compare.split(".")[:4]):
            if cur_ker < supported_ker:
                raise self.log.warn(
                    "This test is not supported on this kernel version")

    def test(self):
        nfail = 0
        perf_stat = "perf stat -v -C 0 -e hv_24x7/HPM_0THRD_NON_IDLE_CCYC"
        event_sysfs = "/sys/bus/event_source/devices/hv_24x7"

        # Check if this is a guest
        # 24x7 is not suported on guest
        cpu_output = process.run("cat /proc/cpuinfo")
        if "emulated by" in cpu_output.stdout:
            self.skipTest("This test is not supported on guest")

        # Check if 24x7 is present
        if os.path.exists("%s" % event_sysfs):
            self.log.info('hv_24x7 present')
        else:
            raise self.error("%s doesn't exist.This feature is\
                             supported on only lpar" % event_sysfs)

        # Performance measurement has to be enabled in lpar through BMC
        # Check if its enabled
        # Refer https://bugzilla.linux.ibm.com/show_bug.cgi?id=139404#c21
        result_perf = process.run("%s,domain = 2,core = 1/ sleep 1"
                                  % perf_stat, ignore_status=True)
        if "You may not have permission to collect stats" in\
                result_perf.stderr:
            raise self.error("Please enable lpar to allow\
                collecting the 24x7 counters info")

        # Testing feature: Display domain indices in sysfs
        # Part of commit d34171e
        #EVENT_SYSFS = "/sys/bus/event_source/devices/hv_24x7/events"
        pattern = re.compile('1: Physical Chip\n2: Physical Core\n\
            3: VCPU Home Core\n4: VCPU Home Chip\n\
            5: VCPU Home Node\n6: VCPU Remote Node')
        result = process.run('cat %s/interface/domains' % event_sysfs)
        Result_search = pattern.search(result.stdout)
        if Result_search:
            self.log.info('Displayed domain indices in sysfs')
        else:
            nfail += 1
            self.log.info('FAIL : Unable to display domain indices in sysfs')

        # Testing feature: Eliminate domain suffix in event name
        # Verify No __PHYS_CORE or VCPU* suffixes in event name
        search_suffix = process.run('ls %s/events |grep -E\
            __PHYS_CORE' % event_sysfs, ignore_status=True)
        if search_suffix.stdout:
            nfail += 1
            self.log.info('FAIL : Found __PHYS_CORE  suffixes in event name')
        else:
            self.log.info('No __PHYS_CORE  suffixes in event name')

        search_suffix = process.run('ls %s/events |grep\
            -E VCPU' % event_sysfs, ignore_status=True)
        if search_suffix.stdout:
            nfail += 1
            self.log.info('FAIL : Found VCPU  suffixes in event name')
        else:
            self.log.info('No VCPU  suffixes in event name')

        # Using hv_24x7/HPM_0THRD_NON_IDLE_CCYC__PHYS_CORE should fail
        result1 = process.run('%s__PHYS_CORE,core=1/ sleep\
            1' % perf_stat, ignore_status=True)
        if "Invalid event/parameter" not in result1.stdout:
            nfail += 1
            self.log.info('FAIL : perf unable to recognize hv_24x7/\
                HPM_0THRD_NON_IDLE_CCYC__PHYS_CORE has invalid event')
        else:
            self.log.info('perf recognized Invalid event')

        # Check if missing parameter is reported
        result1 = process.run(
            '%s/ sleep 1' % perf_stat, ignore_status=True)
        if "invalid or unsupported event" not in result1.stderr or "Required\
                parameter 'domain' not specified" not in result1.stdout:
            nfail += 1
            self.log.info('FAIL : Domain is not specified,\
                perf unable to recognize it has invalid event')
        else:
            self.log.info('perf recognized unsupported event')

        # Check param=value format works
        result2 = process.run(
            '%s,domain=2,core=1/ sleep 1' % perf_stat, ignore_status=True)
        if "Performance counter stats for 'CPU(s) 0'" not in result2.stderr:
            nfail += 1
            self.log.info('FAIL : perf unable to recognize domain\
                name in param=value format')
        else:
            self.log.info('perf recognized domain name in param=value format')

        # Testing feature: Check using domain which is not existing
        result2 = process.run(
            '%s,domain=12,core=1/ sleep 1' % perf_stat, ignore_status=True)
        if "not supported" not in result2.stderr:
            nfail += 1
            self.log.info('FAIL : domain does not exist but perf\
                listed has supported')
        else:
            self.log.info('perf listed non-existing domain as unsupported')

        # Check for all domains
        for domain in range(1, 6):
            result_perf = process.run('%s,domain = %s,core = 1/ sleep\
                1' % (perf_stat, domain), ignore_status=True)
            if "Performance counter stats for 'CPU(s) 0'" not in\
                    result_perf.stderr:
                nfail += 1
                self.log.info('FAIL : perf unable to recognize domain name\
                    in param=value format for all domains')
            else:
                self.log.info('perf recognized domain name in param=value\
                    format for all 6 domains')

        # Check for all domains
        # Testing feature: Fix usage with chip events

        event_out = process.run("cat %s/events/PM_XLINK_CYCLES" % event_sysfs)
        if "chip=?" in event_out.stdout:
            self.log.info('sysfs entry has chip entry')
        else:
            nfail += 1
            self.log.info('FAIL : sysfs does not have chip entry')

        if os.path.exists("%s/format/chip" % event_sysfs):
            self.log.info('chip file exists')
        else:
            nfail += 1
            self.log.info('FAIL : chip file does not exist')

        # Check missing chip parameter
        output_chip_missing = process.run('perf stat -C 0 -v -e hv_24x7/\
            PM_XLINK_CYCLES,domain=1/ /bin/true', ignore_status=True)
        if "Required parameter 'chip' not specified" not in\
                output_chip_missing.stdout:
            nfail += 1
            self.log.info('FAIL : perf unable to detect chip parameter\
                missing')
        else:
            self.log.info('perf detected chip parameter missing')

        output_chip = process.run(
            'perf stat -C 0 -v -e hv_24x7/PM_XLINK_CYCLES,domain = 1,\
                chip = 1/ /bin/true')
        if "Performance counter stats for" not in output_chip.stderr:
            nfail += 1
            self.log.info('FAIL : performance counter stats for missing')

        if nfail != 0:
            raise self.error(
                'Failed to verify domain name suffix in event names')


if __name__ == "__main__":
    main()
