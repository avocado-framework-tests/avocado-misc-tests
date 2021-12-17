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
Test to verify CPU units DLPAR. Operations tested:
 * Add
 * Move
 * Remove

This test assumes that we have 2 power LPARS properly configured to start.
"""
import time
from dlpar_api.api import TestCase, TestException


__all__ = ['CpuUnit']

class CpuUnit(TestCase):
    """DLPAR CPU Units test case.

    The test procedure:
    1 - Get how much cpu units to test;
    2 - Check and set the test environment for both linux partitions;
    3 - Test (see run_test())

    Everything is fine if we don't have troubles with the HMC and with both 
    linux partitions.
    """

    def __prep_shr_cfg(self, linux_machine):
        """
         Activate shared partition with the user defined min/desired/max

         Check:
          1 - Shutdown the partition (shared);
          2 - Define dedicated partition with min, desired, max from config
        """
        u_cmd = 'chsyscfg -r prof -m %s -p %s -i \
                "lpar_name=%s,name=default_profile,proc_mode=shared, \
                min_proc_units=%s,desired_proc_units=%s,max_proc_units=%s, \
                min_procs=%s,desired_procs=%s,max_procs=%s,sharing_mode=%s" --force' % \
                (linux_machine.machine,linux_machine.partition, \
                linux_machine.name,self.min_proc_units,self.desired_proc_units, \
                self.max_proc_units,self.min_procs,self.desired_procs, \
                self.max_procs, self.sharing_mode)
        self.log.info('DEBUG: Shared lpar setup %s' % u_cmd)
        self.hmc.sshcnx.run_command(u_cmd, False)

        d_cmd = 'chsysstate -m %s -o shutdown -r lpar -n %s --immed' % \
                (linux_machine.machine,linux_machine.name)
        self.log.info('DEBUG: Shared lpar setup %s' % d_cmd)
        self.hmc.sshcnx.run_command(d_cmd, False)
        time.sleep(20)

        a_cmd = 'chsysstate -m %s -r lpar -o on -n %s -f default_profile \
                --force' % (linux_machine.machine,linux_machine.name)
        self.log.info('DEBUG: Shared lpar setup %s' % a_cmd)
        self.hmc.sshcnx.run_command(a_cmd, False)
        time.sleep(120)


    def __init__(self, log = 'cpu_unit.log'):
        """Initialize the test case."""
        TestCase.__init__(self, log, "CPU Unit")
        self.get_connections()
        
        # Get test configuration
        self.quant_to_test = float(self.config.get('cpu_unit',
                                                   'quantity_to_test'))
        self.sleep_time = int(self.config.get('cpu_unit', 'sleep_time'))
        self.iterations = int(self.config.get('cpu_unit', 'iterations'))

        self.min_procs = int(self.config.get('cpu_unit',
                                              'min_procs'))
        self.desired_procs = int(self.config.get('cpu_unit',
                                              'desired_procs'))
        self.max_procs = int(self.config.get('cpu_unit',
                                              'max_procs'))
        self.min_proc_units = int(self.config.get('cpu_unit',
                                              'min_proc_units'))
        self.desired_proc_units = int(self.config.get('cpu_unit',
                                              'desired_proc_units'))
        self.max_proc_units = int(self.config.get('cpu_unit',
                                              'max_proc_units'))
        self.sharing_mode = self.config.get('cpu_unit',
                                            'sharing_mode')
        self.log.check_log('Getting Test configuration.',
                           self.quant_to_test != None)
        self.log.debug("Testing with %s CPU Units." % self.quant_to_test)

        # shutdown the paritition, update profile with min,desired,max, activate
        self.__prep_shr_cfg(self.linux_1)
        self.__prep_shr_cfg(self.linux_2)

        self.get_connections()

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
        self.log.info("Checking partition '%s' configuration." % \
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

        ## Check if the system support the virtual cpu inits to add
        c_msg = "Checking if the machine %s supports adding %s cpu units." % \
                (linux_machine.machine, self.quant_to_test)
        c_condition = self.quant_to_test <= (curr_max_proc_units - \
                                             curr_min_proc_units)
        self.log.check_log(c_msg, c_condition)

        ## This is the minimal virtual proc units to have
        ideal_procs = int(curr_min_proc_units + self.quant_to_test)
        if (((curr_min_proc_units + self.quant_to_test) % 1) != 0.0):
            ideal_procs += + 1

        ## This is the ideal proc units to have
        # XXX: We need to improve this, because we need to check the min
        # XXX: virtual cpu, the max virtual cpu and etc
        ideal_proc_units = float(ideal_procs)/10
        if ideal_proc_units < curr_min_proc_units:
            ideal_proc_units = curr_min_proc_units

        ## Check if the system support the needed virtual cpu quantity to have
        c_msg = "Checking if %s profile supports %d virtual cpu units." % \
                (linux_machine.machine, ideal_procs)
        self.log.check_log(c_msg, ideal_procs <= curr_max_procs)

        self.log.debug('Setting the curr_procs at partition %s to %d' % \
                       (linux_machine.partition, ideal_procs))
        self.log.debug('Setting the curr_proc_units at partition %s to %f' % \
                       (linux_machine.partition, ideal_proc_units))

        ## Add and Remove all needed virtual cpus and proc units
        self.set_virtual_proc_and_proc_units(linux_machine, ideal_procs,
                                             ideal_proc_units, self.sleep_time)

        i_msg = 'Configuration settings for partition %s correct.' % \
                linux_machine.partition
        self.log.info(i_msg)


    def run_test(self):
        """Run the test.

        1 - Add X proc units to first partition;
        2 - Move X proc units from the first partition to the second one;
        3 - Remove X proc units from the second partitions;
        4 - Add X proc units to the second partition;
        5 - Move X proc units from the second partition to the first one;
        6 - Remove X proc units from the first partition;
        """
        self.log.info("Initiating the test.")
        for iteration in range(1, self.iterations + 1):
            self.log.info("Running iteration %d" % iteration)
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
        a_cmd = 'chhwres -m ' + linux_machine.machine + \
                ' -r proc -o a --procunits ' + str(quantity) + \
                ' -p "' + linux_machine.partition + '"'
        self.hmc.sshcnx.run_command(a_cmd)
        self.log.debug('Sleeping for %s seconds before proceeding' %
                       self.sleep_time)
        time.sleep(self.sleep_time)

        a_msg = 'Adding %s proc units to partition %s.' % \
                (quantity, linux_machine.partition)
        a_condition = (self.get_cpu_option(linux_machine, 
                                           'curr_proc_units') == \
                       str(curr_proc_units_before + quantity))
        # Check at HMC
        if not self.log.check_log(a_msg, a_condition, False):
            e_msg = 'Error adding %s proc units to partition %s.' % \
                    (quantity, linux_machine.partition)
            self.log.error(e_msg)
            raise TestException(e_msg)


    def __move_cpu_units(self, linux_machine_1, linux_machine_2, quantity):
        """
        Move 'quantity' proc units from linux_machine_1 to linux_machine_2.
        """
        # Get all values from both machines before moving
        curr_proc_units_before_1 = float(self.get_cpu_option(linux_machine_1,
                                                             'curr_proc_units'))
        curr_proc_units_before_2 = float(self.get_cpu_option(linux_machine_2,
                                                             'curr_proc_units'))

        # Move the proc units
        m_cmd = 'chhwres -m ' + linux_machine_1.machine + \
                ' -r proc -o m --procunits ' + str(quantity) + \
                ' -p "' + linux_machine_1.partition + '"' + \
                ' -t "' + linux_machine_2.partition + '"'

        self.hmc.sshcnx.run_command(m_cmd)
        self.log.debug('Sleeping for %s seconds before proceeding' %
                       self.sleep_time)
        time.sleep(self.sleep_time)

        # Check at HMC
        m_msg = 'Moving %s proc units from %s to %s.' % \
                (quantity, linux_machine_1.partition, linux_machine_2.partition)
        m_condition = ((self.get_cpu_option(linux_machine_1,
                                            'curr_proc_units')) == \
                       str(curr_proc_units_before_1 - quantity)) and \
                       ((self.get_cpu_option(linux_machine_2,
                                             'curr_proc_units')) == \
                       str(curr_proc_units_before_2 + quantity))

        if not self.log.check_log(m_msg, m_condition, False):
            e_msg = 'Moving %s proc units from %s to %s.' % \
                    (quantity, linux_machine_1.partition,
                     linux_machine_2.partition)
            self.log.error(e_msg)
            raise TestException(e_msg)


    def __remove_cpu_units(self, linux_machine, quantity):
        """Remove 'quantity' proc units from linux_machine."""
        # Get all values before removing
        curr_proc_units_before = float(self.get_cpu_option(linux_machine,
                                                           'curr_proc_units'))

        # Remove the cpus
        r_cmd = 'chhwres -m ' + linux_machine.machine + \
                ' -r proc -o r --procunits ' + str(quantity) + \
                ' -p "' + linux_machine.partition + '"'
        self.hmc.sshcnx.run_command(r_cmd)
        self.log.debug('Sleeping for %s seconds before proceeding' %
                       self.sleep_time)
        time.sleep(self.sleep_time)
        # Check at HMC
        r_msg = 'Removing %s proc units from partition %s.' % \
                (quantity, linux_machine.partition)
        r_condition = self.get_cpu_option(linux_machine, 'curr_proc_units') == \
                      str(curr_proc_units_before - quantity)

        if not self.log.check_log(r_msg, r_condition, False):
            e_msg = 'Error removing %s proc units from partition %s.' % \
                    (quantity, linux_machine.partition)
            self.log.error(e_msg)
            raise TestException(e_msg)


if __name__ == "__main__":
    CPU_UNIT = CpuUnit()
    CPU_UNIT.run_test()
