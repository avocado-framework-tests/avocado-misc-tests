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
dir = "/sys/bus/event_source/devices/cpu/events"
os.chdir(dir)


def f(x):
    return {
        'cpu-cycles': "0x1e",
        'stalled-cycles-frontend': "0x100f8",
        'stalled-cycles-backend': "0x4000a",
        'instructions': "0x02",
        'branch-instructions': "0x10068",
        'branch-misses': "0x400f6",
        'cache-references': "0x100ee",
        'cache-misses': "0x3e054",
        'L1-dcache-load-misses': "0x3e054",
        'L1-dcache-loads': "0x100ee",
        'L1-dcache-prefetches': "0xd8b8",
        'L1-dcache-store-misses': "0x300f0",
        'L1-icache-load-misses': "0x200fd",
        'L1-icache-loads': "0x4080",
        'L1-icache-prefetches': "0x408e",
        'LLC-load-misses': "0x300fe",
        'LLC-loads': "0x4c042",
        'LLC-prefetches': "0x4e052",
        'LLC-store-misses': "0x17082",
        'LLC-stores': "0x17080",
        'branch-load-misses': "0x400f6",
        'branch-loads': "0x10068",
        'dTLB-load-misses': "0x300fc",
        'iTLB-load-misses': "0x400fc"
    }.get(x, 9)


class test_generic_events(Test):
    """
    This tests Display event codes for Generic HW (PMU) events.
    This test will read content of each file from
    /sys/bus/event_source/devices/cpu/events
    and compare the raw event code for each generic event
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
                raise self.log.warn("This test is not\
                    supported on this kernel version")

    def test(self):
        nfail = 0

        for file in os.listdir(dir):
            myfile = open(file, "r")
            event_code = myfile.readline()
            val = f(file)
            if event_code.split('=', 2)[1].rstrip() != val:
                nfail += 1
            self.log.info(
                'FILE in /sys/bus/event_source/devices/cpu/events\
                    is %s' % file)
            self.log.info("Expected value: %s\n" % val)
            self.log.info('Got: %s' % event_code.split('=', 2)[1].rstrip())
        if nfail != 0:
            raise self.error('Failed to verify generic PMU event codes')

if __name__ == "__main__":
    main()
