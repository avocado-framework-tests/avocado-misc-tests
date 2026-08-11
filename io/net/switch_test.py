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
# Author: Bismruti Bidhibrata Pattjoshi <bbidhibr@in.ibm.com>
#

"""
check the statistics of interface, test big ping
test lro and gro and interface
"""

import os
import time
import yaml
import paramiko
from avocado import Test
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.network.hosts import LocalHost


class SwitchTest(Test):
    '''
    switch port test
    '''

    def setUp(self):
        '''
        To get all the parameter for the test
        '''
        local = LocalHost()
        self.networkinterface = None
        interfaces = os.listdir('/sys/class/net')
        device = self.params.get("interface", default=None)
        if device in interfaces:
            self.iface = device
        elif (local.validate_mac_addr(device) and
              device in local.get_all_hwaddr()):
            self.iface = local.get_interface_by_hwaddr(device).name
        else:
            self.cancel("%s interface is not available" % device)
        self.ipaddr = self.params.get("host_ip", default="")
        self.netmask = self.params.get("netmask", default="")
        self.networkinterface = NetworkInterface(self.iface, local)
        try:
            self.networkinterface.add_ipaddr(self.ipaddr, self.netmask)
            self.networkinterface.save(self.ipaddr, self.netmask)
        except Exception:
            self.networkinterface.save(self.ipaddr, self.netmask)
        self.networkinterface.bring_up()
        self.peer = self.params.get("peer_ip")
        if not self.peer:
            self.cancel("No peer provided")
        if self.networkinterface.ping_check(self.peer, count=2) is not None:
            self.cancel("No connection to peer")
        self.switch_name = self.params.get("switch_name", '*', default="")
        self.userid = self.params.get("userid", '*', default="")
        self.password = self.params.get("password", '*', default="")
        self.port_id = self.params.get("port_id", default="")
        if not self.port_id:
            self.cancel("user should specify port id")

        # Load switch profile configuration
        profile_name = self.params.get("switch_profile",
                                       default="juniper_switch")
        # Get the data directory for this test
        test_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(test_dir, f"{os.path.basename(__file__)}.data")
        profile_path = os.path.join(data_dir, f"{profile_name}.yaml")
        if not os.path.exists(profile_path):
            self.cancel(f"Switch profile {profile_path} not found")

        with open(profile_path, 'r') as f:
            self.switch_config = yaml.safe_load(f)['switch_profile']

        self.log.info(f"Using switch profile: {self.switch_config['vendor']}")
        self.switch_login(self.switch_name, self.userid, self.password)

    def switch_login(self, ip, username, password):
        '''
        Login method for remote switch
        '''
        self.tnc = paramiko.SSHClient()
        self.tnc.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.tnc.connect(ip, username=username, password=password,
                         look_for_keys=False, allow_agent=False)
        self.log.info("SSH connection established to " + ip)
        self.remote_conn = self.tnc.invoke_shell()
        self.log.info("Interactive SSH session established")
        assert self.remote_conn

        # Send login command if specified in profile
        login_cmd = self.switch_config.get('login_command', '')
        if login_cmd:
            self.log.info(f"Sending login command: {login_cmd}")
            self.remote_conn.send(login_cmd + '\n')
            time.sleep(2)  # Wait for command to execute

    def _send_only_result(self, command, response):
        output = response.decode("utf-8").splitlines()
        if command in output[0]:
            output.pop(0)
        output.pop()
        output = [element.lstrip() + '\n' for element in output]
        response = ''.join(output)
        response = response.strip()
        self.log.info(''.join(response))
        return ''.join(response)

    def run_switch_command(self, command, timeout=300):
        '''
        Run command method for running commands on fc switch
        '''
        self.prompt = "#"
        self.log.info("Running the %s command on fc/nic switch", command)
        if not hasattr(self, 'tnc'):
            self.fail("telnet connection to the fc/nic switch not yet done")
        self.remote_conn.send(command + '\n')
        response = self.remote_conn.recv(1000)
        return self._send_only_result(command, response)

    def _enter_config_mode(self):
        '''
        Enter switch configuration mode
        '''
        cmds = self.switch_config['commands']
        if cmds.get('enter_config'):
            self.log.info("Entering configuration mode")
            self.run_switch_command(cmds['enter_config'])

    def _select_interface(self):
        '''
        Select interface on switch
        '''
        cmds = self.switch_config['commands']
        if cmds.get('select_interface'):
            interface_cmd = cmds['select_interface'].format(
                port_id=self.port_id)
            self.log.info(f"Selecting interface: {interface_cmd}")
            self.run_switch_command(interface_cmd)

    def _exit_config_mode(self):
        '''
        Exit switch configuration mode
        '''
        cmds = self.switch_config['commands']
        if cmds.get('exit_config'):
            self.log.info("Exiting configuration mode")
            self.run_switch_command(cmds['exit_config'])

    def _disable_port(self):
        '''
        Disable switch port
        '''
        cmds = self.switch_config['commands']
        if cmds.get('disable_port'):
            disable_cmd = cmds['disable_port'].format(port_id=self.port_id)
            self.log.info(f"Disabling port: {disable_cmd}")
            self.run_switch_command(disable_cmd)

    def _enable_port(self):
        '''
        Enable switch port
        '''
        cmds = self.switch_config['commands']
        if cmds.get('enable_port'):
            enable_cmd = cmds['enable_port'].format(port_id=self.port_id)
            self.log.info(f"Enabling port: {enable_cmd}")
            self.run_switch_command(enable_cmd)

    def test(self):
        '''
        switch port enable and disable test
        '''
        wait_time = self.switch_config.get('wait_time', 5)

        # Disable port
        self._enter_config_mode()
        self._select_interface()
        self._disable_port()
        self._exit_config_mode()

        # Verify port is disabled (ping should fail)
        time.sleep(wait_time)
        try:
            result = self.networkinterface.ping_check(self.peer, count=5)
            if result is None:
                self.fail("Port not disabled - "
                          "ping succeeded when it should fail")
        except Exception:
            # Expected: ping should fail when port is disabled
            self.log.info("Port disabled successfully - "
                          "ping failed as expected")

        # Enable port
        self._enter_config_mode()
        self._select_interface()
        self._enable_port()
        self._exit_config_mode()

        # Verify port is enabled (ping should succeed)
        time.sleep(wait_time)
        if self.networkinterface.ping_check(self.peer, count=5) is not None:
            self.fail("Port not enabled - ping failed when it should succeed")

    def tearDown(self):
        '''
        Cleanup: unset ip address and ensure switch port is enabled
        '''
        # Ensure switch port is always enabled before cleanup
        try:
            if hasattr(self, 'switch_config') and hasattr(self, 'tnc'):
                self.log.info("Ensuring switch port is enabled in tearDown")
                self._enter_config_mode()
                self._select_interface()
                self._enable_port()
                self._exit_config_mode()
                self.log.info("Switch port enabled successfully in tearDown")
        except Exception as e:
            self.log.warning(f"Failed to enable switch port in tearDown: {e}")

        # Close SSH connection to switch
        try:
            if hasattr(self, 'remote_conn') and self.remote_conn:
                self.remote_conn.close()
                self.log.info("Closed SSH shell connection")
            if hasattr(self, 'tnc') and self.tnc:
                self.tnc.close()
                self.log.info("Closed SSH client connection to switch")
        except Exception as e:
            self.log.warning(
                f"Failed to close SSH connection in tearDown: {e}")

        # Cleanup network interface
        if self.networkinterface:
            self.networkinterface.remove_ipaddr(self.ipaddr, self.netmask)
            try:
                self.networkinterface.restore_from_backup()
            except Exception:
                self.log.info(
                    "backup file not available, could not restore file.")
