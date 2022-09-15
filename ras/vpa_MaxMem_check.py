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
from avocado.utils.software_manager.manager import SoftwareManager

IS_POWER_NV = 'PowerNV' in genio.read_file('/proc/cpuinfo').rstrip('\t\r\n\0')
IS_KVM_GUEST = 'qemu' in open('/proc/cpuinfo', 'r').read()


class Cpu_VpaData(Test):

    '''
    checks for cpu files and MaxMem
    '''

    @skipIf(IS_POWER_NV or IS_KVM_GUEST,
            "This test is supported on PowerVM environment")
    def setUp(self):
        if "ppc" not in os.uname()[4]:
            self.cancel("Test case is supported only on IBM Power Servers")

        detected_distro = distro.detect()
        if detected_distro.name not in ['rhel', 'SuSE']:
            self.cancel("Test case is supported only on RHEL and SLES")

        sm = SoftwareManager()
        if 'SuSE' in detected_distro.name:
            package = "powerpc-utils"
        else:
            package = "powerpc-utils-core"

        if not sm.check_installed(package) and not sm.install(package):
            self.cancel("Failed to install %s" % package)

    def test(self):

        self.log.info("===Checking for cpu VPA data and MaxMem==")
        cpu_count = len(os.listdir('/sys/kernel/debug/powerpc/vpa'))
        output = genio.read_file('/proc/powerpc/lparcfg').rstrip('\t\r\n\0')
        for line in output.splitlines():
            if 'MaxMem=' in line:
                maxmem = line.split('=')[1].strip()
        possible_cpus = "/sys/devices/system/cpu/possible"
        output = genio.read_file(possible_cpus).rstrip('\t\r\n\0')
        total_cpus = output.split('-')[1].strip()
        output = process.system_output(
            'lparstat -i', shell=True, ignore_status=True)
        for line in output.decode().splitlines():
            if 'Maximum Memory' in line:
                lmaxmem = line.split(':')[1].strip()
        if ((cpu_count == int(total_cpus)+1) and (maxmem == lmaxmem)):
            self.log.info(
                "Files are generated for all cpu's and maxmem values are same")
        else:
            self.fail("Files are not generated for all cpu's and"
                      " maxmem values are not same")
