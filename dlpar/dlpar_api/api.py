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
# Copyright: 2021 IBM
# Author: Ricardo Salveti <rsalveti@linux.vnet.ibm.com>
# Modified Author: Kalpana Shetty <kalshett@in.ibm.com>

"""
This is the DLPAR test suite API.

It was developed based on how we could test DLPAR while
adding, moving and removing the devices (slots, cpu_units
and etc.).

Here you can find the important TestCase class with many
useful methods to let you test DLPAR.
"""

# Standard library imports
import logging
import re
import time
from avocado import *
from avocado.utils import process
from avocado.utils.ssh import Session
__all__ = ['TestException', 'SshMachine', 'TestLog',
           'TestCase', 'DedicatedCpu', 'CpuUnit', 'Memory']


class TestException(Exception):
    """Base Class for all test exceptions."""

    def __init__(self, value):
        Exception.__init__(self)
        self.value = value

    def __str__(self):
        return str(self.value)


class SshMachine():
    """The machine that we reach using the ssh protocol.

    This class take every important information about the machine
    and also the ssh connection.
    """

    def __init__(self, config_payload, machine_type, log=None):
        """Get every machine information."""
        if machine_type == "linux_primary":
            self.name = config_payload.get('src_name')
            self.machine = config_payload.get('hmc_manageSystem')
            self.partition = config_payload.get('src_partition')
        elif machine_type == "linux_secondary":
            self.name = config_payload.get('target_lpar_hostname')
            self.user = config_payload.get('target_user')
            self.passwd = config_payload.get('target_passwd')
            self.partition = config_payload.get('target_partition')
            self.machine = config_payload.get('hmc_manageSystem')
        else:
            self.name = config_payload.get('hmc_name')
            self.user = config_payload.get('hmc_user')
            self.passwd = config_payload.get('hmc_passwd')
            self.partition = config_payload.get('hmc_manageSystem')
            self.machine = config_payload.get('hmc_manageSystem')

        self.log = log
        if machine_type == "hmc" or machine_type == "linux_secondary":
            self.sshcnx = self.__init_ssh(self.user, self.passwd, self.name)

    def __init_ssh(self, hmc_username, hmc_pwd,  hmc_ip):
        """Return the SSH connection"""
        self.hmcip = hmc_ip
        self.un = hmc_username
        self.pw = hmc_pwd
        self.session_hmc = Session(self.hmcip, user=self.un,
                                   password=self.pw)
        self.session_hmc.cleanup_master()
        if not self.session_hmc.connect():
            print("failed connecting to HMC")
        return self.session_hmc


class TestLog(logging.Logger):
    """Log Object.

    This is the Python Log object with one more method (check_log)
    that print the log message checking the code that you pass to.
    This also set both file and screen logging, with different formatting.
    """

    def __init__(self, logpath):
        # initialize the mother
        logging.Logger.__init__(self, 'root')

        # file log output configuration
        log_file = logging.FileHandler(logpath, 'w')
        log_file.setLevel(self.__get_log_level("DEBUG"))
        format_string = '%(asctime)s %(levelname)-8s %(message)s'
        formatter = logging.Formatter(format_string,
                                      datefmt='%a, %d %b %Y %H:%M:%S')
        log_file.setFormatter(formatter)
        self.addHandler(log_file)

        # console log output configuration
        console = logging.StreamHandler()
        console.setLevel(self.__get_log_level("INFO"))
        formatter = logging.Formatter('%(levelname)-8s: %(message)s')
        console.setFormatter(formatter)
        self.addHandler(console)

    def __get_log_level(self, log_level):
        """Just to translate the strig format to logging format."""
        if log_level not in ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'):
            self.warning('Misconfigured log level %s. Assuming INFO.' %
                         log_level)
            return logging.INFO
        return getattr(logging, log_level)

    def check_log(self, message, code, die=True):
        """
        Catch the code and print the message accordantly
        'code' can be both integer or boolean.
        """
        if type(code) is int:
            if code < 0:
                self.error('[FAILED] %s' % message)
                if die:
                    raise TestException('Check failed. Aborting test.')
                return False
            else:
                self.info('[PASS] %s' % message)
                return True
        elif type(code) == bool:
            if not code:
                self.error('[FAILED] %s' % message)
                if die:
                    raise TestException('Check failed. Aborting test.')
                return False
            else:
                self.info('[PASS] %s' % message)
                return True


class TestCase:
    """Base Class for a Test Case."""

    def __init__(self, log_file, test_name, config_payload):
        """Initialize the test case.
        Set the log file, get all machines connection and the config file.
        """
        # Set the log
        self.log = TestLog(log_file)
        self.log.info('Starting %s Test Case.' % test_name)

        self.cpu_per_processor = int(config_payload.get('cfg_cpu_per_proc'))

    def get_connections(self, config_payload, clients='both'):
        """
        Get connections for the HMC and the linux clients.
        @param clients: The clients we are going to connect to. It can be
                        one of 'primary', 'secondary' or 'both'.
        """
        # Get connection for the machines
        try:
            # Hmc ...
            self.hmc = SshMachine(config_payload, 'hmc', self.log)
            self.log.debug('Login to HMC successful.')
            # ... and the linux partitions
            if clients == 'primary' or clients == 'both':
                self.linux_1 = SshMachine(
                    config_payload, 'linux_primary', self.log)
                self.log.debug('Login to 1st linux LPAR successful.')
            if clients == 'secondary' or clients == 'both':
                self.linux_2 = SshMachine(
                    config_payload, 'linux_secondary', self.log)
                self.log.debug('Login to 2nd linux LPAR successful.')

            self.log.check_log('Getting Machine connections.', True)
        except Exception:
            self.log.check_log('Getting Machine connections.', False, False)
            raise

    def Dlpar_engine(self, dlpar_flag, linux_machine, quantity):
        """
        Running the DLPAR commands.
         1 - Add (cpu, memory)
         2 - Move (cpu, memory)
         3 - Remove (cpu, memory)
        """
        cmd = ""
        if dlpar_flag[1] == "a" or dlpar_flag[1] == "r":
            cmd = 'chhwres -m ' + linux_machine.machine + \
                ' -r ' + dlpar_flag[0] + ' -o ' + dlpar_flag[1] + \
                ' ' + dlpar_flag[2] + ' ' + str(quantity) + \
                ' -p "' + linux_machine.partition + '"' + ' -w 0 '
        elif dlpar_flag[1] == "m":
            cmd = 'chhwres -m ' + linux_machine[0].machine + \
                ' -r ' + dlpar_flag[0] + ' -o ' + dlpar_flag[1] + ' ' + \
                dlpar_flag[2] + ' ' + str(quantity) + \
                ' -p "' + linux_machine[0].partition + '"' + \
                ' -t "' + linux_machine[1].partition + '"' + ' -w 0 '
        else:
            self.log.error("Invalid DLPAR flag")
        self.cmd_result = self.hmc.sshcnx.cmd(cmd)

        return self.cmd_result

    def Dlpar_cpu_validation(self, flag, linux_machine, quantity,
                             curr_procs_info, cmd_result):
        """
         Validating all the CPU add and remove operations after
         they have been performed.
        """
        if flag == "a":
            curr_procs_before = curr_procs_info
            a_msg = 'Adding %d dedicated cpus to partition %s.' % \
                    (quantity, linux_machine.partition)
            a_condition = int(self.get_cpu_option(
                linux_machine, 'curr_procs')) == \
                curr_procs_before + quantity
            if not self.log.check_log(a_msg, a_condition, False):
                e_msg = 'Error adding %d dedicated cpus to partition %s.' % \
                        (quantity, linux_machine.partition)
                self.log.error(e_msg)
                raise TestException(cmd_result)

        elif flag == "r":
            curr_procs_before = curr_procs_info
            r_msg = 'Removing %s dedicated cpus from partition %s.' % \
                (quantity, linux_machine.partition)
            r_condition = int(self.get_cpu_option(linux_machine,
                                                  'curr_procs')) == \
                (curr_procs_before
                 - quantity)
            if not self.log.check_log(r_msg, r_condition, False):
                e_msg = 'Error removing %s dedicated cpus from partition %s.' \
                        % (quantity, linux_machine.partition)
                self.log.error(e_msg)
                raise TestException(e_msg)

        elif flag == "m":

            m_msg = 'Moving %s dedicated cpus from %s to %s.' % \
                (quantity, linux_machine[0].partition,
                 linux_machine[1].partition)
            m_condition = (int(self.get_cpu_option(linux_machine[0],
                                                   'curr_procs'))
                           == curr_procs_info[0] - quantity) \
                and (int(self.get_cpu_option(linux_machine[1],
                                             'curr_procs'))
                     == curr_procs_info[1] + quantity)
            if not self.log.check_log(m_msg, m_condition, False):
                self.log.error(cmd_result)
                raise TestException(cmd_result)
            # Check at both linux partitions
            self.linux_check_rm_cpu(
                linux_machine[0], curr_procs_info[0], quantity)
            self.linux_check_add_cpu(linux_machine[1], quantity)

        elif flag == "cpu_a":
            curr_proc_units_before = curr_procs_info
            a_msg = 'Adding %s proc units to partition %s.' % \
                    (quantity, linux_machine.partition)
            a_condition = (self.get_cpu_option(linux_machine,
                                               'curr_proc_units') ==
                           str(curr_proc_units_before + quantity))
            # Check at HMC
            if not self.log.check_log(a_msg, a_condition, False):
                e_msg = 'Error adding %s proc units to partition %s.' % \
                        (quantity, linux_machine.partition)
                self.log.error(e_msg)
                raise TestException(e_msg)
        elif flag == "cpu_r":
            curr_proc_units_before = curr_procs_info
            # Check at HMC
            r_msg = 'Removing %s proc units from partition %s.' % \
                    (quantity, linux_machine.partition)
            r_condition = float(self.get_cpu_option(linux_machine,
                                                    'curr_proc_units')) == \
                round((curr_proc_units_before - quantity))
            if not self.log.check_log(r_msg, r_condition, False):
                e_msg = 'Error removing %s proc units from partition %s.' % \
                        (quantity, linux_machine.partition)
                self.log.error(e_msg)
                raise TestException(e_msg)
        elif flag == "cpu_m":
            curr_proc_units_before = curr_procs_info
            # Check at HMC
            m_msg = 'Moving %s proc units from %s to %s.' % \
                    (quantity, linux_machine[0].partition,
                     linux_machine[1].partition)
            proc_after_0 = float(self.get_cpu_option(linux_machine[0],
                                                     'curr_proc_units'))
            proc_after_1 = float((self.get_cpu_option(linux_machine[1],
                                                      'curr_proc_units')))
            m_condition = (float(self.get_cpu_option(linux_machine[0],
                                                     'curr_proc_units')) ==
                           round(float(curr_proc_units_before[0]) -
                                 quantity)) and \
                (float((self.get_cpu_option(linux_machine[1],
                                            'curr_proc_units'))) ==
                 float((curr_proc_units_before[1]) + quantity))
            if not self.log.check_log(m_msg, m_condition, False):
                e_msg = 'Moving %s proc units from %s to %s.' % \
                        (quantity, linux_machine[0].partition,
                         linux_machine[1].partition)
                self.log.error(e_msg)
                raise TestException(e_msg)

    def Dlpar_mem_validation(self, flag, linux_machine, quantity,
                             mem_info, cmd_result):
        """
        Validating all the memory add and remove operations after
        they have been performed.
        """
        if flag == "a":
            # Check at HMC
            curr_mem_before = mem_info[0]
            curr_mem_proc_before = mem_info[1]
            a_msg = 'Adding %d megabytes of memory to partition %s.' % \
                    (quantity, linux_machine.partition)
            a_condition = (int(self.get_mem_option(linux_machine,
                                                   'curr_mem')) ==
                           curr_mem_before + quantity)
            if not self.log.check_log(a_msg, a_condition, False):
                e_msg = 'Error happened when adding memory to %s' % \
                        linux_machine.partition
                self.log.error(e_msg)
                raise TestException(e_msg)
            # Check at Linux partition (using /proc/meminfo)
            curr_mem_proc_after = self.check_memory_proc(linux_machine)
            p_msg = 'Checking if /proc/meminfo shows all added memory.'
            p_condition = ((curr_mem_proc_after - curr_mem_proc_before)/1024
                           == quantity)
            self.log.check_log(p_msg, p_condition)
        elif flag == "r":
            curr_mem_before = mem_info[0]
            curr_mem_proc_before = mem_info[1]
            r_msg = 'Removing %d megabytes of memory from partition %s.' % \
                    (quantity, linux_machine.partition)
            curr_mem = int(self.get_mem_option(linux_machine, 'curr_mem'))
            r_condition = ((curr_mem) == (curr_mem_before - quantity))
            if not self.log.check_log(r_msg, r_condition, False):
                e_msg = 'Error happened when removing memory from %s' % \
                    linux_machine.partition
                self.log.error(e_msg)
                raise TestException(e_msg)
            # Check at Linux partition (using /proc/meminfo)
            curr_mem_proc_after = self.check_memory_proc(linux_machine)
            p_msg = 'Checking if /proc/meminfo shows all removed memory.'
            p_condition = ((curr_mem_proc_before - curr_mem_proc_after)/1024 ==
                           quantity)
            self.log.check_log(p_msg, p_condition)
        elif flag == "m":
            curr_mem_before_1 = mem_info[0]
            curr_mem_before_2 = mem_info[1]
            curr_mem_proc_before_1 = mem_info[2]
            curr_mem_proc_before_2 = mem_info[3]
            m_msg = 'Moving %d megabytes of memory from %s to %s.' % \
                (quantity, linux_machine[0].partition,
                 linux_machine[1].partition)
            if not self.log.check_log(m_msg,
                                      (int(self.get_mem_option(
                                          linux_machine[0], 'curr_mem'))
                                       ==
                                       curr_mem_before_1 - quantity) and
                                      (int(self.get_mem_option(
                                          linux_machine[1], 'curr_mem'))
                                       ==
                                          curr_mem_before_2 + quantity),
                                      False):
                e_msg = 'Error happened when moving memory from %s to %s' % \
                    (linux_machine[0].partition, linux_machine[1].partition)
                self.log.error(e_msg)
                raise TestException(e_msg)
            # Check at Linux partition (using /proc/meminfo)
            curr_mem_proc_after_1 = self.check_memory_proc(linux_machine[0])
            curr_mem_proc_after_2 = self.check_memory_proc(linux_machine[1])

            c_msg_1 = 'Checking if /proc/meminfo shows removed memory on %s.' \
                % linux_machine[0].partition
            self.log.check_log(c_msg_1, (round(abs((curr_mem_proc_before_1 -
                                                    curr_mem_proc_after_1))
                                               / 1024)
                                         == quantity))
            c_msg_2 = 'Checking if /proc/meminfo shows removed memory on %s.' \
                % linux_machine[1].partition
            self.log.check_log(c_msg_2, (round(abs((curr_mem_proc_after_2 -
                                                    curr_mem_proc_before_2))
                                         / 1024)
                                         == quantity))

    def run_test(self):
        """Run the test case."""
        pass

    def get_cpu_option(self, linux_machine, option):
        """Just to help getting a cpu option from hmc."""

        o_cmd = 'lshwres -m ' + linux_machine.machine + \
                ' --level lpar -r proc --filter lpar_names="' + \
                linux_machine.partition + '" -F ' + option
        opt_value = self.hmc.sshcnx.cmd(o_cmd).stdout_text.strip()
        d_msg = option + ": " + opt_value + " for partition " + \
            linux_machine.partition
        self.log.debug(d_msg)
        return opt_value

    def check_memory_proc(self, machine):
        """
        Check on a linux client how much physical memory we have.
        """
        memory = 0
        p_cmd = ""
        self.log.info('Checking memory under linux on %s' % machine.partition)
        try:
            p_cmd = 'cat /proc/meminfo | grep MemTotal'
            memory = machine.sshcnx.cmd(p_cmd).stdout_text
        except Exception:
            cmd = []
            cmd.append(p_cmd)
            memory = process.run(cmd, shell=True).stdout.decode()
        memory = memory.strip().split(":")[-1].strip().split(" ")[0]
        return int(memory)

    def get_mem_option(self, linux_machine, option):
        """Just to help getting a memory option from hmc."""
        o_cmd = 'lshwres -m ' + linux_machine.machine + \
                ' --level lpar -r mem --filter lpar_names="' + \
                linux_machine.partition + '" -F ' + option
        opt_value = self.hmc.sshcnx.cmd(o_cmd).stdout_text.strip()
        d_msg = option + ": " + opt_value + " for partition " + \
            linux_machine.partition
        self.log.debug(d_msg)
        return opt_value

    def linux_check_add_cpu(self, linux_machine, quantity):
        """Check if the processors were added at the linux partition.

        Check both dmesg and /proc/cpuinfo to see if the current processor
        units are what they should be. Remember that you have to clean dmesg
        before adding and calling this function.
        """
        # Also, verify if /proc/cpuinfo show all processors
        proc_before = int(self.get_cpu_option(linux_machine, 'curr_procs'))
        c_cmd = 'cat /proc/cpuinfo'
        sdata = linux_machine.sshcnx.cmd(c_cmd).stdout_text.strip()
        cpuinfo_proc_lines = re.findall('processor.*:.*\n', sdata)
        d_msg = 'Checking if /proc/cpuinfo shows all processors correctly.'
        d_condition = len(cpuinfo_proc_lines) == ((proc_before) *
                                                  self.cpu_per_processor)
        self.log.check_log(d_msg, d_condition)

    def linux_check_rm_cpu(self, linux_machine, quantity_before,
                           quantity_removed):
        """Check if the processors were removed at the linux partition.
        Check both dmesg and /proc/cpuingo to see if the current processor
        units are what they should be. Remember that you have to clean dmesg
        before removing and calling this function.
        """
        # Also, verify if /proc/cpuinfo show all processors
        c_cmd = 'cat /proc/cpuinfo'
        cmd = process.run(c_cmd).stdout.decode()
        self.log.debug(cmd)
        cpuinfo_proc_lines = re.findall('processor.*:.*\n', cmd)
        d_msg = 'Checking if /proc/cpuinfo shows all processors correctly.'
        d_condition = len(cpuinfo_proc_lines) == \
            ((quantity_before - quantity_removed) *
             self.cpu_per_processor)
        self.log.check_log(d_msg, d_condition)

    def set_virtual_proc_and_proc_units(self, linux_machine, ideal_procs,
                                        ideal_proc_units, sleep_time):
        """Set the virtual proc and proc units to an ideal value.
        We do this to configure and set up the enviroment to be able to do
        our testing.
        """
        # Get the current values
        curr_procs = int(self.get_cpu_option(linux_machine, 'curr_procs'))
        curr_proc_units = float(self.get_cpu_option(linux_machine,
                                                    'curr_proc_units'))
        # Just to set everything at the correct values
        while curr_procs != ideal_procs or curr_proc_units != ideal_proc_units:
            # Add procs
            if curr_procs < ideal_procs:
                # Get how much we want to add
                procs_to_add = ideal_procs - curr_procs
                # Get the procs limit to know how much we can add
                procs_limit = int(curr_proc_units * 10) - curr_procs
                # Set how much we'll add
                if procs_to_add > procs_limit:
                    procs_to_add = procs_limit
                if procs_to_add > 0:
                    # Add 'procs_to_add'
                    a_cmd = 'chhwres -m ' + linux_machine.machine + \
                            ' -r proc -o a --procs ' + str(procs_to_add) + \
                            ' -p "' + linux_machine.partition + '"'
                    cmd_retcode = self.hmc.sshcnx.cmd(a_cmd)
                    if cmd_retcode.stdout_text != "":
                        self.log.error(cmd_retcode)
                        e_msg = 'Command ended with return code %s' % \
                                (cmd_retcode.stdout_text)
                        raise TestException(e_msg)
                    time.sleep(sleep_time)
                    a_msg = 'Adding %s virtual cpus to partition %s.' % \
                            (procs_to_add, linux_machine.partition)
                    a_condition = int(self.get_cpu_option(linux_machine,
                                                          'curr_procs') ==
                                      (curr_procs + procs_to_add))
                    self.log.check_log(a_msg, a_condition)
                    curr_procs += procs_to_add
            # Remove procs
            elif curr_procs > ideal_procs:
                # Get how much we want to remove
                procs_to_remove = curr_procs - ideal_procs
                # Get the procs limit to know how much we need to have,at least
                procs_limit = int(curr_proc_units) + 1
                # Set how much we'll remove
                if (curr_procs - procs_to_remove) < procs_limit:
                    procs_to_remove -= procs_limit - \
                        (curr_procs - procs_to_remove)
                # Remove 'procs_to_remove'
                if procs_to_remove != 0 and procs_to_remove > 0:
                    r_cmd = 'chhwres -m ' + linux_machine.machine + \
                            ' -r proc -o r --procs ' + str(procs_to_remove) + \
                            ' -p "' + linux_machine.partition + '"'
                    cmd_retcode = self.hmc.sshcnx.cmd(r_cmd)
                    if cmd_retcode.stdout_text != "":
                        self.log.error(cmd_retcode)
                        e_msg = 'Command failed with %s' % (
                            cmd_retcode.stdout_text)
                        raise TestException(e_msg)
                    time.sleep(sleep_time)
                    r_msg = 'Removing %s virtual cpus form partition %s.' % \
                            (procs_to_remove, linux_machine.partition)
                    r_condition = int(self.get_cpu_option(linux_machine,
                                                          'curr_procs') ==
                                      (curr_procs - procs_to_remove))
                    self.log.check_log(r_msg, r_condition)
                    curr_procs -= procs_to_remove
                else:
                    break

            # Add proc units
            if curr_proc_units < ideal_proc_units:
                # Get how much we want to add
                proc_units_to_add = ideal_proc_units - curr_proc_units
                # Get the proc units limit to know how much we can add
                proc_units_limit = curr_procs - curr_proc_units
                # Set how much we'll add
                if proc_units_to_add > proc_units_limit:
                    procs_to_add = proc_units_limit
                if proc_units_to_add > 0 and \
                        str(proc_units_to_add).isnumeric():
                    # Add 'proc_units_to_add'
                    a_cmd = 'chhwres -m ' + linux_machine.machine + \
                            ' -r proc -o a --procunits ' + \
                            str(proc_units_to_add) + ' -p "' + \
                            linux_machine.partition + '"'
                    cmd_retcode = self.hmc.sshcnx.cmd(a_cmd)
                    if cmd_retcode.stdout_text != "":
                        self.log.error(cmd_retcode.stdout_text)
                        e_msg = 'Command failed with %s' % \
                                (cmd_retcode.stdout_text)
                        raise TestException(e_msg)
                    time.sleep(sleep_time)
                    self.log.check_log('Adding %s proc units to %s.' %
                                       (proc_units_to_add,
                                        linux_machine.partition),
                                       float(self.get_cpu_option(
                                           linux_machine,
                                           'curr_proc_units') ==
                                           (curr_proc_units +
                                               proc_units_to_add)))
                    curr_proc_units += proc_units_to_add
                else:
                    break
            # Remove proc units
            elif curr_proc_units > ideal_proc_units:
                # Get how much we want to remove
                proc_units_to_remove = curr_proc_units - ideal_proc_units
                # Get the proc units limit to know how much we need to have,
                # at least
                proc_units_limit = float(curr_procs)/10
                # Set how much we'll remove
                if (curr_proc_units - proc_units_to_remove) < proc_units_limit:
                    proc_units_to_remove -= proc_units_limit - \
                        (curr_proc_units -
                         proc_units_to_remove)

                # Remove 'procs_to_remove'
                r_cmd = 'chhwres -m ' + linux_machine.machine + \
                        ' -r proc -o r --procunits ' + \
                        str(proc_units_to_remove) + ' -p "' + \
                        linux_machine.partition + '"'
                cmd_retcode = self.hmc.sshcnx.cmd(r_cmd)
                if cmd_retcode.stdout_text != "":
                    self.log.error(cmd_retcode.stdout_text)
                    e_msg = 'Command failed with %s' % (
                        cmd_retcode.stdout_text)
                    raise TestException(e_msg)
                time.sleep(sleep_time)
                r_msg = 'Removing %s proc units form partition %s.' % \
                        (proc_units_to_remove, linux_machine.partition)
                r_condition = float(self.get_cpu_option(linux_machine,
                                                        'curr_proc_units') ==
                                    (curr_proc_units - proc_units_to_remove))
                self.log.check_log(r_msg, r_condition)
                curr_proc_units -= proc_units_to_remove


class DedicatedCpu(TestCase):
    """
    DLPAR Dedicated CPU test case.

    The test procedure:
     1 - Get how many dedicated processors to test;
     2 - Check and set the test environment for both linux partitions;
     3 - Test (see run_test())

    Everything is fine if we don't have troubles with the HMC and the linux
    partitions are recognizing all added/removed cpus
    (using dmesg and /var/log/messages).
    """

    def __init__(self, config_payload, log='dedicated_cpu.log'):

        TestCase.__init__(self, log, 'Dedicated CPU', config_payload)

        # Get test configuration
        self.quant_to_test = 2
        self.quant_to_test = config_payload.get('ded_quantity_to_test')
        self.sleep_time = 60
        self.sleep_time = config_payload.get('sleep_time')

        self.log.check_log('Getting Test configuration.',
                           (self.quant_to_test is not None))
        self.log.debug("Testing with %s Dedicated CPU units." %
                       self.quant_to_test)
        self.get_connections(config_payload, clients='both')
        # Check linux partitions configuration
        self.__check_set_cfg(self.linux_1)
        self.__check_set_cfg(self.linux_2)

    def add_ded_cpu(self):
        self.__add_dedicated_cpu(self.linux_1, self.quant_to_test)
        self.log.info("Test finished successfully :)")

    def rem_ded_cpu(self):
        self.__remove_dedicated_cpu(self.linux_1, self.quant_to_test)
        self.log.info("Test finished successfully :)")

    def move_ded_cpu(self):
        self.__move_dedicated_cpu(self.linux_1, self.linux_2,
                                  self.quant_to_test)
        self.log.info("Test finished successfully :)")

    def mix_ded_ope(self):
        self.__add_dedicated_cpu(self.linux_1, self.quant_to_test)
        self.__move_dedicated_cpu(self.linux_1, self.linux_2,
                                  self.quant_to_test)
        self.__remove_dedicated_cpu(self.linux_2, self.quant_to_test)
        self.__add_dedicated_cpu(self.linux_2, self.quant_to_test)
        self.__move_dedicated_cpu(self.linux_2, self.linux_1,
                                  self.quant_to_test)
        self.__remove_dedicated_cpu(self.linux_1, self.quant_to_test)

        self.log.info("Test finished successfully :)")

    def __check_set_cfg(self, linux_machine):
        """
        Test and set machine configuration, to see if we can actually
        perform the test.

        Check:
         1 - Processor type (dedicated, shared);
         2 - Max cpus;
         3 - Have enought processor units;
        """
        self.log.info("Checking partition '%s' configuration." %
                      linux_machine.partition)
        self.log.debug("Machine: %s" % linux_machine.name)

        # Checking processor type
        curr_proc_mode = self.get_cpu_option(linux_machine, 'curr_proc_mode')
        d_msg = "Checking if linux partition '%s' is at dedicated mode" % \
                linux_machine.partition
        self.log.info('DEBUG: curr_proc_node %s' % curr_proc_mode)
        d_condition = (curr_proc_mode == "ded")
        self.log.check_log(d_msg, d_condition)

        # Get cpu configuration
        curr_min_procs = int(self.get_cpu_option(linux_machine,
                                                 'curr_min_procs'))
        curr_procs = int(self.get_cpu_option(linux_machine, 'curr_procs'))

        # Check dedicated cpu quantity

        # Set the curr_procs to curr_min_procs if we need it
        if curr_min_procs != curr_procs:
            s_msg = 'Setting the curr_procs to curr_min_procs at %s' \
                    % linux_machine.partition
            self.log.debug(s_msg)
            m_cmd = 'chhwres -m ' + linux_machine.machine + \
                    ' -r proc -o r --procs ' + \
                    str(curr_procs - curr_min_procs) + \
                    ' -p "' + linux_machine.partition + '"' + ' -w 0 '
            self.hmc.sshcnx.cmd(m_cmd, False)

            self.log.debug('Sleeping for %s seconds before proceeding' %
                           self.sleep_time)
            time.sleep(self.sleep_time)

            m_msg = 'Removing %s dedicated cpus form partition %s.' % \
                    (curr_procs - curr_min_procs, linux_machine.partition)
            m_condition = int(self.get_cpu_option(linux_machine,
                                                  'curr_procs')) == \
                curr_min_procs
            self.log.check_log(m_msg, m_condition)

        o_msg = 'Configuration settings for partition %s all correct.' % \
                linux_machine.partition
        self.log.info(o_msg)

    def __add_dedicated_cpu(self, linux_machine, quantity):
        """Add 'quantity' dedicated cpus at the a linux partition."""
        # Get all values before adding
        curr_procs_before = int(self.get_cpu_option(linux_machine,
                                                    'curr_procs'))
        time.sleep(self.sleep_time)

        # Add the cpus
        flag = ['proc', 'a', '--procs']
        self.cmd_result = self.Dlpar_engine(flag, linux_machine, quantity)
        self.log.debug('Sleeping for %s seconds before proceeding' %
                       self.sleep_time)
        time.sleep(self.sleep_time)

        # Check at HMC
        self.Dlpar_cpu_validation("a", linux_machine, quantity,
                                  curr_procs_before, self.cmd_result)

    def __move_dedicated_cpu(self, linux_machine_1, linux_machine_2, quantity):
        """
        Move 'quantity' dedicated cpus from linux_machine_1 to linux_machine_2.
        """
        # Get all values from both machines before moving
        curr_procs_before_1 = int(self.get_cpu_option(linux_machine_1,
                                                      'curr_procs'))
        curr_procs_before_2 = int(self.get_cpu_option(linux_machine_2,
                                                      'curr_procs'))
        # Move the processors
        linux_machine = []
        linux_machine.append(linux_machine_1)
        linux_machine.append(linux_machine_2)
        proc_info = []
        proc_info.append(curr_procs_before_1)
        proc_info.append(curr_procs_before_2)

        flag = ['proc', 'm', '--procs']
        self.cmd_result = self.Dlpar_engine(flag, linux_machine, quantity)
        self.log.debug('Sleeping for %s seconds before proceeding' %
                       self.sleep_time)
        time.sleep(self.sleep_time)

        # Check at HMC
        self.Dlpar_cpu_validation("m", linux_machine, quantity,
                                  proc_info, self.cmd_result)

    def __remove_dedicated_cpu(self, linux_machine, quantity):
        """Remove 'quantity' dedicated cpus from linux_machine."""
        # Get all values before removing
        curr_procs_before = int(self.get_cpu_option(linux_machine,
                                                    'curr_procs'))
        # Remove the cpus
        flag = ['proc', 'r', '--procs']
        self.cmd_result = self.Dlpar_engine(flag, linux_machine, quantity)
        self.log.debug('Sleeping for %s seconds before proceeding' %
                       self.sleep_time)
        time.sleep(self.sleep_time)

        # Check at HMC
        self.Dlpar_cpu_validation("r", linux_machine, quantity,
                                  curr_procs_before, self.cmd_result)


class CpuUnit(TestCase):
    """DLPAR CPU Units test case.

    The test procedure:
    1 - Get how much cpu units to test;
    2 - Check and set the test environment for both linux partitions;
    3 - Test (see run_test())

    Everything is fine if we don't have troubles with the HMC and with both
    linux partitions.
    """

    def __init__(self, config_payload, log='cpu_unit.log'):
        """Initialize the test case."""
        TestCase.__init__(self, log, "CPU Unit", config_payload)

        # Get test configuration
        self.quant_to_test = config_payload.get('cpu_quantity_to_test')
        self.sleep_time = config_payload.get('sleep_time')

        self.log.check_log('Getting Test configuration.',
                           self.quant_to_test is not None)
        self.log.debug("Testing with %s CPU Units." % self.quant_to_test)

        self.get_connections(config_payload, clients='both')
        # self.get_connections()

        # Check linux partitions configuration
        self.__check_set_cfg(self.linux_1)
        self.__check_set_cfg(self.linux_2)

    def __check_set_cfg(self, linux_machine):
        """Test and set machine configuration, to see if we can do the test.

        Check:
        1 - Processor type (dedicated, shared);
        2 - Max cpu units;
        3 - Have enought virtual cpu units;
        """
        self.log.info("Checking partition '%s' configuration." %
                      linux_machine.partition)
        self.log.debug("Machine: %s" % linux_machine.name)

        # Checking processor type
        curr_proc_mode = self.get_cpu_option(linux_machine, 'curr_proc_mode')
        c_msg = "Checking if linux partition '%s' is at shared mode" % \
                linux_machine.partition
        c_condition = (curr_proc_mode == "shared")
        self.log.check_log(c_msg, c_condition)

        # Get cpu configuration
        curr_max_procs = int(self.get_cpu_option(linux_machine,
                                                 'curr_max_procs'))
        curr_min_proc_units = float(self.get_cpu_option(linux_machine,
                                                        'curr_min_proc_units'))
        curr_max_proc_units = float(self.get_cpu_option(linux_machine,
                                                        'curr_max_proc_units'))

        # Check if the system support the virtual cpu inits to add
        c_msg = "Checking if the machine %s supports adding %s cpu units." % \
                (linux_machine.machine, self.quant_to_test)
        c_condition = self.quant_to_test <= (curr_max_proc_units -
                                             curr_min_proc_units)
        self.log.check_log(c_msg, c_condition)

        # This is the minimal virtual proc units to have
        ideal_procs = int(curr_min_proc_units + self.quant_to_test)
        if (((curr_min_proc_units + self.quant_to_test) % 1) != 0.0):
            ideal_procs += + 1

        # This is the ideal proc units to have
        # XXX: We need to improve this, because we need to check the min
        # XXX: virtual cpu, the max virtual cpu and etc
        ideal_proc_units = float(ideal_procs)/10
        if ideal_proc_units < curr_min_proc_units:
            ideal_proc_units = curr_min_proc_units

        # Check if the system support the needed virtual cpu quantity to have
        c_msg = "Checking if %s profile supports %d virtual cpu units." % \
                (linux_machine.machine, ideal_procs)
        self.log.check_log(c_msg, ideal_procs <= curr_max_procs)

        self.log.debug('Setting the curr_procs at partition %s to %d' %
                       (linux_machine.partition, ideal_procs))
        self.log.debug('Setting the curr_proc_units at partition %s to %f' %
                       (linux_machine.partition, ideal_proc_units))

        # Add and Remove all needed virtual cpus and proc units
        self.set_virtual_proc_and_proc_units(linux_machine, ideal_procs,
                                             ideal_proc_units, self.sleep_time)

        i_msg = 'Configuration settings for partition %s correct.' % \
                linux_machine.partition
        self.log.info(i_msg)

    def add_proc(self):
        self.__add_cpu_units(self.linux_1, self.quant_to_test)
        self.log.info("Test finished successfully.")

    def remove_proc(self):
        self.__remove_cpu_units(self.linux_1, self.quant_to_test)
        self.log.info("Test finished successfully.")

    def move_proc(self):
        self.__move_cpu_units(self.linux_1, self.linux_2,
                              self.quant_to_test)
        self.log.info("Test finished successfully.")

    def mix_proc_ope(self):
        self.__add_cpu_units(self.linux_1, self.quant_to_test)
        self.__move_cpu_units(self.linux_1, self.linux_2,
                              self.quant_to_test)
        self.__remove_cpu_units(self.linux_2, self.quant_to_test)
        self.__add_cpu_units(self.linux_2, self.quant_to_test)
        self.__move_cpu_units(self.linux_2, self.linux_1,
                              self.quant_to_test)
        self.__remove_cpu_units(self.linux_1, self.quant_to_test)
        self.log.info("Test finished successfully.")

    def __add_cpu_units(self, linux_machine, quantity):
        """Add 'quantity' proc units at the a linux partition."""
        # Get all values before adding
        curr_proc_units_before = float(self.get_cpu_option(linux_machine,
                                                           'curr_proc_units'))

        # Add the cpus
        flag = ['proc', 'a', '--procunits']
        self.cmd_result = self.Dlpar_engine(flag, linux_machine, quantity)
        self.log.debug('Sleeping for %s seconds before proceeding' %
                       self.sleep_time)
        time.sleep(self.sleep_time)

        # Call to Dlpar_validation
        self.Dlpar_cpu_validation("cpu_a", linux_machine, quantity,
                                  curr_proc_units_before, self.cmd_result)

    def __move_cpu_units(self, linux_machine_1, linux_machine_2, quantity):
        """
        Move 'quantity' proc units from linux_machine_1 to linux_machine_2.
        """
        # Get all values from both machines before moving
        curr_proc_units_before_1 = float(self.get_cpu_option
                                         (linux_machine_1, 'curr_proc_units'))
        curr_proc_units_before_2 = float(self.get_cpu_option
                                         (linux_machine_2, 'curr_proc_units'))

        # Move the proc units
        linux_machine = []
        linux_machine.append(linux_machine_1)
        linux_machine.append(linux_machine_2)
        proc_info = []
        proc_info.append(curr_proc_units_before_1)
        proc_info.append(curr_proc_units_before_2)

        flag = ['proc', 'm', '--procunits']
        self.cmd_output = self.Dlpar_engine(flag, linux_machine, quantity)

        self.log.debug(self.cmd_output)
        self.log.debug('Sleeping for %s seconds before proceeding' %
                       self.sleep_time)
        time.sleep(self.sleep_time)

        # Check at HMC
        self.Dlpar_cpu_validation("cpu_m", linux_machine, quantity,
                                  proc_info, self.cmd_output)

    def __remove_cpu_units(self, linux_machine, quantity):
        """Remove 'quantity' proc units from linux_machine."""
        # Get all values before removing
        curr_proc_units_before = float(self.get_cpu_option(linux_machine,
                                                           'curr_proc_units'))
        # Remove the cpus
        flag = ['proc', 'r', '--procunits']
        self.cmd_output = self.Dlpar_engine(flag, linux_machine, quantity)

        self.log.debug(self.cmd_output)
        self.log.debug('Sleeping for %s seconds before proceeding' %
                       self.sleep_time)
        time.sleep(self.sleep_time)

        # Check at HMC
        self.Dlpar_cpu_validation("cpu_r", linux_machine, quantity,
                                  curr_proc_units_before, self.cmd_output)


class Memory(TestCase):
    """DLPAR memory add/move/remove test case.

   The test procedure:
    1 - Get how much of memory to test;
    2 - Check the test environment for both linux partitions;
    3 - Test (see run_test())

    Everything is fine if we don't have troubles with the HMC and the linux
    partitions are recognizing all added memory (using /proc/meminfo).
    """

    def __init__(self, config_payload, log='memory.log'):

        TestCase.__init__(self, log, 'Memory', config_payload)

        # Get test configuration
        self.quant_to_test = 1024
        self.quant_to_test = config_payload.get('mem_quantity_to_test')
        self.sleep_time = 60
        self.sleep_time = config_payload.get('sleep_time')

        self.get_connections(config_payload, clients='both')

        self.linux_machine = config_payload.get('mem_linux_machine')
        # self.linux_machine = self.config.get('memory', 'linux_machine')
        if self.linux_machine == 'primary':
            self.get_connections(config_payload, clients='primary')
            # self.get_connections(clients='primary')
            self.linux = self.linux_1
        elif self.linux_machine == 'secondary':
            self.get_connections(config_payload, clients='secondary')
            # self.get_connections(clients='secondary')
            self.linux = self.linux_2
        else:
            e_msg_1 = "Invalid 'linux_machine' at the configuration file."
            e_msg_2 = "Please use either 'primary' or 'secondary'."
            self.log.error(e_msg_1)
            self.log.error(e_msg_2)
            raise TestException(e_msg_1 + " " + e_msg_2)

        self.log.debug("Testing with %s megabytes of memory." %
                       self.quant_to_test)
        c_msg = 'Getting Test configuration.'
        c_condition = self.quant_to_test is not None
        self.log.check_log(c_msg, c_condition)

        # Check linux partitions configuration
        try:
            self.__check_set_cfg(self.linux_1)
        except AttributeError:
            self.log.debug('linux_1 not found, so not checking it.')

        try:
            self.__check_set_cfg(self.linux_2)
        except AttributeError:
            self.log.debug('linux_2 not found, so not checking it.')

    def __check_set_cfg(self, linux_machine):
        """Test the machine configuration, to see if we can do the test.

        Check:
        1 - If machine has enough memory to add;
        2 - If profile supports adding 'quant_to_test' of memory;
        """
        self.log.info("Checking partition '%s' configuration." %
                      linux_machine.partition)
        self.log.debug("Machine: %s" % linux_machine.name)

        # Getting memory configuration
        m_cmd = 'lshwres -m ' + linux_machine.machine + \
                ' --level sys -r mem -F curr_avail_sys_mem'
        # curr_avail_sys_mem = int(self.hmc.sshcnx.cmd(m_cmd))
        curr_avail_sys_mem = int(
            self.hmc.sshcnx.cmd(m_cmd).stdout_text.strip())
        curr_max_mem = int(self.get_mem_option(linux_machine, 'curr_max_mem'))
        curr_mem = int(self.get_mem_option(linux_machine, 'curr_mem'))

        # Check if the system support the memory units to add
        m_msg = "Checking if the system has enough available memory to add."
        m_condition = self.quant_to_test <= curr_avail_sys_mem
        self.log.check_log(m_msg, m_condition)

        p_msg = "Checking if the system's profile supports %s of memory." % \
                (self.quant_to_test + curr_mem)
        p_condition = curr_mem + self.quant_to_test <= curr_max_mem
        self.log.check_log(p_msg, p_condition)

        self.log.info('Configuration data for LPAR %s is OK.' %
                      linux_machine.partition)

    def mem_add(self):
        self.__add_memory(self.linux, self.quant_to_test)
        self.log.info("Test finished successfully.")

    def mem_rem(self):
        self.__remove_memory(self.linux, self.quant_to_test)
        self.log.info("Test finished successfully.")

    def mem_move(self):
        self.__move_memory(self.linux_1, self.linux_2, self.quant_to_test)
        self.log.info("Test finished successfully.")

    def mem_mix_ope(self):
        self.__add_memory(self.linux_1, self.quant_to_test)
        self.__move_memory(self.linux_1, self.linux_2, self.quant_to_test)
        self.__remove_memory(self.linux_2, self.quant_to_test)
        self.__add_memory(self.linux_2, self.quant_to_test)
        self.__move_memory(self.linux_2, self.linux_1, self.quant_to_test)
        self.__remove_memory(self.linux_1, self.quant_to_test)
        self.log.info("Test finished successfully.")

    def __add_memory(self, linux_machine, quantity):
        """
        Add 'quantity' of memory at the linux partition.
        """
        # Get all values before adding
        curr_mem_before = int(self.get_mem_option(linux_machine, 'curr_mem'))
        curr_mem_proc_before = self.check_memory_proc(linux_machine)

        # Add the memory
        flag = ['mem', 'a', '-q']
        self.cmd_result = self.Dlpar_engine(flag, linux_machine, quantity)

        self.log.debug('Sleeping for %s seconds before proceeding' %
                       self.sleep_time)
        time.sleep(self.sleep_time)

        # Check at HMC
        mem_info = []
        mem_info.append(curr_mem_before)
        mem_info.append(curr_mem_proc_before)
        self.Dlpar_mem_validation("a", linux_machine, quantity,
                                  mem_info, self.cmd_result)

    def __remove_memory(self, linux_machine, quantity):
        """Remove 'quantity' of memory from a linux partition."""
        # Get all values before adding
        curr_mem_before = int(self.get_mem_option(linux_machine, 'curr_mem'))
        curr_mem_proc_before = self.check_memory_proc(linux_machine)

        # Remove the memory
        flag = ['mem', 'r', '-q']
        self.cmd_result = self.Dlpar_engine(flag, linux_machine, quantity)

        self.log.debug('Sleeping for %s seconds before proceeding' %
                       self.sleep_time)
        time.sleep(self.sleep_time)
        mem_info = []
        mem_info.append(curr_mem_before)
        mem_info.append(curr_mem_proc_before)

        # Check at HMC
        self.Dlpar_mem_validation("r", linux_machine, quantity,
                                  mem_info, self.cmd_result)

    def __move_memory(self, linux_machine_1, linux_machine_2, quantity):
        """
        Move 'quantity' of memory from linux partition 1 to linux partition 2.
        """
        # Get all values before adding
        curr_mem_before_1 = int(self.get_mem_option(linux_machine_1,
                                                    'curr_mem'))
        curr_mem_before_2 = int(self.get_mem_option(linux_machine_2,
                                                    'curr_mem'))

        # Remove the memory
        curr_mem_proc_before_1 = self.check_memory_proc(linux_machine_1)
        curr_mem_proc_before_2 = self.check_memory_proc(linux_machine_2)
        mem_info = []
        mem_info.append(curr_mem_before_1)
        mem_info.append(curr_mem_before_2)
        mem_info.append(curr_mem_proc_before_1)
        mem_info.append(curr_mem_proc_before_2)

        linux_machine = []
        linux_machine.append(linux_machine_1)
        linux_machine.append(linux_machine_2)
        flag = ['mem', 'm', '-q']
        self.cmd_result = self.Dlpar_engine(flag, linux_machine, quantity)

        self.log.debug('Going to sleep for %s s' % self.sleep_time)
        time.sleep(self.sleep_time)

        # Check at HMC
        self.Dlpar_mem_validation("m", linux_machine, quantity, mem_info,
                                  self.cmd_result)
