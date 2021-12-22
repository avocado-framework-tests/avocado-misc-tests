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
import logging, re, time

# DLPAR API imports
from dlpar_api.pxssh import pxssh
from dlpar_api.config import TestConfig

__all__ = ['TestException', 'MyPxssh', 'SshMachine', 'TestLog', 'TestCase']

CONFIG_FILE = TestConfig("config/tests.cfg")

class TestException(Exception):
    """Base Class for all test exceptions."""

    def __init__(self, value):
        Exception.__init__(self)
        self.value = value

    def __str__(self):
        return str(self.value)


class MyPxssh(pxssh):
    """My pxssh class, with more methods."""

    def __init__(self, log = None):
        pxssh.__init__(self)
        # Set the log file if we have one
        self.log = log


    def run_command(self, command, string = True, code = False):
        """Execute a command at the ssh conection.

        You can choose if you want the returned string, the return code
        or both.
        """
        self.__log("SSH command on %s: '%s'" % (self.server, command))

        # In some situations, with asynchronous commands, we might not get 
        # an answer right after we try to check the exit code. so in this
        # case, we need to wait and try again.
        self.sendline("bind 'set enable-bracketed-paste off'")
        self.expect('\r\n')
        self.prompt()
        self.sendline(command)
        self.expect('\r\n')
        self.prompt()
        result = self.before.strip()
        self.sendline('echo $?')
        self.expect('\r\n')
        self.prompt()
        return_code = self.before.strip()
        try:
            int(return_code)
        except ValueError:
            self.__log('Got invalid return code. Trying again after 240s.')
            time.sleep(240)
            self.expect('\r\n')
            self.prompt()
            return_code = self.before.strip()
            # If something goes wrong after 240 seconds, then it's better to
            # throw an exception...
            try:
                int(return_code)
            except ValueError:
                e_msg = 'Got invalid return code again. Aborting.'
                raise ValueError(e_msg)

        self.__log("Command output: '%s'" % result)
        self.__log("Return code: '%s'" % return_code)

        if string and code:
            return result, return_code
        elif string:
            return result
        elif code:
            return return_code


    def __log(self, message):
        """Just to use the log if we have one."""
        if self.log:
            self.log.debug(message)


class SshMachine:
    """The machine that we reach using the ssh protocol.

    This class take every important information about the machine
    and also the ssh connection.
    """

    def __init__(self, machine_type, log = None):
        """Get every machine information."""
        self.name = CONFIG_FILE.get(machine_type, 'name')
        self.user = CONFIG_FILE.get(machine_type, 'user')
        self.passwd = CONFIG_FILE.get(machine_type, 'passwd')
        self.machine = CONFIG_FILE.get(machine_type, 'machine')
        self.partition = CONFIG_FILE.get(machine_type, 'partition')

        self.log = log
        self.sshcnx = self.__init_ssh(self.user, self.passwd, self.name)

    def __init_ssh(self, user, passwd, server):
        """Return the SSH connection"""
        self.log.debug('Initializing connection for %s' % server)
        ssh_cnx = MyPxssh(self.log)
        if not ssh_cnx.login(server, user, passwd):
            raise TestException('Failed to login at machine %s.' % server)
        return ssh_cnx


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
        log_file.setLevel(self.__get_log_level(CONFIG_FILE.get('log',
                                                           'file_level')))
        format_string = '%(asctime)s %(levelname)-8s %(message)s'
        formatter = logging.Formatter(format_string,
                                      datefmt='%a, %d %b %Y %H:%M:%S')
        log_file.setFormatter(formatter)
        self.addHandler(log_file)

        # console log output configuration
        console = logging.StreamHandler()
        console.setLevel(self.__get_log_level(CONFIG_FILE.get('log',
                                                              'console_level')))
        formatter = logging.Formatter('%(levelname)-8s: %(message)s')
        console.setFormatter(formatter)
        self.addHandler(console)


    def __get_log_level(self, log_level):
        """Just to translate the strig format to logging format."""
        if log_level not in ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'):
            self.warning('Misconfigured log level %s. Assuming INFO.' % \
                         log_level)
            return logging.INFO
        return getattr(logging, log_level)


    def check_log(self, message, code, die = True):
        """Catch the code and print the message accordantly

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

    def __init__(self, log_file, test_name):
        """Initialize the test case.

        Set the log file, get all machines connection and the config file
        """
        # Set the log
        self.log = TestLog(log_file)
        self.log.info('Starting %s Test Case.' % test_name)

        # Get test configuration
        self.config = CONFIG_FILE
        ## Get common values for any test case
        self.cpu_per_processor = int(self.config.get('machine_cfg',
                                                     'cpu_per_processor'))


    def get_connections(self, clients='both'):
        """
        Get connections for the HMC and the linux clients.

        @param clients: The clients we are going to connect to. It can be
                        one of 'primary', 'secondary' or 'both'.
        """
        # Get connection for the machines
        try:
            # Hmc ...
            self.hmc = SshMachine('hmc', self.log)
            self.log.debug('Login to HMC successful.')
            # ... and the linux partitions
            if clients == 'primary' or clients == 'both':
                self.linux_1 = SshMachine('linux_primary', self.log)
                self.log.debug('Login to 1st linux LPAR successful.')
            if clients == 'secondary' or clients == 'both':
                self.linux_2 = SshMachine('linux_secondary', self.log)
                self.log.debug('Login to 2nd linux LPAR successful.')

            self.log.check_log('Getting Machine connections.', True)
        except:
            self.log.check_log('Getting Machine connections.', False, False)
            raise


    def run_test(self):
        """Run the test case."""
        pass


    def get_cpu_option(self, linux_machine, option):
        """Just to help getting a cpu option from hmc."""

        o_cmd = 'lshwres -m ' + linux_machine.machine + \
                ' --level lpar -r proc --filter lpar_names="' + \
                linux_machine.partition + '" -F ' + option
        opt_value = self.hmc.sshcnx.run_command(o_cmd)

        d_msg = option + ": " + opt_value + " for partition " + \
                linux_machine.partition
        self.log.debug(d_msg)
        return opt_value


    def get_mem_option(self, linux_machine, option):
        """Just to help getting a memory option from hmc."""

        o_cmd = 'lshwres -m ' + linux_machine.machine + \
                ' --level lpar -r mem --filter lpar_names="' + \
                linux_machine.partition + '" -F ' + option
        opt_value = self.hmc.sshcnx.run_command(o_cmd)

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
        c_cmd = 'cat /proc/cpuinfo'
        cpuinfo_proc_lines = re.findall('processor.*:.*\n',
                                        linux_machine.sshcnx.run_command(c_cmd))
        d_msg = 'Checking if /proc/cpuinfo shows all processors correctly.'
        d_condition = len(cpuinfo_proc_lines) == \
                      ((quantity + int(self.get_cpu_option(linux_machine,
                                       'curr_min_procs'))) * \
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
        cpuinfo_proc_lines = re.findall('processor.*:.*\n',
                                        linux_machine.sshcnx.run_command(c_cmd))
        d_msg = 'Checking if /proc/cpuinfo shows all processors correctly.'
        d_condition = len(cpuinfo_proc_lines) == \
                      ((quantity_before - quantity_removed) * \
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
                    cmd_out, cmd_retcode = self.hmc.sshcnx.run_command(a_cmd,
                                                                       True,
                                                                       True)
                    if cmd_retcode != "0":
                        self.log.error(cmd_out)
                        e_msg = 'Command ended with return code %s' % \
                                (cmd_retcode)
                        raise TestException(e_msg)
                    time.sleep(sleep_time)
                    a_msg = 'Adding %s virtual cpus to partition %s.' % \
                            (procs_to_add, linux_machine.partition)
                    a_condition = int(self.get_cpu_option(linux_machine,
                                      'curr_procs') == \
                                      (curr_procs + procs_to_add))
                    self.log.check_log(a_msg, a_condition)
                    curr_procs += procs_to_add
            # Remove procs
            elif curr_procs > ideal_procs:
                # Get how much we want to remove
                procs_to_remove = curr_procs - ideal_procs
                # Get the procs limit to know how much we need to have, at least
                procs_limit = int(curr_proc_units) + 1
                # Set how much we'll remove
                if (curr_procs - procs_to_remove) < procs_limit:  
                    procs_to_remove -= procs_limit - \
                                       (curr_procs - procs_to_remove)
                # Remove 'procs_to_remove'
                r_cmd = 'chhwres -m ' + linux_machine.machine + \
                        ' -r proc -o r --procs ' + str(procs_to_remove) + \
                        ' -p "' + linux_machine.partition + '"'
                cmd_out, cmd_retcode = self.hmc.sshcnx.run_command(r_cmd, True,
                                                                   True)
                if cmd_retcode != "0":
                    self.log.error(cmd_out)
                    e_msg = 'Command ended with return code %s' % (cmd_retcode)
                    raise TestException(e_msg)
                time.sleep(sleep_time)
                r_msg = 'Removing %s virtual cpus form partition %s.' % \
                        (procs_to_remove, linux_machine.partition)
                r_condition = int(self.get_cpu_option(linux_machine,
                                                      'curr_procs') == \
                              (curr_procs - procs_to_remove))
                self.log.check_log(r_msg, r_condition)
                curr_procs -= procs_to_remove

            # Add proc units
            if curr_proc_units < ideal_proc_units:
                # Get how much we want to add
                proc_units_to_add = ideal_proc_units - curr_proc_units
                # Get the proc units limit to know how much we can add
                proc_units_limit = curr_procs - curr_proc_units
                # Set how much we'll add
                if proc_units_to_add > proc_units_limit:  
                    procs_to_add = proc_units_limit
                if proc_units_to_add > 0:
                    # Add 'proc_units_to_add'
                    a_cmd = 'chhwres -m ' + linux_machine.machine + \
                            ' -r proc -o a --procunits ' + \
                            str(proc_units_to_add) + ' -p "' + \
                            linux_machine.partition + '"'
                    cmd_out, cmd_retcode = self.hmc.sshcnx.run_command(a_cmd,
                                                                       True,
                                                                       True)
                    if cmd_retcode != "0":
                        self.log.error(cmd_out)
                        e_msg = 'Command ended with return code %s' % \
                                (cmd_retcode)
                        raise TestException(e_msg)
                    time.sleep(sleep_time)
                    self.log.check_log('Adding %s proc units to %s.' % \
                                       (proc_units_to_add,
                                       linux_machine.partition),
                                       float(self.get_cpu_option(linux_machine,
                                       'curr_proc_units') == \
                                       (curr_proc_units + proc_units_to_add)))
                    curr_proc_units += proc_units_to_add

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
                                            (curr_proc_units - \
                                            proc_units_to_remove)

                # Remove 'procs_to_remove'
                r_cmd = 'chhwres -m ' + linux_machine.machine + \
                        ' -r proc -o r --procunits ' + \
                        str(proc_units_to_remove) + ' -p "' + \
                        linux_machine.partition + '"'
                cmd_out, cmd_retcode = self.hmc.sshcnx.run_command(r_cmd, True,
                                                                   True)
                if cmd_retcode != "0":
                    self.log.error(cmd_out)
                    e_msg = 'Command ended with return code %s' % (cmd_retcode)
                    raise TestException(e_msg)
                time.sleep(sleep_time)
                r_msg = 'Removing %s proc units form partition %s.' % \
                        (proc_units_to_remove, linux_machine.partition)
                r_condition = float(self.get_cpu_option(linux_machine, 
                                                        'curr_proc_units') == \
                              (curr_proc_units - proc_units_to_remove))
                self.log.check_log(r_msg, r_condition)
                curr_proc_units -= proc_units_to_remove
