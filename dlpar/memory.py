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
# Author(Modified): Kalpana Shetty <kalshett@in.ibm.com>

"""
Test to verify memory DLPAR. Operations tested:
 * Add
 * Move
 * Remove

This test assumes that we have 2 power LPARS properly configured to start.
"""
import time
from dlpar_api.api import TestCase, TestException

__all__ = ['Memory']

class Memory(TestCase):
    """DLPAR memory add/move/remove test case.

   The test procedure:
    1 - Get how much of memory to test;
    2 - Check the test environment for both linux partitions;
    3 - Test (see run_test())

    Everything is fine if we don't have troubles with the HMC and the linux 
    partitions are recognizing all added memory (using /proc/meminfo).
    """

    def __prep_mem_cfg(self, linux_machine):
        """
         Activate shared partition with the user defined min/desired/max

         Check:
          1 - Shutdown the partition (shared);
          2 - Define memory profile with min, desired, max from config
        """
        u_cmd = 'chsyscfg -r prof -m %s -i "lpar_name=%s,name=default_profile, \
                min_mem=%d,desired_mem=%d,max_mem=%d, \
                min_num_huge_pages=0,desired_num_huge_pages=0, \
                max_num_huge_pages=0" --force' % \
                (linux_machine.machine,linux_machine.name, \
                self.min_mem,self.desired_mem,self.max_mem)

        self.log.info('DEBUG: Memory lpar setup %s' % u_cmd)
        self.hmc.sshcnx.run_command(u_cmd, False)

        d_cmd = 'chsysstate -m %s -o shutdown -r lpar -n %s --immed' % \
                (linux_machine.machine,linux_machine.name)
        self.log.info('DEBUG: Memory lpar setup %s' % d_cmd)
        self.hmc.sshcnx.run_command(d_cmd, False)
        time.sleep(20)

        a_cmd = 'chsysstate -m %s -r lpar -o on -n %s -f default_profile \
                --force' % (linux_machine.machine,linux_machine.name)
        self.log.info('DEBUG: Memory lpar setup %s' % a_cmd)
        self.hmc.sshcnx.run_command(a_cmd, False)
        time.sleep(120)

    def __init__(self, log = 'memory.log'):
        TestCase.__init__(self, log, 'Memory')

        # Get test configuration
        self.quant_to_test = int(self.config.get('memory',
                                                 'quantity_to_test'))
        self.sleep_time = int(self.config.get('memory', 'sleep_time'))
        self.iterations = int(self.config.get('memory', 'iterations'))

        self.min_mem = int(self.config.get('memory','min_mem'))
        self.desired_mem = int(self.config.get('memory','desired_mem'))
        self.max_mem = int(self.config.get('memory','max_mem'))

        # shutdown the paritition, update profile with min,desired,max, activate
        self.get_connections()
        self.__prep_mem_cfg(self.linux_1)
        self.__prep_mem_cfg(self.linux_2)
        self.get_connections()

        self.mode = self.config.get('memory', 'mode')
        if self.mode == 'add' or self.mode == 'add_remove':
            self.linux_machine = self.config.get('memory', 'linux_machine')
            if self.linux_machine == 'primary':
                self.get_connections(clients='primary')
                self.linux = self.linux_1
            elif self.linux_machine == 'secondary':
                self.get_connections(clients='secondary')
                self.linux = self.linux_2
            else:
                e_msg_1 = "Invalid 'linux_machine' at the configuration file."
                e_msg_2 = "Please use either 'primary' or 'secondary'."
                self.log.error(e_msg_1)
                self.log.error(e_msg_2)
                raise TestException(e_msg_1 + " " + e_msg_2)
        elif self.mode == 'add_move_remove':
            self.get_connections()
        else:
            e_msg_1 = "Invalid 'mode' at the configuration file."
            e_msg_2 = "Use one of 'add', 'add_remove', 'add_move_remove'."
            self.log.error(e_msg_1)
            self.log.error(e_msg_2)
            raise TestException(e_msg_1 + " " + e_msg_2)

        self.log.debug("Testing with %s megabytes of memory." % \
                       self.quant_to_test)
        c_msg = 'Getting Test configuration.'
        c_condition = self.quant_to_test != None
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
        self.log.info("Checking partition '%s' configuration." % \
                      linux_machine.partition)
        self.log.debug("Machine: %s" % linux_machine.name)

        # Getting memory configuration
        m_cmd = 'lshwres -m ' + linux_machine.machine + \
                ' --level sys -r mem -F curr_avail_sys_mem'
        curr_avail_sys_mem = int(self.hmc.sshcnx.run_command(m_cmd))
        curr_max_mem = int(self.get_mem_option(linux_machine, 'curr_max_mem'))
        curr_mem = int(self.get_mem_option(linux_machine, 'curr_mem'))

        ## Check if the system support the memory units to add
        m_msg = "Checking if the system has enough available memory to add."
        m_condition = self.quant_to_test <= curr_avail_sys_mem
        self.log.check_log(m_msg, m_condition)

        p_msg = "Checking if the system's profile supports %s of memory." % \
                (self.quant_to_test + curr_mem)
        p_condition = curr_mem + self.quant_to_test <= curr_max_mem
        self.log.check_log(p_msg, p_condition)

        self.log.info('Configuration data for LPAR %s is OK.' % \
                      linux_machine.partition)


    def run_test(self):
        """Run the test.

        1 - Add 'quantity' of memory to the first partition;
        2 - Move 'quantity' of memory from the first to the second partition;
        3 - Remove 'quantity' of memory from the second partition;

        4 - Repeat steps 1 to 3, this time starting from the second partition.
        """
        self.log.info("Initiating the test.")
        for iteration in range(1, self.iterations + 1):
            self.log.info("Running iteration %d" % iteration)
            if self.mode == 'add':
                self.__add_memory(self.linux, self.quant_to_test)
            elif self.mode == 'add_remove':
                self.__add_memory(self.linux, self.quant_to_test)
                self.__remove_memory(self.linux, self.quant_to_test)
            elif self.mode == 'add_move_remove':
                self.__add_memory(self.linux_1, self.quant_to_test)
                self.__move_memory(self.linux_1, self.linux_2,
                                   self.quant_to_test)
                self.__remove_memory(self.linux_2, self.quant_to_test)

                self.__add_memory(self.linux_2, self.quant_to_test)
                self.__move_memory(self.linux_2, self.linux_1,
                                   self.quant_to_test)
                self.__remove_memory(self.linux_1, self.quant_to_test)

        self.log.info("Test finished successfully.")


    def __check_memory_proc(self, machine):
        """
        Check on a linux client how much physical memory we have.
        """
        p_cmd = "cat /proc/meminfo | grep MemTotal | awk -F' ' '{ print $2 }'"
        self.log.info('Checking memory under linux on %s' % machine.partition)
        self.log.debug('Checking memory under linux on %s' % machine.partition)
        memory = int(machine.sshcnx.run_command(p_cmd))
        return memory


    def __add_memory(self, linux_machine, quantity):
        """
        Add 'quantity' of memory at the linux partition.
        """
        # Get all values before adding
        curr_mem_before = int(self.get_mem_option(linux_machine, 'curr_mem'))
        curr_mem_proc_before = self.__check_memory_proc(linux_machine)

        # Add the memory
        a_cmd = 'chhwres -m ' + linux_machine.machine + ' -r mem -o a -q ' + \
                str(quantity) + ' -p "' + linux_machine.partition + '"' + \
                ' -w 0 '
        self.hmc.sshcnx.run_command(a_cmd)

        self.log.debug('Sleeping for %s seconds before proceeding' %
                       self.sleep_time)
        time.sleep(self.sleep_time)

        # Check at HMC
        a_msg = 'Adding %d megabytes of memory to partition %s.' % \
                (quantity, linux_machine.partition)
        a_condition = (int(self.get_mem_option(linux_machine, 'curr_mem')) == \
                       curr_mem_before + quantity)
        if not self.log.check_log(a_msg, a_condition, False):
            e_msg = 'Error happened when adding memory to %s' % \
                    linux_machine.partition
            self.log.error(e_msg)
            raise TestException(e_msg)

        # Check at Linux partition (using /proc/meminfo)
        curr_mem_proc_after = self.__check_memory_proc(linux_machine)
        p_msg = 'Checking if /proc/meminfo shows all added memory.'
        p_condition = ((curr_mem_proc_after - curr_mem_proc_before)/1024 == \
                      quantity)
        self.log.check_log(p_msg, p_condition)


    def __remove_memory(self, linux_machine, quantity):
        """Remove 'quantity' of memory from a linux partition."""
        # Get all values before adding
        curr_mem_before = int(self.get_mem_option(linux_machine, 'curr_mem'))
        curr_mem_proc_before = self.__check_memory_proc(linux_machine)

        # Remove the memory
        r_cmd = 'chhwres -m ' + linux_machine.machine + ' -r mem -o r -q ' + \
                str(quantity) + ' -p "' + linux_machine.partition + '"' + \
                ' -w 0 '
        self.hmc.sshcnx.run_command(r_cmd)
        self.log.debug('Sleeping for %s seconds before proceeding' %
                       self.sleep_time)
        time.sleep(self.sleep_time)

        # Check at HMC
        r_msg = 'Removing %d megabytes of memory from partition %s.' % \
                (quantity, linux_machine.partition)
        r_condition = (int(self.get_mem_option(linux_machine, 'curr_mem')) == \
                       (curr_mem_before - quantity))
        if not self.log.check_log(r_msg, r_condition, False):
            e_msg = 'Error happened when removing memory from %s' % \
                    linux_machine.partition
            self.log.error(e_msg)
            raise TestException(e_msg)

        # Check at Linux partition (using /proc/meminfo)
        curr_mem_proc_after = self.__check_memory_proc(linux_machine)
        p_msg = 'Checking if /proc/meminfo shows all removed memory.'
        p_condition = ((curr_mem_proc_before - curr_mem_proc_after)/1024 == \
                       quantity)
        self.log.check_log(p_msg, p_condition)


    def __move_memory(self, linux_machine_1, linux_machine_2, quantity):
        """
        Move 'quantity' of memory from linux partition 1 to linux partition 2.
        """
        # Get all values before adding
        curr_mem_before_1 = int(self.get_mem_option(linux_machine_1,
                                'curr_mem'))
        curr_mem_before_2 = int(self.get_mem_option(linux_machine_2,
                                'curr_mem'))

        curr_mem_proc_before_1 = self.__check_memory_proc(linux_machine_1)
        curr_mem_proc_before_2 = self.__check_memory_proc(linux_machine_2)

        # Move the memory
        m_cmd = 'chhwres -m ' + linux_machine_1.machine + ' -r mem -o m -q ' + \
                str(quantity) + ' -p "' + linux_machine_1.partition + \
                ' -t "' + linux_machine_2.partition + '"' + ' -w 0 '
        self.hmc.sshcnx.run_command(m_cmd)
        self.log.debug('Going to sleep for %s s' % self.sleep_time)
        time.sleep(self.sleep_time)

        # Check at HMC
        m_msg = 'Moving %d megabytes of memory from %s to %s.' % \
                (quantity, linux_machine_1.partition, linux_machine_2.partition)
        if not self.log.check_log(m_msg, 
                                  (int(self.get_mem_option(linux_machine_1, 
                                                           'curr_mem')) == \
                                   curr_mem_before_1 - quantity) and \
                                   (int(self.get_mem_option(linux_machine_2, 
                                                            'curr_mem')) == \
                                   curr_mem_before_2 + quantity), False):
            e_msg = 'Error happened when moving memory from %s to %s' % \
                    (linux_machine_1.partition, linux_machine_2.partition)
            self.log.error(e_msg)
            raise TestException(e_msg)

        # Check at Linux partition (using /proc/meminfo)
        curr_mem_proc_after_1 = self.__check_memory_proc(linux_machine_1)
        curr_mem_proc_after_2 = self.__check_memory_proc(linux_machine_2)
        c_msg_1 = 'Checking if /proc/meminfo shows removed memory on %s.' % \
                  linux_machine_1.partition
        self.log.check_log(c_msg_1, ((curr_mem_proc_after_1 - \
                                      curr_mem_proc_before_1)/1024 == quantity))

        c_msg_2 = 'Checking if /proc/meminfo shows removed memory on %s.' % \
                  linux_machine_2.partition
        self.log.check_log(c_msg_2, ((curr_mem_proc_before_2 - \
                                      curr_mem_proc_after_2)/1024 == quantity))


if __name__ == "__main__":
    MEMORY = Memory()
    MEMORY.run_test()
