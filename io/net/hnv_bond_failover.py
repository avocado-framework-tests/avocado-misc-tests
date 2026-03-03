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
# Copyright: 2026 IBM
# Author: Vaishnavi Bhat <vaishnavi@linux.vnet.ibm.com>

"""
HNV Bond Failover Test
Tests HNV (Hybrid Network Virtualization) bond failover functionality
by bringing down slave interfaces and verifying connectivity is maintained.
"""

import os
import time
from avocado import Test
from avocado.utils import process
from avocado.utils import wait


class HNVBondFailoverTest(Test):
    """
    Test HNV bond failover by disabling slave interfaces one at a time
    and verifying that connectivity is maintained through the bond.

    :avocado: tags=net,bond,hnv,failover
    """

    def setUp(self):
        """
        Set up test parameters and verify bond configuration
        """
        self.interface = self.params.get("interface", default=None)
        self.host_ip = self.params.get("host_ip", default=None)
        self.peer_ip = self.params.get("peer_ip", default=None)

        if not self.interface:
            self.cancel("Bond interface not specified in YAML configuration")
        if not self.host_ip:
            self.cancel("Host IP address not specified in YAML configuration")
        if not self.peer_ip:
            self.cancel("Peer IP address not specified in YAML configuration")

        # Verify bond exists
        if not os.path.exists("/sys/class/net/%s" % self.interface):
            self.cancel("Bond interface %s does not exist" % self.interface)

        # Verify it's a bond interface
        bond_path = "/sys/class/net/%s/bonding" % self.interface
        if not os.path.exists(bond_path):
            self.cancel("Interface %s is not a bond interface" %
                        self.interface)

        # Get bond slaves
        self.slaves = self._get_bond_slaves()
        if not self.slaves:
            self.cancel("No slave interfaces found for bond %s" %
                        self.interface)

        if len(self.slaves) < 2:
            self.cancel("Bond %s has only %d slave(s), need at least 2 "
                        "for failover test" %
                        (self.interface, len(self.slaves)))

        self.log.info("Bond %s has %d slaves: %s" %
                      (self.interface, len(self.slaves),
                       ', '.join(self.slaves)))

        # Get initial active slave
        self.initial_active_slave = self._get_active_slave()
        if not self.initial_active_slave:
            self.cancel("No active slave found for bond %s" % self.interface)

        self.log.info("Initial active slave: %s" % self.initial_active_slave)

        # Store initial slave states
        self.initial_slave_states = {}
        for slave in self.slaves:
            self.initial_slave_states[slave] = self._get_interface_state(slave)
            self.log.info("Initial state of %s: %s" %
                          (slave, self.initial_slave_states[slave]))

        # Verify initial connectivity
        if not self._ping_test(self.peer_ip):
            self.cancel("Initial connectivity test failed - cannot ping %s" %
                        self.peer_ip)

        self.log.info("Initial connectivity test passed")

    def _get_bond_slaves(self):
        """
        Get list of slave interfaces for the bond
        """
        slaves_file = "/sys/class/net/%s/bonding/slaves" % self.interface
        try:
            with open(slaves_file, 'r') as f:
                slaves_str = f.read().strip()
                if slaves_str:
                    return slaves_str.split()
        except IOError as e:
            self.log.error("Error reading bond slaves: %s" % str(e))
        return []

    def _get_active_slave(self):
        """
        Get the current active slave interface
        """
        active_slave_file = ("/sys/class/net/%s/bonding/active_slave" %
                             self.interface)
        try:
            if os.path.exists(active_slave_file):
                with open(active_slave_file, 'r') as f:
                    active_slave = f.read().strip()
                    return active_slave if active_slave else None
        except IOError as e:
            self.log.error("Error reading active slave: %s" % str(e))
        return None

    def _get_interface_state(self, interface):
        """
        Get the operational state of an interface
        """
        state_file = "/sys/class/net/%s/operstate" % interface
        try:
            with open(state_file, 'r') as f:
                return f.read().strip()
        except IOError as e:
            self.log.error("Error reading interface state: %s" % str(e))
            return "unknown"

    def _set_interface_down(self, interface):
        """
        Bring an interface down
        """
        cmd = "ip link set %s down" % interface
        result = process.run(cmd, shell=True, ignore_status=True)
        if result.exit_status != 0:
            self.log.error("Failed to bring down interface %s: %s" %
                           (interface, result.stderr.decode()))
            return False
        self.log.info("Successfully brought down interface %s" % interface)
        return True

    def _set_interface_up(self, interface):
        """
        Bring an interface up
        """
        cmd = "ip link set %s up" % interface
        result = process.run(cmd, shell=True, ignore_status=True)
        if result.exit_status != 0:
            self.log.error("Failed to bring up interface %s: %s" %
                           (interface, result.stderr.decode()))
            return False
        self.log.info("Successfully brought up interface %s" % interface)
        return True

    def _ping_test(self, target_ip, count=5, timeout=10):
        """
        Test connectivity by pinging target IP through the bond interface
        Uses -I option to ensure traffic goes through the bond interface
        """
        cmd = ("ping -I %s -c %d -W %d %s" %
               (self.interface, count, timeout, target_ip))
        result = process.run(cmd, shell=True, ignore_status=True)

        if result.exit_status == 0:
            self.log.info("Ping test to %s via %s successful" %
                          (target_ip, self.interface))
            return True
        else:
            self.fail("Ping test to %s via %s failed" %
                      (target_ip, self.interface))
            return False

    def _wait_for_failover(self, old_active_slave, timeout=30):
        """
        Wait for bond to failover to a different slave
        """
        self.log.info("Waiting for failover from %s..." % old_active_slave)

        def check_failover():
            new_active = self._get_active_slave()
            if new_active and new_active != old_active_slave:
                self.log.info("Failover detected: new active slave is %s" %
                              new_active)
                return True
            return False

        try:
            wait.wait_for(check_failover, timeout=timeout, step=1)
            return True
        except Exception as e:
            self.log.error("Failover did not occur within %d seconds: %s" %
                           (timeout, str(e)))
            return False

    def test_bond_config_validation(self):
        """
        Verify that the HNV bond is configured properly with
        primary_reselect=always and has an active slave
        """
        # Check primary_reselect setting
        primary_reselect_file = (
            "/sys/class/net/%s/bonding/primary_reselect" % self.interface)
        try:
            if os.path.exists(primary_reselect_file):
                with open(primary_reselect_file, 'r') as f:
                    primary_reselect = f.read().strip()
                    self.log.info("Bond %s primary_reselect: %s" %
                                  (self.interface, primary_reselect))

                    # Check if primary_reselect is set to 'always'
                    # The value might be in format "always 0" or just "always"
                    if not primary_reselect.startswith("always"):
                        self.fail(
                            "Bond %s primary_reselect is not set to "
                            "'always', current value: %s" %
                            (self.interface, primary_reselect))
                    else:
                        self.log.info(
                            "Bond %s has primary_reselect=always "
                            "configured" % self.interface)
            else:
                self.fail("primary_reselect file not found for bond %s" %
                          self.interface)
        except IOError as e:
            self.error("Error reading primary_reselect: %s" % str(e))

        # Verify active slave is configured
        active_slave = self._get_active_slave()
        if not active_slave:
            self.fail("Bond %s does not have an active slave" % self.interface)

        if active_slave not in self.slaves:
            self.fail("Active slave %s is not in the list of bond slaves: "
                      "%s" % (active_slave, ', '.join(self.slaves)))

        self.log.info("Bond %s has active slave: %s" %
                      (self.interface, active_slave))

    def test_failover_slave1_down(self):
        """
        Test failover by bringing down the first slave interface
        """
        slave1 = self.slaves[0]
        self.log.info("Testing failover by bringing down slave: %s" % slave1)

        # Get current active slave
        current_active = self._get_active_slave()
        self.log.info("Current active slave before test: %s" % current_active)

        # Bring down slave1
        if not self._set_interface_down(slave1):
            self.fail("Failed to bring down slave interface %s" % slave1)

        # Wait a bit for the bond to detect the failure
        time.sleep(5)

        # If slave1 was the active slave, wait for failover
        if current_active == slave1:
            if not self._wait_for_failover(slave1):
                self.fail(
                    "Bond did not failover after bringing down active "
                    "slave %s" % slave1)

        # Verify connectivity is maintained
        if not self._ping_test(self.peer_ip):
            self.fail("Connectivity lost after bringing down slave %s" %
                      slave1)

        self.log.info("Failover test with slave1 down: PASSED")

        # Bring slave1 back up for next test
        if not self._set_interface_up(slave1):
            self.error("Failed to bring slave %s back up" % slave1)
        time.sleep(5)

    def test_failover_slave2_down(self):
        """
        Test failover by bringing down the second slave interface
        """
        if len(self.slaves) < 2:
            self.cancel("Not enough slaves for this test")

        slave2 = self.slaves[1]
        self.log.info("Testing failover by bringing down slave: %s" % slave2)

        # Get current active slave
        current_active = self._get_active_slave()
        self.log.info("Current active slave before test: %s" % current_active)

        # Bring down slave2
        if not self._set_interface_down(slave2):
            self.fail("Failed to bring down slave interface %s" % slave2)

        # Wait a bit for the bond to detect the failure
        time.sleep(5)

        # If slave2 was the active slave, wait for failover
        if current_active == slave2:
            if not self._wait_for_failover(slave2):
                self.fail(
                    "Bond did not failover after bringing down active "
                    "slave %s" % slave2)

        # Verify connectivity is maintained
        if not self._ping_test(self.peer_ip):
            self.fail("Connectivity lost after bringing down slave %s" %
                      slave2)

        self.log.info("Failover test with slave2 down: PASSED")

        # Bring slave2 back up
        if not self._set_interface_up(slave2):
            self.error("Failed to bring slave %s back up" % slave2)
        time.sleep(5)

    def tearDown(self):
        """
        Restore all slave interfaces to their original state
        """
        self.log.info("Restoring slave interfaces to original state")

        for slave in self.slaves:
            current_state = self._get_interface_state(slave)
            original_state = self.initial_slave_states.get(slave, "up")

            if current_state != original_state:
                self.log.info("Restoring %s from %s to %s" %
                              (slave, current_state, original_state))

                if original_state == "up" or "unknown":
                    self._set_interface_up(slave)
                elif original_state == "down":
                    self._set_interface_down(slave)

                time.sleep(2)

        # Verify final connectivity
        time.sleep(5)
        if self._ping_test(self.peer_ip):
            self.log.info("Final connectivity test: PASSED")
        else:
            self.log.warn("Final connectivity test: FAILED")

        # Verify slaves are intact
        final_slaves = self._get_bond_slaves()
        if set(final_slaves) != set(self.slaves):
            self.log.warn("Bond slave configuration changed! Initial: %s, "
                          "Final: %s" %
                          (', '.join(self.slaves), ', '.join(final_slaves)))
        else:
            self.log.info("Bond slave configuration intact: %s" %
                          ', '.join(final_slaves))
# Assisted by AI tool
