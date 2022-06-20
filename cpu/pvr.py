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
# Author:  Pooja B Surya <pooja@linux.vnet.ibm.com>
# Update: Sachin Sant <sachinp@linux.vnet.ibm.com>

import os
import re

import configparser
from avocado import Test
from avocado.utils import process
from avocado.utils import genio
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils import distro


class pvr(Test):

    '''
    Processor version register(pvr) test case

    :avocado: tags=cpu,power
    '''

    def setUp(self):
        if "ppc" not in os.uname()[4]:
            self.cancel("supported only on Power platform")
        smm = SoftwareManager()
        detected_distro = distro.detect()
        parser = configparser.ConfigParser()
        parser.read(self.get_data("pvr.cfg"))
        if detected_distro.name == "Ubuntu":
            pkg = 'device-tree-compiler'
        else:
            pkg = 'dtc'
        if not smm.check_installed(pkg) and not smm.install(pkg):
            self.cancel("%s package is needed for the test to be run" % pkg)

        val = genio.read_file("/proc/cpuinfo")
        for line in val.splitlines():
            if 'revision' in line:
                rev = (line.split('revision')[1]).split()
                self.log.info("Revision: %s %s" % (rev, rev[1]))
                break
        if 'pSeries' in val and 'POWER8' in val:
            self.pvr_value = parser.get('PVR_Values', 'pvr_value_p8')
        elif 'PowerNV' in val and 'POWER8' in val:
            self.pvr_value = parser.get('PVR_Values', 'pvr_value_p8')
        elif 'pSeries' in val and 'POWER9' in val:
            if rev[1] == '1.2':
                self.pvr_value = parser.get('PVR_Values',
                                            'pvr_value_p9LPAR_1.2')
            elif rev[1] == '2.2':
                self.pvr_value = parser.get('PVR_Values',
                                            'pvr_value_p9LPAR_2.2')
            elif rev[1] == '2.3':
                self.pvr_value = parser.get('PVR_Values',
                                            'pvr_value_p9LPAR_2.3')
        elif 'PowerNV' in val and 'POWER9' in val:
            if rev[1] == '2.1':
                self.pvr_value = parser.get('PVR_Values', 'pvr_value_p9NV_2.1')
            elif rev[1] == '2.2':
                self.pvr_value = parser.get('PVR_Values', 'pvr_value_p9NV_2.2')
            elif rev[1] == '2.3':
                self.pvr_value = parser.get('PVR_Values', 'pvr_value_p9NV_2.3')
        elif 'pSeries' in val and 'POWER10' in val:
            if rev[1] == '1.0':
                self.pvr_value = parser.get('PVR_Values', 'pvr_value_p10_1')
            elif rev[1] == '2.0':
                self.pvr_value = parser.get('PVR_Values', 'pvr_value_p10_2')
        else:
            self.fail("Unsupported processor family")

    def test(self):
        self.log.info("====== Verifying CPU PVR entries =====")
        self.log.info(self.pvr_value)
        pvr_cpu = genio.read_file("/proc/cpuinfo")
        res = re.sub(' ', '', pvr_cpu)
        match = re.search(self.pvr_value, res)
        self.log.info('self.pvr_value = %s, res = %s' % (self.pvr_value, res))
        if match:
            self.log.info("PVR from /proc/cpuinfo for the system is correct")
        else:
            self.fail("PVR from /proc/cpuinfo for the system is not correct")
        pvr_dtc = process.run("dtc -I fs /proc/device-tree -O dts |grep %s | "
                              "head -1" % self.pvr_value, shell=True,
                              ignore_status=True)
        if not pvr_dtc.exit_status:
            self.log.info("PVR from device tree for the system is correct")
        else:
            self.fail("PVR from device tree for the system is not correct")
