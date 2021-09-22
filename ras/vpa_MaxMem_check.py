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
# Copyright: 2021 IBM
# Author: Shirisha Ganta <shirisha.ganta1@ibm.com>

import os

from avocado import Test
from avocado.utils import process, genio, distro
from avocado import skipIf

IS_POWER_NV = 'PowerNV' in genio.read_file('/proc/cpuinfo').rstrip('\t\r\n\0')


class Cpu_VpaData(Test):

    '''
    checks for cpu files and MaxMem
    '''

    @skipIf(IS_POWER_NV, "This test is supported on PowerVM environment")
    def setUp(self):
        detected_distro = distro.detect()
        if detected_distro.name not in ['rhel', 'SuSE']:
            self.cancel("Test case is supported only on RHEL and SLES")
        
    def test(self):

        self.log.info("===Checking for cpu VPA data and MaxMem==")
        cpu_count = len(os.listdir('/sys/kernel/debug/powerpc/vpa'))
        output = genio.read_file('/proc/powerpc/lparcfg').rstrip('\t\r\n\0')
        for line in output.splitlines():
            if 'MaxMem=' in line:
            	maxmem = line.split('=')[1].strip()
        output = process.system_output('lscpu', shell=True, ignore_status=True)
        for line in output.decode().splitlines():
            if line.startswith('CPU'):
            	total_cpus = line.split(':')[1].strip()
        output = process.system_output('lparstat -i',shell=True, ignore_status=True)
        for line in output.decode().splitlines():
            if 'Maximum Memory' in line:
            	lmaxmem = line.split(':')[1].strip()
        if ((cpu_count == int(total_cpus)) and (maxmem == lmaxmem)):
            self.log.info("Files are generated for all cpu's and maxmem values are same")
        else:
            self.fail("Files are not generated for all cpu's and maxmem values are not same")
