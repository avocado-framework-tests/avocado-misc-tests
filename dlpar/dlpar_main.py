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
from avocado import skipUnless
import configparser
from avocado.utils import wait


list_payload = ["pri_machine", "cfg_cpu_per_proc", "log_file_level",
                "log_console_level", "hmc_name", "hmc_machine",
                "hmc_partition", "hmc_user", "hmc_passwd", "sec_name",
                "sec_machine",
                "sec_partition", "sec_user", "sec_passwd",
                "ded_quantity_to_test",
                "ded_sleep_time", "ded_iterations", "ded_min_procs",
                "ded_desired_procs",
                "ded_max_procs", "ded_mode", "vir_quantity_to_test",
                "vir_sleep_time", "vir_iterations",
                "cpu_quantity_to_test", "cpu_sleep_time", "cpu_iterations",
                "cpu_min_procs",
                "cpu_desired_procs", "cpu_max_procs", "cpu_min_proc_units",
                "cpu_desired_proc_units",
                "cpu_max_proc_units", "cpu_sharing_mode",
                "mem_quantity_to_test", "mem_sleep_time",
                "mem_iterations", "mem_mode", "mem_linux_machine",
                "mem_min_mem", "mem_desired_mem", "mem_max_mem"]

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

    def config_creation(self, config_payload):
        """
        Creating configuration file for DLPAR opertaion.
        """
        config = configparser.ConfigParser()
        count = 0
        delete = []
        self.conf_payload = config_payload
        section_name = ["machine_cfg", "cpu_unit", "dedicated_cpu", "hmc",
                        "log", "memory", "linux_primary", "linux_secondary",
                        "virtual_cpu"]
        for section in section_name:
            config.add_section(section)
            if count != 0:
                for item in delete:
                    del self.conf_payload[item]
                delete.clear()
            count += 1
            for key, value in self.conf_payload.items():
                key_dup = key
                b = ["hmc_", "pri_", "sec_", "ded_",
                     "mem_", "cpu_", "log_", "vir_"]
                number_list = [x for x in b if x in key_dup]
                if number_list:
                    key_dup = key_dup.replace(number_list[0], "")
                    config.set(section, key_dup, str(value))
                else:
                    config.set(section, key, str(value))
                if key in ["cfg_cpu_per_proc", "cpu_sleep_time",
                           "ded_sleep_time", "hmc_user", "log_file_level",
                           "mem_sleep_time", "pri_partition", "sec_user"]:
                    delete.append(key)
                    break
                delete.append(key)

        with open(r"config/tests.cfg", 'w') as configfile:
            config.write(configfile)
            self.log.info("Successfully written config file--!!")

    @skipUnless(IS_POWER_VM,
                "DLPAR test is supported only on PowerVM platform")
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
        pri_data = {"pri_partition": self.pri_partition,
                    "pri_name": self.pri_name}
        self.res = {list_payload[i]: self.list_data[i]
                    for i in range(len(list_payload))}
        self.res = dict(list(pri_data.items()) + list(self.res.items()))
        key = "hmc_name"
        if key in self.res.keys():
            self.res.update({key: self.hmc_ip})
        self.log.info("Calling Config file creation method--!!")
        sorted_payload = dict(sorted(self.res.items()))
        self.config_creation(sorted_payload)

    def dlpar_engine(self):
        '''
        Call and create the log file as per dlpar test case
        Ex: With and without workload(smt, cpu_fold etc)
        '''
        test_cmd = ""
        dlpar_type_flag = ""
        if self.lpar_mode == 'dedicated':
            self.log.info("Dedicated Lpar....")
            self.test_case = self.params.get('test_case', default='cpu')
            self.log.info("TestCase: %s" % self.test_case)
            if self.test_case == 'cpu':
                test_mode = "DED {}: Calling dedicated_cpu.py".format(
                    self.lpar_mode)
                test_cmd = './dedicated_cpu.py'
            elif self.test_case == 'mem':
                test_mode = "DED {}: Calling memory.py".format(self.lpar_mode)
                test_cmd = './memory.py'

        elif self.lpar_mode == 'shared':
            self.log.info("Shared Lpar.....")
            self.test_case = self.params.get('test_case', default='cpu')
            self.log.info("TestCase: %s" % self.test_case)
            if self.test_case == 'cpu':
                self.log.info("SHR: Calling cpu_unit.py")
                test_cmd = './cpu_unit.py'
            elif self.test_case == 'mem':
                self.log.info("SHR: Calling memory.py")
                test_cmd = './memory.py'

        if test_cmd != "":
            self.run_cmd(test_cmd)

    def test_dlpar(self):
        """
        Calling dedicated and shared mode dlpar test cases (CPU, Memory etc.)
        """
        self.dlpar_engine()
