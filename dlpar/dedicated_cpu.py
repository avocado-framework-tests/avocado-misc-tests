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
# Author(Original): Ricardo Salveti <rsalveti@linux.vnet.ibm.com>
# Author(Modified): Kalpana Shetty <kalshett@in.ibm.com>

"""
Test to verify dedicated CPU DLPAR. Operations tested:
 * Add
 * Move
 * Remove

This test assumes that we have 2 power LPARS properly configured to start.
"""
import time
from dlpar_api.api import TestCase, TestException


__all__ = ['DedicatedCpu']


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

    def __prep_ded_cfg(self, linux_machine):
        """
         Activate dedicated partition with the user defined min/desired/max

         Check:
          1 - Shutdown the partition (dedicated);
          2 - Define dedicated partition with min, desired, max from config
        """
        u_cmd = 'chsyscfg -r prof -m %s -i \
                "lpar_name=%s,name=default_profile,proc_mode=ded, \
                min_procs=%s,desired_procs=%s,max_procs=%s,sharing_mode=keep_idle_procs" \
                --force' % (linux_machine.machine,
                            linux_machine.name, self.min_procs, self.desired_procs, self.max_procs)
        self.log.info('DEBUG: Dedicated lpar setup %s' % u_cmd)
        self.hmc.sshcnx.run_command(u_cmd, False)

        d_cmd = 'chsysstate -m %s -o shutdown -r lpar -n %s --immed' % \
                (linux_machine.machine, linux_machine.name)
        self.log.info('DEBUG: Dedicated lpar setup %s' % d_cmd)
        self.hmc.sshcnx.run_command(d_cmd, False)
        time.sleep(20)

        a_cmd = 'chsysstate -m %s -r lpar -o on -n %s -f default_profile \
                --force' % (linux_machine.machine, linux_machine.name)
        self.log.info('DEBUG: Dedicated lpar setup %s' % a_cmd)
        self.hmc.sshcnx.run_command(a_cmd, False)
        time.sleep(120)

    def __init__(self, log='dedicated_cpu.log'):

        TestCase.__init__(self, log, 'Dedicated CPU')

        self.get_connections()

        # Get test configuration
        self.quant_to_test = int(self.config.get('dedicated_cpu',
                                                 'quantity_to_test'))
        self.sleep_time = int(self.config.get('dedicated_cpu',
                                              'sleep_time'))
        self.iterations = int(self.config.get('dedicated_cpu',
                                              'iterations'))
        self.min_procs = int(self.config.get('dedicated_cpu',
                                             'min_procs'))
        self.desired_procs = int(self.config.get('dedicated_cpu',
                                                 'desired_procs'))
        self.max_procs = int(self.config.get('dedicated_cpu',
                                             'max_procs'))
        self.log.check_log('Getting Test configuration.',
                           (self.quant_to_test != None))
        self.log.debug("Testing with %s Dedicated CPU units." %
                       self.quant_to_test)

        # shutdown the paritition, update profile with min,desired,max, activate
        self.__prep_ded_cfg(self.linux_1)
        self.__prep_ded_cfg(self.linux_2)

        self.get_connections()

        # Check linux partitions configuration
        self.__check_set_cfg(self.linux_1)
        self.__check_set_cfg(self.linux_2)

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
            self.hmc.sshcnx.run_command(m_cmd, False)

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

    def run_test(self):
        """Run the test.

        1 - Add X dedicated cpus to first partition;
        2 - Move X dedicated cpus from the first partition to the second one;
        3 - Remove X dedicated cpus from the second partitions;
        4 - Add X dedicated cpus to the second partition;
        5 - Move X dedicated cpus from the second partition to the first one;
        6 - Remove X dedicated cpus from the first partition;
        """
        self.log.info("Initiating the test.")
        for iteration in range(1, self.iterations + 1):
            self.log.info("Running iteration %d" % iteration)
            self.__add_dedicated_cpu(self.linux_1, self.quant_to_test)
            self.__move_dedicated_cpu(self.linux_1, self.linux_2,
                                      self.quant_to_test)
            self.__remove_dedicated_cpu(self.linux_2, self.quant_to_test)
            self.__add_dedicated_cpu(self.linux_2, self.quant_to_test)
            self.__move_dedicated_cpu(self.linux_2, self.linux_1,
                                      self.quant_to_test)
            self.__remove_dedicated_cpu(self.linux_1, self.quant_to_test)
        self.log.info("Test finished successfully :)")

    def __add_dedicated_cpu(self, linux_machine, quantity):
        """Add 'quantity' dedicated cpus at the a linux partition."""
        # Get all values before adding
        curr_procs_before = int(self.get_cpu_option(linux_machine,
                                                    'curr_procs'))
        time.sleep(self.sleep_time)

        # Add the cpus
        a_cmd = 'chhwres -m ' + linux_machine.machine + \
                ' -r proc -o a --procs ' + str(quantity) + \
                ' -p "' + linux_machine.partition + '"' + ' -w 0 '
        cmd_result = self.hmc.sshcnx.run_command(a_cmd)
        self.log.debug('Sleeping for %s seconds before proceeding' %
                       self.sleep_time)
        time.sleep(self.sleep_time)

        # Check at HMC
        a_msg = 'Adding %d dedicated cpus to partition %s.' % \
                (quantity, linux_machine.partition)
        a_condition = int(self.get_cpu_option(linux_machine, 'curr_procs')) == \
            curr_procs_before + quantity
        if not self.log.check_log(a_msg, a_condition, False):
            e_msg = 'Error adding %d dedicated cpus to partition %s.' % \
                    (quantity, linux_machine.partition)

            self.log.error(e_msg)
            raise TestException(cmd_result)

        # Check at Linux Partition
        self.linux_check_add_cpu(linux_machine, quantity)

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
        m_cmd = 'chhwres -m ' + linux_machine_1.machine + \
                ' -r proc -o m --procs ' + str(quantity) + \
                ' -p "' + linux_machine_1.partition + '"' + \
                ' -t "' + linux_machine_2.partition + '"' + ' -w 0 '
        cmd_result = self.hmc.sshcnx.run_command(m_cmd)
        self.log.debug('Sleeping for %s seconds before proceeding' %
                       self.sleep_time)
        time.sleep(self.sleep_time)
        # Check at HMC
        m_msg = 'Moving %s dedicated cpus from %s to %s.' % \
                (quantity, linux_machine_1.partition, linux_machine_2.partition)
        m_condition = (int(self.get_cpu_option(linux_machine_1, 'curr_procs'))
                       == curr_procs_before_1 - quantity) \
            and (int(self.get_cpu_option(linux_machine_2,
                                         'curr_procs'))
                 == curr_procs_before_2 + quantity)
        if not self.log.check_log(m_msg, m_condition, False):
            self.log.error(cmd_result)
            raise TestException(cmd_result)

        # Check at both linux partitions
        self.linux_check_rm_cpu(linux_machine_1, curr_procs_before_1, quantity)
        self.linux_check_add_cpu(linux_machine_2, quantity)

    def __remove_dedicated_cpu(self, linux_machine, quantity):
        """Remove 'quantity' dedicated cpus from linux_machine."""
        # Get all values before removing
        curr_procs_before = int(self.get_cpu_option(linux_machine,
                                                    'curr_procs'))
        # Remove the cpus
        r_cmd = 'chhwres -m ' + linux_machine.machine + \
                ' -r proc -o r --procs ' + str(quantity) + \
                ' -p "' + linux_machine.partition + '"' + ' -w 0 '
        self.hmc.sshcnx.run_command(r_cmd)
        self.log.debug('Sleeping for %s seconds before proceeding' %
                       self.sleep_time)
        time.sleep(self.sleep_time)
        # Check at HMC
        r_msg = 'Removing %s dedicated cpus from partition %s.' % \
                (quantity, linux_machine.partition)
        r_condition = int(self.get_cpu_option(linux_machine, 'curr_procs')) == \
            (curr_procs_before - quantity)
        if not self.log.check_log(r_msg, r_condition, False):
            e_msg = 'Error removing %s dedicated cpus from partition %s.' % \
                    (quantity, linux_machine.partition)

            self.log.error(e_msg)
            raise TestException(e_msg)

        # Check at Linux Partition
        self.linux_check_rm_cpu(linux_machine, curr_procs_before, quantity)


if __name__ == "__main__":
    DEDICATED_CPU = DedicatedCpu()
    DEDICATED_CPU.run_test()
