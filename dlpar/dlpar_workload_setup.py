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
# Author: Samir Mulani <samir@linux.vnet.ibm.com>

"""
This is the DLPAR setup API's.
It was developed based on how we could test DLPAR with workload
EX: SMT, CPU folding, HTX.
"""
from dlpar_api.api import TestCase, TestException
from dlpar_api.config import TestConfig
from avocado.utils import process
import os
import sys


workload_flag = ""
CONFIG_FILE = TestConfig("config/tests.cfg")
__all__ = ['Dlpar_setup']


class Dlpar_setup(TestCase):

    # Command creater
    def cmd_builder(self, password, machine_add, linux_cmd):
        cmd = "nohup sshpass -p {} ssh {} '{}' &> dlpar_workload.out &".format(
            password, machine_add, linux_cmd)
        return cmd

    def Execute_cmd(self, cmd):
        try:
            process.run(cmd, ignore_status=True)
            return True
        except Exception:
            return False

    def __init__(self, log, workload_type):
        self.test_name = "Dedicated CPU " + workload_type + " workload"
        TestCase.__init__(self, log, self.test_name)
        self.log.info(
            "Inside {} workload Get test configuration \
                    ..!!".format(workload_type))
        # Get test configuration
        self.linux_1 = self.config.get('linux_primary',
                                       'name')
        self.linux_2 = self.config.get('linux_secondary',
                                       'name')
        self.linux_1_user = self.config.get('linux_primary',
                                            'user')
        self.linux_2_user = self.config.get('linux_secondary',
                                            'user')
        self.linux_1_pw = self.config.get('linux_primary',
                                          'passwd')
        self.linux_2_pw = self.config.get('linux_secondary',
                                          'passwd')
        # Command configuration
        self.workload_type = workload_type + ".sh"
        self.workload_local_dir = os.getcwd()
        self.run_cmd = "nohup bash  "
        self.remote_dir = "/tmp"
        self.primary_lpar = self.linux_1_user + "@" + \
            self.linux_1  # lpar-1 fully qualified address
        self.secondary_lpar = self.linux_2_user + "@" + \
            self.linux_2  # lpar-2 fully qualified address
        self.Workload_rem_path = self.remote_dir + "/" + \
            self.workload_type  # Path for remote workload script
        # Local workload path from config
        self.workload_local_dir = os.path.join(
            self.workload_local_dir, "config/" + self.workload_type)
        # Workload/process start/run command
        self.process_run = self.run_cmd + self.Workload_rem_path
        self.grep_cmd = "grep -i {}".format(self.workload_type)
        self.process_kill = 'ps aux | {} | awk "{{ print $2 }}" | \
                xargs kill'.format(
            self.grep_cmd)  # Workload/process stop/kill command

        # Workload remote file dir
        self.workload_remote_dir_1 = self.primary_lpar + ":" + self.remote_dir
        self.workload_remote_dir_2 = self.secondary_lpar + ":" + \
            self.remote_dir

        # Command preparation
        self.workload_run_cmd_1 = self.cmd_builder(
            self.linux_1_pw, self.primary_lpar, self.process_run)
        self.workload_run_cmd_2 = self.cmd_builder(
            self.linux_2_pw, self.secondary_lpar, self.process_run)
        self.workload_kill_cmd_1 = self.cmd_builder(
            self.linux_1_pw, self.primary_lpar, self.process_kill)
        self.workload_kill_cmd_2 = self.cmd_builder(
            self.linux_2_pw, self.secondary_lpar, self.process_kill)
        self.workload_init_1 = "sshpass -p {} scp -o \
                StrictHostKeyChecking=no {} {}".format(
            self.linux_1_pw, self.workload_local_dir,
            self.workload_remote_dir_1)
        self.workload_init_2 = "sshpass -p {} scp -o \
                StrictHostKeyChecking=no {} {}".format(
            self.linux_2_pw, self.workload_local_dir,
            self.workload_remote_dir_2)
        self.log.info(
            "{} Workload command preparation and configuration is \
                    done..!!".format(workload_type))

    def main_engine(self):
        '''
        First need to check machine is accessable or not using ping test
        '''

        self.primary = self.Execute_cmd("timeout 2s ping " + self.linux_1)
        self.secondary = self.Execute_cmd("timeout 2s ping " + self.linux_2)
        if (self.primary and self.secondary):
            self.log.info("Ping test for {} and {} machine is \
                    Succesfull..!!".format(
                self.linux_1, self.linux_2))
            # Copy the SMT or cpufolding shell script file to remote machine
            if (workload_flag == "smt" or workload_flag == "cpu_fold"):
                self.lpar_1_cpy_flag = self.Execute_cmd(self.workload_init_1)
                self.lpar_2_cpy_flag = self.Execute_cmd(self.workload_init_2)
                if (self.lpar_1_cpy_flag and self.lpar_2_cpy_flag):
                    self.log.info("The workload {} scripts are copied to the \
                            destination..!!".format(
                        self.workload_type))
                    self.workload_1_flag = self.Execute_cmd(
                        self.workload_run_cmd_1)
                    self.workload_2_flag = self.Execute_cmd(
                        self.workload_run_cmd_2)
                    if (self.workload_1_flag and self.workload_1_flag):
                        self.log.info("The workload {} scripts are running \
                                Succesfully..!!".format(
                            self.workload_type))
                    elif (not self.workload_1_flag):
                        self.log.error("Command {} failed".format(
                            self.workload_1_flag))
                    elif (not self.workload_1_flag):
                        self.log.error("Command {} failed".format(
                            self.workload_2_flag))
                else:
                    self.log.error("The workload {} scripts are not copied \
                            to the destination..!!". format(
                        self.workload_type))
                    if not self.lpar_1_cpy_flag:
                        self.log.error("Command {} failed".format(
                            self.workload_init_1))
                        raise TestException(self.lpar_1_cpy_flag)
                    if not self.lpar_2_cpy_flag:
                        self.log.error("Command {} failed".format(
                            self.workload_init_2))
                        raise TestException(self.lpar_2_cpy_flag)

            elif ("kill_process" in workload_flag):
                self.Execute_cmd(self.workload_kill_cmd_1)
                self.Execute_cmd(self.workload_kill_cmd_2)
                self.log.info("Process killed successfully..!!")
                self.log.info("command: {}".format(self.workload_kill_cmd_1))
                self.log.info("command: {}".format(self.workload_kill_cmd_2))
        if (not self.primary):
            self.log.error(
                "Ping test is failed for {} machine..!!".format(self.linux_1))
            raise TestException(self.linux_1)
        if (not self.secondary):
            self.log.error(
                "Ping test is failed for {} machine..!!".format(self.linux_2))
            raise TestException(self.linux_1)


# class HTX(TestCase):
#    pass

task_flag = []
if __name__ == "__main__":
    n = len(sys.argv)
    if (n == 2):
        if (sys.argv[1] == "smt" or sys.argv[1] == "cpu_fold"):
            workload_flag = sys.argv[1]
            log_file = "dlpar_" + "workload_" + workload_flag
            workload = Dlpar_setup(log_file, workload_flag)
            workload.main_engine()
        elif ("kill_process" in sys.argv[1]):
            task_flag = sys.argv[1].split(":")
            workload_flag = task_flag
            log_file = "dlpar_"+"workload_kill_" + task_flag[0]
            workload = Dlpar_setup(log_file, task_flag[0])
            workload.main_engine()
