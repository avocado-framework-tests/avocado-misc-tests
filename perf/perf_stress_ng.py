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
# Copyright: 2023 IBM
# Author: kajol Jain<kjain@linux.ibm.com>
#         Manvanthara Puttashakar <manvanth@linux.vnet.ibm.com>
#         R Nageswara Sastry <rnsastry@linux.ibm.com>

import os
import re
import psutil
import time
import glob
from avocado.utils import process, genio
from avocado import Test
from avocado.utils import process, build, archive, dmesg
from avocado.utils.software_manager.manager import SoftwareManager


class Stressng(Test):

    """
    Perf record with CPU stress
    :source: git://kernel.ubuntu.com/cking/stress-ng.git
    :param cpu_per: CPU Percentage to load
    """

    def setUp(self):
        smm = SoftwareManager()
        self.timeout = self.params.get('timeout', default=1)
        self.cpu_per = self.params.get("cpu_load", default='10')
        self.profile_dur = int(self.params.get("profile_duration", default=1))
        run_type = self.params.get('type', default='distro')
        dmesg.clear_dmesg()

        deps = ['gcc', 'perf']
        if run_type == "upstream":
            asset_url = 'https://github.com/ColinIanKing/stress-ng/archive/master.zip'
            tarball = self.fetch_asset('stressng.zip', locations=[
                                       asset_url], expire='7d')
            archive.extract(tarball, self.workdir)
            sourcedir = os.path.join(self.workdir, 'stress-ng-master')
            os.chdir(sourcedir)
            result = build.run_make(sourcedir, process_kwargs={
                                    'ignore_status': True})
            for line in str(result).splitlines():
                if 'error:' in line:
                    self.cancel(
                        "Build Failed, Please check the build logs for details !!")
            build.make(sourcedir, extra_args='install')
        elif run_type == "distro":
            deps.extend(['stress-ng'])

        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

    def is_process_running(self, process_name):
        """
        Verifies if a process is running
        :param process_name: name of the process
        """
        for proc in psutil.process_iter(['pid', 'name']):
            if process_name in proc.info['name']:
                return True
        return False

    def kill_process_by_name(self, process_name):
        """
        Kills the process
        :param process_name: name of the process
        """
        for proc in psutil.process_iter(['pid', 'name']):
            if process_name in proc.info['name']:
                try:
                    process = psutil.Process(proc.info['pid'])
                    process.terminate()
                    self.log.info(f"Process  %s terminated" % (process_name))
                except psutil.NoSuchProcess:
                    self.log.info(f"Process  %s not found" % (process_name))
                    return

    def vmstat_result(self, filename):
        """
        Captures the vmstat from the log file
        :param filename: log file name
        """
        var = 0
        total_sum = 0
        result = 0
        # Equivalent Python code for bash command
        # "awk '!/procs|swpd/ && NF > 0 { print $15 }' %s > /tmp/data1.txt" % filename
        exclude_patterns = re.compile(r'procs|swpd')
        output = genio.read_all_lines(filename)
        for line in output:
            if not exclude_patterns.search(line) and len(line.split()) > 0:
                fields = line.split()
                if len(fields) >= 15:
                    if fields[14].isnumeric():
                        if var < 10:
                            var += 1
                            total_sum = total_sum + int(fields[14])
                        else:
                            total_sum = total_sum + int(fields[14])
                            result = 100 - total_sum // 11
                            var = 0
                            total_sum = 0
        self.log.info(f" vmstat data  => %s" % result)
        return result

    def calculate_average(self, iterations):
        """
        Calculate the average of the data received per iteration
        :param iterations: variable holding data points
        """

        total_sum = sum(iterations.values())
        return total_sum / len(iterations)

    def _remove_pattern_files(self, patterns):
        """
        To remove files with a pattern
        param patterns: list of files to be removed with pattern
        """
        for pattern in patterns:
            for file in glob.glob(pattern):
                if os.path.isfile(file):
                    os.remove(file)

    def test(self):
        """
        Main function to test Perf record and vmstat with CPU stress
        :source: git://kernel.ubuntu.com/cking/stress-ng.git
        :param: None
        """
        self.tcpus = os.cpu_count()
        smt = int(re.split(r'=| is ', process.system_output("ppc64_cpu --smt")
                           .decode('utf-8'))[1])
        no_of_cores = int(self.tcpus // smt)
        # Equivalent Python code for bash command
        # "cat /proc/cpuinfo | grep -m1 clock |sed 's/.*://' | cut -f1 -d'.'"
        clock_freq = 0
        output = genio.read_all_lines("/proc/cpuinfo")
        for line in output:
            if 'clock' in line:
                clock_freq = int(line.split(":")[1].split(".")[0].strip())
                break
        cpu_freq = int(clock_freq // 100)
        perf_iterations = {}
        vmstat_iterations = {}
        final_results = {}
        failed = 0

        self.log.info("=====================================================")

        self.log.info("Total cpus %s", self.tcpus)
        self.log.info("Total cores %s", no_of_cores)
        self.log.info("SMT = %s", smt)
        self.log.info("Perf profile duration: %s", self.profile_dur)
        self.log.info("CPU frequency = %s", cpu_freq)

        # Equivalent Python code for bash command
        # "rm -rf /tmp/stressng_output* /tmp/data*"
        self._remove_pattern_files(['/tmp/stressng_output*', '/tmp/data*'])

        for load in self.cpu_per.split():
            cmd = f"timeout %s stress-ng --cpu=%s -l %s --timeout %s" \
                " 1>>/tmp/stdout 2>>/tmp/stderr &" % (
                    self.timeout, self.tcpus, load, self.timeout)
            return_val = process.run(cmd, ignore_status=True, sudo=True,
                                     shell=True, ignore_bg_processes=True)
            if (return_val.exit_status != 0):
                self.fail("stress-ng failed")
            time.sleep(3)

            if self.is_process_running("stress-ng"):
                for iter in range(1, 6):
                    self.log.info(
                        "Running stress-ng CPU load %s for iteration %s" %
                        (load, iter))

                    cmd = f"timeout %s vmstat 1 11 &>> /tmp/stressng_output_%s_%s.log &" % (
                        self.timeout, load, iter)
                    return_val = process.run(
                        cmd, ignore_status=True, sudo=True, shell=True, ignore_bg_processes=True)
                    if (return_val.exit_status != 0):
                        self.fail("vmstat failed")

                    cmd = "perf record -e cycles -a sleep 10 1>>/tmp/stdout 2>>/tmp/stderr"
                    return_val = process.run(cmd, shell=True)
                    if (return_val.exit_status != 0):
                        self.fail("perf record failed")

                    cmd = "perf report > /tmp/data.txt && sed -n '6,7p' /tmp/data.txt >> /tmp/stressng_output_%s_%s.log" % (
                        load, iter)
                    return_val = process.run(
                        cmd, ignore_status=True, sudo=True, shell=True, ignore_bg_processes=True)
                    if (return_val.exit_status != 0):
                        self.fail("perf report failed")

                    # Equivalent Python code for bash command
                    # "sed -n '/approx./{p;q}' < /tmp/data.txt | awk '{print $NF}'"
                    pattern = re.compile(r'approx.')
                    output = genio.read_all_lines('/tmp/data.txt')
                    perf_data = 0
                    for line in output:
                        if pattern.search(line):
                            perf_data = int(line.strip().split()[-1])
                            break

                    self.log.info(" Perf data ==>  %s" % perf_data)

                    result = int(perf_data / (no_of_cores *
                                 self.profile_dur * smt * cpu_freq * 1000000))
                    self.log.info(
                        " Result for iteration %s and load %s ==>  %s" % (iter, load, result))

                    perf_iterations[iter] = result
                    filename = str("/tmp/stressng_output_") + \
                        str(load) + str("_") + str(iter) + str(".log")
                    self.log.info("filename = %s " % (filename))
                    vmstat_iterations[iter] = self.vmstat_result(filename)

                perf_average = self.calculate_average(perf_iterations)
                vmstat_average = self.calculate_average(vmstat_iterations)
                self.log.info(
                    " ***************************************************************************************")
                self.log.info(
                    " Summary for CPU Load %s for %s iterations" %
                    (load, iter))
                self.log.info(
                    " Perf data %s   <=====> vmstat data %s" %
                    (perf_iterations, vmstat_iterations))
                self.log.info(
                    " Perf Average %s <=====> vmstat Average %s " %
                    (perf_average, vmstat_average))
                self.log.info(
                    " ***************************************************************************************")

                if self.is_process_running("stress-ng"):
                    self.kill_process_by_name("stress-ng")

                change_percent = abs(perf_average - vmstat_average)

                if change_percent > 3.5:
                    final_results[load] = change_percent
                    failed = 1
                    self.log.info(
                        " CPU load %s Failed with percentage %s difference" %
                        (load, change_percent))
            else:
                self.log.info(
                    "stress-ng is either not running or all the process are now killed ")

        self.log.info("=====================================================")
        if failed == 1:
            self.fail(" CPU load %s combination's failed with percentage difference %s" % (
                self.cpu_per, final_results))

    def tearDown(self):
        """
        removes the log files and collects the dmesg data
        :param: none
        """
        self._remove_pattern_files(["/tmp/stdout", "/tmp/stderr", "/tmp/data*",
                                   "/tmp/stressng_output*"])
        dmesg.collect_dmesg()
