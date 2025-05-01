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
# Copyright (C) 2024 Advanced Micro Devices, Inc.
# Author: Athira Rajeev<atrajeev@linux.vnet.ibm.com>
# Author: Shriya Kulkarni <shriyak@linux.vnet.ibm.com>
# Author: Ayush Jain <ayush.jain3@amd.com>

import os
import configparser
from avocado import Test
from avocado.utils import cpu, process


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
        # Equivalent Python code for bash command
        # "journalctl -k|grep -i performance"
        pmu_registered = process.get_command_output_matching("journalctl -k",
                                                             "performance")
        pmu_event_mapping = {'generic_compat': 'GENERIC_COMPAT_PMU',
                             'isav3': 'GENERIC_COMPAT_PMU', 'power8': 'POWER8',
                             'power9': 'POWER9', 'power10': 'POWER10',
                             'power11': 'POWER10'}
        for pmu, event_type in pmu_event_mapping.items():
            if pmu in pmu_registered[0].lower():
                self.generic_events = dict(parser.items(event_type))
                return
        self.cancel("Processor is not supported: %s" % pmu_registered)

        self.arch = cpu.get_arch()
        self.vendor = cpu.get_vendor()
        if 'amd' in self.vendor:
            self.family = cpu.get_family()
            if self.family == 0x16:
                self.log.info("AMD Family: 16h")
                self.generic_events = dict(parser.items('AMD16h'))
            elif self.family >= 0x17:
                self.amd_zen = cpu.get_x86_amd_zen()
                if self.amd_zen is None:
                    self.cancel("Unsupported AMD ZEN")
                self.log.info(f"AMD Family: {self.family} ZEN{self.amd_zen}")
                if f'AMDZEN{self.amd_zen}' in parser.keys() is not None:
                    self.generic_events = dict(parser.items(f'AMDZEN{self.amd_zen}'))
                else:
                    self.cancel(f"AMD ZEN{self.amd_zen} raw_code cfg not found")
            else:
                self.cancel("Unsupported AMD Family")

    def hex_to_int(self, input):
        return int(input, 0)

    def test(self):
        nfail = 0
        dir = "/sys/bus/event_source/devices/cpu/events"
        self.read_generic_events()
        os.chdir(dir)
        for file in os.listdir(dir):
            events_file = open(file, "r")
            event_code = events_file.readline()
            val = self.generic_events.get(file)
            if val is None:
                continue
            if 'umask' in event_code:
                umask = event_code.split('=', 2)[2].rstrip()
                if self.arch == "x86_64" and 'amd' in self.vendor:
                    umask = self.hex_to_int(umask)
                    event = self.hex_to_int(event_code.split('=', 2)[1].rstrip(',umask='))
                    raw_code = (event & 0xff) | (umask << 8) | ((event & 0xf00) << 24)
                else:
                    event = (event_code.split('0x')[1]).rstrip(',umask=')
                    raw_code = self.hex_to_int(umask + event)
            else:
                raw_code = self.hex_to_int(event_code.split('=', 2)[1].rstrip())

            self.log.info('FILE in %s is %s' % (dir, file))
            if raw_code != self.hex_to_int(val):
                nfail += 1
                self.log.info('FAIL : Expected value is %s(hex: %s) but got '
                              '%s' % (self.hex_to_int(val), val, raw_code))
            else:
                self.log.info('PASS : Expected value is %s(hex: %s) and got '
                              '%s' % (self.hex_to_int(val), val, raw_code))
        if nfail != 0:
            self.fail('Failed to verify generic PMU event codes')
