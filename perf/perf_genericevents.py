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
import configparser
from avocado import Test
from avocado.utils import genio, cpu


class test_generic_events(Test):
    """
    This tests Display event codes for Generic HW (PMU) events.
    This test will read content of each file from
    /sys/bus/event_source/devices/cpu/events
    and compare the raw event code for each generic event
    :avocado: tags=perf,events
    """

    def read_generic_events(self):
        parser = configparser.ConfigParser()
        parser.optionxform = str
        parser.read(self.get_data('raw_code.cfg'))
        cpu_info = genio.read_file("/proc/cpuinfo")
        for line in cpu_info.splitlines():
            if 'revision' in line:
                self.rev = (line.split(':')[1])
                if '004b' in self.rev:
                    self.generic_events = dict(parser.items('POWER8'))
                elif '004e' in self.rev:
                    self.generic_events = dict(parser.items('POWER9'))
                elif '0080' in self.rev:
                    self.generic_events = dict(parser.items('POWER10'))
                else:
                    self.cancel("Processor is not supported: %s" % cpu_info)
        if 'amd' in cpu.get_vendor():
            for line in cpu_info.splitlines():
                if 'cpu family' in line:
                    self.family = int(line.split(':')[1])
            if self.family == 0x16:
               self.log.info("AMD Family: 16h")
               self.generic_events = dict(parser.items('AMD16h'))
            elif self.family >= 0x17:
               self.log.info("AMD Family: 17h")
               self.generic_events = dict(parser.items('AMD17h'))
            else:
               self.cancel("Unsupported AMD Family")

    def test(self):
        nfail = 0
        dir = "/sys/bus/event_source/devices/cpu/events"
        self.read_generic_events()
        os.chdir(dir)
        for file in os.listdir(dir):
            events_file = open(file, "r")
            event_code = events_file.readline()
            val = self.generic_events.get(file, 9)
            if 'umask' in event_code:
                self.log.debug("EventCode: %s" % event_code)
                event = (event_code.split('0x')[1]).rstrip(',umask=')
                umask = event_code.split('=', 2)[2].rstrip()
                raw_code = umask + event
            else:
                raw_code = event_code.split('=', 2)[1].rstrip()
            self.log.info('FILE in %s is %s' % (dir, file))
            if raw_code != val:
                nfail += 1
                self.log.info('FAIL : Expected value is %s but got '
                              '%s' % (val, raw_code))
            else:
                self.log.info('PASS : Expected value: %s and got '
                              '%s' % (val, raw_code))
        if nfail != 0:
            self.fail('Failed to verify generic PMU event codes')
