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
# Copyright: 2023 IBM
# Author: Samir A Mulani <samir@linux.vnet.ibm.com>

import multiprocessing
import os
import re
import time
from avocado import Test
from avocado.utils import process, cpu, distro
from avocado.utils.software_manager.manager import SoftwareManager


class load_balancer(Test):
    """
    _test summary_
    -> This experiment entails executing a workload and subsequently
        analyzing how a load balancer distributes the workload among
        the available CPU cores and validate the functionality
        of load balancer.

    Prerequisite:
    -> Machine should be SMT capable
    To install SMT state tool we need below prerequisite,
    1. RHEL distro version should greter than 8 and distro release
        should not less than 4
    2. SUSE supported only after SLES15 SP3.
    -> Python pandas package need to be installed
    Below packages to be installed to run the test,
    -> powerpc-utils, sysstat, stress-ng.
    """

    def setUp(self):
        self.total_cpus = 0
        self.current_totalcpus = 0
        file_path = "/tmp/mpstat.log"
        if os.path.exists(file_path):
            os.remove(file_path)
        if 'ppc' not in distro.detect().arch:
            self.cancel("Processor is not powerpc")
        sm = SoftwareManager()
        self.detected_distro = distro.detect()
        deps = ["powerpc-utils", "sysstat", "stress-ng"]
        for package in deps:
            if not sm.check_installed(package) and not sm.install(package):
                self.cancel('%s is needed for the test to be run' % package)
        smt_op = process.run("ppc64_cpu --smt", shell=True,
                             ignore_status=True).stderr.decode("utf-8")
        if "is not SMT capable" in smt_op:
            self.cancel("Machine is not SMT capable, skipping the test")
        self.no_threads = self.params.get("no_threads", default=4)
        self.cpu_cycles = self.params.get("cpu_cycles", default=10000000)
        self.capacity = self.params.get("capacity", default=30)
        distro_name = self.detected_distro.name
        distro_ver = self.detected_distro.version
        distro_rel = self.detected_distro.release
        if distro_name == "rhel":
            if (distro_ver == "7" or
                    (distro_ver == "8" and distro_rel < "4")):
                self.cancel("smtstate tool is supported only after RHEL8.4")
        elif distro_name == "SuSE":
            if (distro_ver == "12" or (distro_ver == "15" and
                                       distro_rel < 3)):
                self.cancel("smtstate tool is supported only after \
                        SLES15 SP3")
        else:
            self.cancel("Test case is supported only on RHEL and SLES")

    def run_workload(self, no_threads, cpu_cycles, capacity):
        """
        Run the stress-ng workload
        """
        cmd = 'nohup stress-ng --cpu %s --cpu-ops %s -l %s &> \
                /tmp/stress-ng.txt &' % (no_threads, cpu_cycles, capacity)
        process.run(cmd, shell=True)
        self.log.info("stress-ng workload started running successfully--!!")

    def mpstat_analyzer(self, on_cpu_count, smt_mode, core):
        """
        This function basically capture the mpstat command
        output for cpu utilization and validate the mpstat data.
        """
        load_balancer_flag = False
        load_balancer = []
        cpu_list = []
        usr_list = []
        idle_list = []
        new_user_list = []
        avg_utilization = 0
        log_file = '/tmp/mpstat.log'

        cmd = 'mpstat -P ALL 1 1 | awk \'$3 >= 0 && $4 > 5\' &> %s' % (
            log_file)
        process.run(cmd, shell=True)
        lines = []
        with open("/tmp/mpstat.log", "r") as file:
            lines = file.readlines()
        filtered_lines = [line.strip().split() for line in lines if re.match(
            "^[0-9][0-9]:[0-9][0-9]:[0-9][0-9]", line)]
        for columns in filtered_lines:
            cpu_list.append(columns[2])
            usr_list.append(columns[3])
            idle_list.append(columns[12])

        result_dict = {key: (value1, value2) for key, value1,
                       value2 in zip(cpu_list, usr_list, idle_list)}
        for idle in idle_list:
            data = 100 - int(float(idle))
            new_user_list.append(data)
        if len(cpu_list) > 0:
            self.log.info("CPU\t%user\t%idle")
            self.log.info("----------------------")
            for key, (value1, value2) in result_dict.items():
                self.log.info(f"{key}\t{value1}\t{value2}")
            count = 0
            avg_expected_utilization = (
                self.no_threads/self.current_totalcpus) * self.capacity
            if avg_expected_utilization > self.capacity:
                avg_expected_utilization = self.capacity
            utilization_bck = {}
            count = 0
            for utilization in new_user_list:
                if int(float(utilization)) == int(self.capacity) or \
                        int(float(utilization)) >= \
                        (int(self.capacity) - 2):
                    load_balancer_flag = True
                    load_balancer.append(load_balancer_flag)
                else:
                    utilization_bck[cpu_list[count]] = int(float(utilization))
                    if 'all' in utilization_bck:
                        del utilization_bck['all']
                    else:
                        load_balancer_flag = False
                        load_balancer.append(load_balancer_flag)
                count += 1
            avg_utilization = int(float(avg_expected_utilization))
            if ((new_user_list[0] - 4) <= avg_utilization <=
                    (new_user_list[0] + 4)) or \
                    (False not in load_balancer):
                self.log.info("Load -balancer balnced load across \
                        the available cpu for smt mode \
                        %s core's: %s ", smt_mode, core)
            else:
                self.fail("Load -balancer is failed to balance load across \
                        the available cpu for smt mode \
                        %s core's: %s utilization: %s", smt_mode, core,
                          utilization_bck)

    def test(self):
        """
        In this funtion basically we are online and offline the
        cores and cpu's in sequence,
        1.Running the stress-ng workload.
        2.changing the SMT modes.
        3.Validating the mpstat command output for CPU utilization
        as per SMT mode.
        """
        mpstat_dir = self.logdir + "/mpstat"
        os.mkdir(mpstat_dir)
        self.mpstat_log_file = mpstat_dir + "/mpstat_dump.log"
        process.run('ppc64_cpu --cores-on=all', shell=True)
        process.run('ppc64_cpu --smt=on', shell=True)
        totalcpus = int(multiprocessing.cpu_count())
        total_cores = totalcpus//8
        if (self.no_threads == ""):
            self.no_threads = totalcpus + 1
        self.log.info("Total no of cores %d", total_cores)
        self.log.info("Total no of online cores %d", totalcpus)
        self.run_workload(self.no_threads, self.cpu_cycles, self.capacity)
        cpu_controller = ["2", "4", "6", "on", "off"]
        for core in range(1, total_cores+1):
            cmd = "ppc64_cpu --cores-on=%s" % (core)
            self.log.info("Total no of online core's %d", core)
            process.run(cmd, shell=True)
            for smt_mode in cpu_controller:
                cmd = "ppc64_cpu --smt={}".format(smt_mode)
                self.log.info("smt mode %s", smt_mode)
                process.run(cmd, shell=True)
                self.mpstat_log_file = mpstat_dir + \
                    "/mpstat_core["+str(core)+"]"+"_smt["+str(smt_mode)+"]"
                cmd = "nohup mpstat -P ALL -u 1 &> %s &" % (
                    self.mpstat_log_file)
                process.run(cmd, shell=True)
                time.sleep(10)
                lscpu_payload = "lscpu > /tmp/lscpu_" + \
                    str(core) + "_" + str(smt_mode)
                process.run(lscpu_payload, shell=True)
                on_cpu_count = int(multiprocessing.cpu_count())
                self.log.info("After SMT mode %s no of \
                        online cpu's %d", smt_mode, on_cpu_count)
                online_cpu = cpu.online_count()
                self.current_totalcpus = int(multiprocessing.cpu_count())
                self.mpstat_analyzer(on_cpu_count, smt_mode, core)
                process.run("ps aux | grep '[m]pstat' | grep -v grep | awk \
                '{print $2}' | xargs kill -9", ignore_status=True,
                            shell=True)

    def tearDown(self):
        """
        1. Restoring the system with turning on all the core's and smt on.
        2. Killing the stress-ng workload
        """
        process.run("ps aux | grep '[m]pstat' | grep -v grep | awk \
                '{print $2}' | xargs kill -9", ignore_status=True,
                    shell=True)
        process.run('ppc64_cpu --cores-on=all', shell=True)
        process.run('ppc64_cpu --smt=on', shell=True)
        process.run("ps aux | grep 'stress-ng' | grep -v grep | awk \
                '{print $2}' | xargs kill -9", ignore_status=True,
                    shell=True)
        if os.path.exists("/tmp/stress-ng.txt"):
            os.remove("/tmp/stress-ng.txt")
