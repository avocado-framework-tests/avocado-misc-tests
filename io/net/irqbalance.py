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
# Author: Shaik Abdulla <shaik.abdulla1@ibm.com>

'''
Irq-balance and CPU affinity test for IO subsystem.
'''

import re
import os
from avocado import Test
from avocado.utils import process, cpu, wait, dmesg, genio
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.network.hosts import LocalHost
from avocado.utils.process import CmdError
import multiprocessing
import subprocess
import time

totalcpus = int(multiprocessing.cpu_count()) - 1
errorlog = ['WARNING: CPU:', 'Oops',
            'Segfault', 'soft lockup', 'ard LOCKUP',
            'Unable to handle paging request',
            'rcu_sched detected stalls',
            'NMI backtrace for cpu',
            'Call Trace:']


class irq_balance(Test):

    '''
    Test to verify irqbalance by setting up various SMP_affinity levels for
    any given IO adapters/devices.
    1. Covers assiging diffrent SMP affinity list to IO IRQ number and
       validating values set.
    2. Setting up diffrent avialble CPU'S to IO based process by taskset
       and validating values set.
    3. Making off/on [ offline/online ] of CPU's from min available CPU's
       to Max available CPU's serial fashion.
    4. Setting diffent SMT levels and off/on using ppc64_cpu utils.
    '''

    def setUp(self):
        '''
        Set up
        '''
        self.interface = None
        device = self.params.get("interface", default=None)
        self.disk = self.params.get("disk", default=None)
        if device:
            self.peer_ip = self.params.get("peer_ip", default=None)
            self.ping_count = self.params.get("ping_count", default=None)
            interfaces = os.listdir('/sys/class/net')
            self.localhost = LocalHost()
            if device in interfaces:
                self.interface = device
            elif self.localhost.validate_mac_addr(device) and device in self.localhost.get_all_hwaddr():
                self.interface = self.localhost.get_interface_by_hwaddr(device).name
            else:
                self.cancel("Please check the network device")
            if not self.peer_ip:
                self.cancel("peer ip need to specify in YAML")
            self.ipaddr = self.params.get("host_ip", default="")
            self.networkinterface = NetworkInterface(self.interface,
                                                     self.localhost)
            if not self.networkinterface.validate_ipv4_format(self.ipaddr):
                self.cancel("Host IP formatt in YAML is incorrect,"
                            "Please specify it correctly")
            if not self.networkinterface.validate_ipv4_format(self.peer_ip):
                self.cancel("Peer IP formatt in YAML is incorrect,"
                            "Please specify it correctly")
            self.netmask = self.params.get("netmask", default="")
            if not (self.networkinterface.validate_ipv4_netmask_format
                    (self.netmask)):
                self.cancel("Netmask formatt in YAML is incorrect,"
                            "please specify it correctly")
            try:
                self.networkinterface.add_ipaddr(self.ipaddr, self.netmask)
                self.networkinterface.save(self.ipaddr, self.netmask)
            except Exception:
                self.networkinterface.save(self.ipaddr, self.netmask)
            self.networkinterface.bring_up()
            if not wait.wait_for(self.networkinterface.is_link_up, timeout=60):
                self.cancel("Link up of interface taking more than"
                            "60 seconds")
            if self.networkinterface.ping_check(self.peer_ip,
                                                count=5) is not None:
                self.cancel("No connection to peer")
            self.interface_type = self.networkinterface.get_device_IPI_name()

        if self.disk:
            self.interface_type = self.get_disk_IPI_name()

        self.check_current_smt()
        self.set_max_smt_values()
        self.cpu_list = cpu.online_list()

    @staticmethod
    def __online_cpus(cores):
        for cpus in range(cores):
            cpu.online(cpus)

    def check_current_smt(self):
        '''
        Function to check current smt values of CPU.
        :rtype : int
        '''
        cmd = ("ppc64_cpu --smt | awk 'NR==1 {split($0, arr, \"=\"); "
               "split(arr[2], num, \":\"); print num[1]}'")
        curr_smt = process.system_output(cmd, shell=True).decode("utf-8")
        return curr_smt

    def get_disk_IPI_name(self):
        '''
        Function to get the Disk IPI name according to
        "/proc/interrupt" context.
        :rtype : str
        '''
        if "nvme" in self.disk:
            pattern = r"\/(nvme[0-9]+)n[0-9]+"
            match = re.search(pattern, self.disk)
            disk_ipi_name = match.group(1)
            return disk_ipi_name

    def get_device_interrupts(self):
        '''
        Function to get all the interrupts device_IPI of given device.
        '''
        cmd = f"grep {self.interface_type} /proc/interrupts"
        self.device_interrupts = process.run(cmd,
                                             shell=True,
                                             ignore_status=True
                                             ).stdout.decode().strip()
        return self.device_interrupts

    def get_irq_numbers(self):
        '''
        Function to get all IRQ numbers assocaited for given device.
        '''
        self.irq_number = [int(x.strip(":"))
                           for x in re.findall(r'\b(\d+):',
                                               self.device_interrupts)]
        return self.irq_number

    def get_ping_process_pid(self):
        """
        Funtion to get the process ID of ping flood.

        :returns : Process PID number that initated by ping flood command.
        :rtype : int
        """
        cmd = (
            f"ps -ef | grep '[p]ing -I "
            f"{self.interface} {self.peer_ip} -c {self.ping_count} -f' "
            f"| awk '{{print $2}}' | head -1"
        )
        process_pid = process.system_output(cmd, shell=True,
                                            ignore_status=True,
                                            sudo=True).decode("utf-8")
        if not process_pid:
            self.log.debug(f"No more process PID avaialable")
            return False
        return process_pid

    def compare_range_strings(self, range_str1, range_str2):
        '''
        Function to compare and match cpu range of string format.
        :rtype : boolean value.
        '''
        range_pattern = r'(\d+)-(\d+)'
        match1 = re.match(range_pattern, range_str1)
        match2 = re.match(range_pattern, range_str2)

        if match1 and match2:
            start1, end1 = int(match1.group(1)), int(match1.group(2))
            start2, end2 = int(match2.group(1)), int(match2.group(2))

            return start1 == start2 and end1 == end2
        return False

    def cpu_range_validation(self):
        '''
        Funtion to validate the assinged CPU's by script.
        '''
        self.irq_affinity = '-'.join([str(self.cpu_range[0]),
                                      str(self.cpu_range[-1])])
        cmd = f'/proc/irq/{self.irq_number}/smp_affinity_list'
        self.system_affinity = genio.read_file(cmd)
        time.sleep(25)
        if not self.compare_range_strings(self.irq_affinity,
                                          self.system_affinity):
            self.fail(f'The smp_affinity_list does not matches to affinity'
                      ' that was set by script, Please check the logs')

    def get_module_interrupts(self):
        '''
        Funtion to filter all interrupts along associated CPU's of device.
        '''
        cmd = f'head -n 1 /proc/interrupts &&' \
              f' grep {self.interface_type} /proc/interrupts'

        process.run(cmd, shell=True, ignore_status=True
                    ).stdout.decode().strip()

    def taskset_cpu_validation(self):
        '''
        Function to validate the CPU number set by "taskset" command.
        Returns : <int> value set by script.
        '''
        if self.interface:
            cmd = "ps -o psr -p %s | awk 'NR>1 {print $1}'" % (
                self.get_ping_process_pid()
            )
        if self.disk:
            cmd = "ps -o psr -p %s | awk 'NR>1 {print $1}'" % (
                self.get_dd_process_pid()
            )

        cpu_by_script = process.system_output(cmd, shell=True,
                                              ignore_status=True,
                                              sudo=True).decode("utf-8")
        return int(cpu_by_script)

    def get_dd_process_pid(self):
        '''
        Function to extract PID for running "dd" Process.
        Returns: PID value.
        Rtype: int
        '''
        cmd = f"ps -C dd | awk 'NR > 1 {{print $1}}'"
        dd_process_pid = process.system_output(cmd, shell=True,
                                               ignore_status=True, sudo=True
                                               ).decode("utf-8")
        if not dd_process_pid:
            self.fail(f"No more dd run process PID avaialable")
        return dd_process_pid

    def dd_run(self):
        '''
        Runs the dd command on given Disk and returns True or False
        '''
        cmd = f"dd if=/dev/urandom of={self.disk} bs=1M count=$((600*60))"
        process = subprocess.Popen(
            cmd, shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True
        )
        while True:
            self.log.debug(f"Initaited dd command on disk {self.disk}")
            return True
        process.stdout.close()
        process.wait()

    def set_max_smt_values(self):
        '''
        Function to set max smt values.
        '''
        wait.wait_for(self.set_smt_values, args=(8,), timeout=300)

    def set_smt_values(self, value):
        '''
        Function to execute different smt values.
        '''
        cmd = f'ppc64_cpu --smt={value}'
        output = process.run(cmd, shell=True)
        if output.exit_status != 0:
            return False
        return True

    def test_irq_balance(self):
        '''
        Selects single IRQ number of device and sets,
        a. Assign all the avialable CPU's serially from min to maximum
           avaliable CPU's and validates the operations.
        Eg: 1
            1,2
            1,2, ----> 99 [ upto max available CPU's ]

        b. Unassing all the avialable CPU's serially from max to minimum
           avialble CPU's and validates the operations.
        Eg: 1,2 -----> 99
            1,2 ----> 98
            1 [ upto min avialable CPU's ]
        '''
        self.get_device_interrupts()
        self.get_irq_numbers()

        if len(self.irq_number) == 1:
            self.irq_number = self.irq_number[0]
        else:
            self.irq_number = self.irq_number[1]

        '''
        Assgining CPU's to IRQ serailly upto max available CPU's
        '''
        for cpu_number in range(len(self.cpu_list)):
            self.cpu_range = self.cpu_list[:cpu_number+1]
            output = process.run(
                f'echo {str(self.cpu_range)[1:-1]} > /proc/irq/'
                f'{self.irq_number}/smp_affinity_list',
                shell=True, ignore_status=True
            )
            if output.exit_status != 0:
                self.fail(f'Assigning CPU to IRQ failed, Please check logs')
            wait.wait_for(self.get_module_interrupts, timeout=5)
            if len(self.cpu_range) > 1:
                self.cpu_range_validation()
        dmesg.collect_errors_dmesg(errorlog)

        '''
        un-assgining CPU's in reverse order upto minimum available CPU's
        '''
        while len(self.cpu_range) > 1:
            cpu_range = ','.join(str(n) for n in self.cpu_range)
            output = process.run(f'echo {str(cpu_range)} > /proc/irq/'
                                 f'{self.irq_number}/smp_affinity_list',
                                 shell=True, ignore_status=True)
            if output.exit_status != 0:
                self.fail(f'Assigning CPU to IRQ failed, Please check logs')
            if len(self.cpu_range) > 1:
                self.cpu_range_validation()
            wait.wait_for(self.get_module_interrupts, timeout=5)
            self.cpu_range = self.cpu_range[:-1]
        dmesg.collect_errors_dmesg(errorlog)

    def test_cpu_serial_off_on(self):
        '''
        Offline all the cpus serially and online again.
        offline 0 -> 99
        online 99 -> 0
        '''
        if len(self.cpu_list) == 1:
            self.cancel(" only one cpu is avialable cannot do this operation")

        '''
        Making CPU offline serially
        '''
        for cpus in self.cpu_list[:-1]:
            self.log.info("Offlining cpu%s", cpus)
            cpu.offline(cpus)
            if cpus in cpu.online_list():
                self.fail(f" The offlined cpu {cpus} is still showing as"
                          f" online, Please check the logs")

        '''
        Making CPU online serially
        '''
        for cpus in self.cpu_list[:-1]:
            self.log.info("Onlining cpu%s", cpus)
            cpu.online(cpus)
            if cpus not in cpu.online_list():
                self.fail(f" The onlined cpu {cpus} is still showing as"
                          f" offline, Please check the logs")
        dmesg.collect_errors_dmesg(errorlog)

    def test_smt_toggle(self):
        '''
        Enables diferrent SMT options to offline multiple cpus
        1. makes offlines all cpu's
        2. enable smt value from 1 --> 8
        3. makes all cpu offline again.
        4. makes all cpu online.

        '''
        for i in ['off', *range(1, 9), 'off', 'on']:
            wait.wait_for(self.set_smt_values, args=(i,), timeout=300)

    def test_taskset(self):
        '''
        Function to run "taskset" command to assign available CPU's to
        Process ID.
        changes the CPU number of PID while IO running.
        Eg:
           CPU1 ---> CPU2
           CPU2 ---> CPU3, ----> till last availble CPU number.
        '''
        if self.interface:
            for cpu_number in self.cpu_list:
                if self.networkinterface.ping_flood(self.interface,
                                                    self.peer_ip,
                                                    self.ping_count):
                    cmd = "taskset -cp %s %s" % (
                        cpu_number,
                        self.get_ping_process_pid()
                    )
                    output = process.run(cmd, shell=True, ignore_status=True)
                    if output.exit_status != 0:
                        self.fail(f'taskset command failed check logs')
                    if cpu_number != self.taskset_cpu_validation():
                        self.fail(f"CPU number is mismatching after taskset "
                                  "operation, Please check logs.")
                    try:
                        process.system(
                            "kill -9 %s" % int(self.get_ping_process_pid()),
                            ignore_status=True,
                            sudo=True
                        )
                    except CmdError as ex:
                        self.log.fail(f"Failed to kill the processes, {ex}")
                else:
                    self.fail(f"ping flood failed, Please check the logs")
        if self.disk:
            for cpu_number in self.cpu_list:
                if self.dd_run():
                    cmd = (
                        f"taskset -cp {cpu_number} "
                        f"{self.get_dd_process_pid()}"
                    )
                    output = process.run(cmd, shell=True, ignore_status=True)
                    if output.exit_status != 0:
                        self.fail(f'taskset command failed check logs')
                    if cpu_number != self.taskset_cpu_validation():
                        self.fail(f"CPU number is mismatching after taskset "
                                  "operation, Please check logs.")
                    try:
                        process.system(
                            f"kill -9 {int(self.get_dd_process_pid())}",
                            ignore_status=True,
                            sudo=True
                        )
                    except CmdError as ex:
                        self.log.fail(f"Failed to kill the processes, {ex}")
                    time.sleep(2)
                else:
                    self.fail(f'dd command failed, Please check logs')
        dmesg.collect_errors_dmesg(errorlog)

    def tearDown(self):
        """
        Sets back SMT to original value as was before the test.
        Sets back cpu states to online
        """
        if hasattr(self, 'curr_smt'):
            process.system_output(f"ppc64_cpu "
                                  f"--smt={self.check_current_smt()}",
                                  shell=True
                                  )
        self.__online_cpus(totalcpus)
        if self.interface:
            if self.networkinterface:
                self.networkinterface.remove_ipaddr(self.ipaddr, self.netmask)
                try:
                    self.networkinterface.restore_from_backup()
                except Exception:
                    self.networkinterface.remove_cfg_file()
                    self.log.info("backup file not availbale,"
                                  "could not restore file.")
