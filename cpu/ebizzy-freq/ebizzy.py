#!/bin/python
import json
import random
import csv
import string
from collections import Counter
import re
from avocado import Test
from avocado import main
from avocado.utils import process


class ebizzy(Test):
    def test(self):
        threads_per_core = process.system_output("lscpu |""grep \"Thread(s) per core:\" |""cut -d':' -f2", shell=True).strip()
        rand_cpu = self.get_rand_online()
        rand_cpu_idx = int(rand_cpu) % int(threads_per_core)
        start_cpu = int(rand_cpu) - int(rand_cpu_idx)
        end_cpu = int(start_cpu) + int(threads_per_core) - 1
        for util_val in range(10, 100, 10):
            self.get_time_in_state(util_val, start_cpu, 0)
            self.set_smt()
            cmd = "taskset -c '%s - %s' ./run_ebizzy.sh %s %s 60" % (start_cpu, end_cpu, util_val, (2 * threads_per_core))
            output = process.system_output(cmd)
            self.get_time_in_state(util_val, start_cpu, 1)
            self.get_diff_time_in_state(util_val)

    def get_rand_online(self):
        # Get Random cpu from list of CPUs
        cpus_1 = []
        online_cpus = process.system_output("cat /proc/cpuinfo |""grep \"processor\" |""cut -d':' -f2", shell=True).strip()
        cpus_1 = online_cpus.split()
        return random.choice(cpus_1)

    def get_time_in_state(self, util_val, start_cpu, is_before):
        # Collect time_in_state values before and after tests
        if is_before is 0:
            file = "/tmp/timestat_%s_before" % (util_val)
        else:
            file = "/tmp/timestat_%s_after" % (util_val)
        fd = open(file, 'w')
        filename = "/sys/devices/system/cpu/cpu%s/cpufreq/stats/time_in_state" % (start_cpu)
        for line in open(filename, 'r').readlines():
            fd.writelines(line)

    def set_smt(self):
        cmd_set_smt = "ppc64_cpu --smt=on"
        output = process.system_output(cmd_set_smt)

    def get_diff_time_in_state(self, util_val):
        # Difference in values before and after running sleep ebizzy tests
        A = []
        for name in ['after', 'before']:
            file = "/tmp/timestat_%s_%s" % (util_val, name)
            dict = "d_%s" % name
            dict = {}
            dict_res = self.get_dict(file, dict)
            A.append(dict_res)
        self.diff_dic(A, util_val)

    def get_dict(self, file, dict):
        f1 = open(file, 'r')
        for line in f1:
            line1 = string.split(line)
            a1 = line1[-1]
            freq = " ".join(line1[:-1])
            dict[freq] = a1
        return dict

    def diff_dic(self, A, util_val):
        # Get final Dict and plot graph accordingly
        d3 = {}
        for k, v1 in (A[0]).items():
            d3[k] = int(v1) - int((A[1]).get(k, 0))
        file = "/tmp/final_%s.csv" % util_val
        with open(file, 'wb') as f:
            w = csv.DictWriter(f, d3.keys())
            w.writeheader()
            w.writerow(d3)

if __name__ == "__main__":
    main()
