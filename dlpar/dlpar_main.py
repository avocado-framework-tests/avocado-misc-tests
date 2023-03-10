#!/usr/bin/env python
#
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
# Copyright: 2022 IBM
# Author: Kalpana Shetty <kalshett@in.ibm.com>
# Author(Modified): Samir A Mulani <samir@linux.vnet.ibm.com>

import os

from avocado import Test
from avocado.utils import process
from avocado.utils import wait
from dlpar_api.api import DedicatedCpu, CpuUnit, Memory
list_payload = ["cfg_cpu_per_proc", "hmc_manageSystem", "hmc_user",
                "hmc_passwd", "target_lpar_hostname", "target_partition",
                "target_user", "target_passwd", "ded_quantity_to_test",
                "sleep_time", "iterations", "vir_quantity_to_test",
                "cpu_quantity_to_test", "mem_quantity_to_test",
                "mem_linux_machine"]


IS_POWER_VM = 'pSeries' in open('/proc/cpuinfo', 'r').read()
dlpar_type_flag = ""


class DlparTests(Test):

    """
    Dlpar CPU/MEMORY  tests - ADD/REMOVE/MOVE
    """

    def run_cmd(self, test_cmd, dlpar_type_flag=""):
        os.chmod(test_cmd, 0o755)
        if dlpar_type_flag != "":
            test_cmd = test_cmd + " " + dlpar_type_flag
        result = process.run(test_cmd, shell=True)
        errors = 0
        warns = 0
        for line in result.stdout.decode().splitlines():
            if 'FAILED' in line:
                self.log.info(line)
                errors += 1
            elif 'WARNING' in line:
                self.log.info(line)
                warns += 1

        if errors == 0 and warns > 0:
            self.warn('number of warnings is %s', warns)

        elif errors > 0:
            self.log.warn('number of warnings is %s', warns)
            self.fail("number of errors is %s" % errors)

    @staticmethod
    def get_mcp_component(component):
        '''
        probes IBM.MCP class for mentioned component and returns it.
        '''
        for line in process.system_output('lsrsrc IBM.MCP %s' % component,
                                          ignore_status=True, shell=True,
                                          sudo=True).decode("utf-8") \
                                                    .splitlines():
            if component in line:
                return line.split()[-1].strip('{}\"')
        return ''

    @staticmethod
    def get_partition_name(component):
        '''
        get partition name from lparstat -i
        '''
        for line in process.system_output('lparstat -i', ignore_status=True,
                                          shell=True,
                                          sudo=True).decode("utf-8") \
                                                    .splitlines():
            if component in line:
                a = line.split(':')[-1].strip()
                print(a)
                return a
        return ''

    def setUp(self):
        self.list_data = []
        self.lpar_mode = self.params.get('lp_mode', default='dedicated')
        for i in list_payload:
            self.data = self.params.get(i, default='')
            self.list_data.append(self.data)

        # Get HMC IP
        self.hmc_ip = wait.wait_for(
            lambda: self.get_mcp_component("HMCIPAddr"), timeout=30)

        # Primary lpar details
        self.pri_partition = self.get_partition_name("Partition Name")
        self.pri_name = self.get_partition_name("Node Name")
        pri_data = {"src_partition": self.pri_partition,
                    "src_name": self.pri_name,
                    "hmc_name": self.hmc_ip}
        self.res = {list_payload[i]: self.list_data[i]
                    for i in range(len(list_payload))}
        self.res = dict(list(pri_data.items()) + list(self.res.items()))
        self.log.info("Calling Config file creation method--!!")
        self.sorted_payload = dict(sorted(self.res.items()))
        self.iterations = self.sorted_payload.get('iterations')

    def test_cpu_dlpar(self):

        if self.lpar_mode == 'dedicated':
            Ded_obj = DedicatedCpu(self.sorted_payload,
                                   log='dedicated_cpu.log')
            for i in range(self.iterations):
                Ded_obj.add_ded_cpu()
                Ded_obj.move_ded_cpu()
                Ded_obj.add_ded_cpu()
                Ded_obj.rem_ded_cpu()
        elif self.lpar_mode == 'shared':
            Sha_obj = CpuUnit(self.sorted_payload, log='cpu_unit.log')
            for i in range(self.iterations):
                Sha_obj.mix_proc_ope()

    def test_mem_dlpar(self):
        Mem_obj = Memory(self.sorted_payload, log='memory.log')
        for i in range(self.iterations):
            Mem_obj.mem_add()
            Mem_obj.mem_rem()
            Mem_obj.mem_move()
            # Mem_obj.mem_mix_ope()
