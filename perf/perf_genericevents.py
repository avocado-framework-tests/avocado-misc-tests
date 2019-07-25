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
import ConfigParser
from avocado import Test
from avocado import main


class test_generic_events(Test):
    """
    This tests Display event codes for Generic HW (PMU) events.
    This test will read content of each file from
    /sys/bus/event_source/devices/cpu/events
    and compare the raw event code for each generic event
    :avocado: tags=perf,events
    """

    def read_generic_events(self):
        parser = ConfigParser.ConfigParser()
        parser.optionxform = str
        parser.read(self.get_data('raw_code.cfg'))
        cpu_info = open('/proc/cpuinfo', 'r').read()
        if 'POWER8' in cpu_info:
            self.generic_events = dict(parser.items('POWER8'))
        elif 'POWER9' in cpu_info:
            self.generic_events = dict(parser.items('POWER9'))

    def test(self):
        nfail = 0
        dir = "/sys/bus/event_source/devices/cpu/events"
        self.read_generic_events()
        os.chdir(dir)
        for file in os.listdir(dir):
            events_file = open(file, "r")
            event_code = events_file.readline()
            val = self.generic_events.get(file, 9)
            raw_code = event_code.split('=', 2)[1].rstrip()
            if raw_code != val:
                nfail += 1
                self.log.warn('FAIL : Expected value is %s but got'
                              '%s' % (val, raw_code))
            self.log.info('FILE in %s is %s' % (dir, file))
            self.log.info('PASS : Expected value: %s and got'
                          '%s' % (val, raw_code))
        if nfail != 0:
            self.fail('Failed to verify generic PMU event codes')


if __name__ == "__main__":
    main()
