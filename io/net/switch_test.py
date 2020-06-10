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

import time
import paramiko
import netifaces
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
        interfaces = netifaces.interfaces()
        interface = self.params.get("interface")
        if interface not in interfaces:
            self.cancel("%s interface is not available" % interface)
        self.iface = interface
        self.ipaddr = self.params.get("host_ip", default="")
        self.netmask = self.params.get("netmask", default="")
        local = LocalHost()
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
        self.switch_login(self.switch_name, self.userid, self.password)

    def switch_login(self, ip, username, password):
        '''
        Login method for remote fc switch
        '''
        self.tnc = paramiko.SSHClient()
        self.tnc.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.tnc.connect(ip, username=username, password=password,
                         look_for_keys=False, allow_agent=False)
        self.log.info("SSH connection established to " + ip)
        self.remote_conn = self.tnc.invoke_shell()
        self.log.info("Interactive SSH session established")
        assert self.remote_conn
        self.remote_conn.send("iscli" + '\n')

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

    def test(self):
        '''
        switch port enable and disable test
        '''
        self.log.info("Enabling the privilege mode")
        self.run_switch_command("enable")
        self.log.info("Entering configuration mode")
        self.run_switch_command("conf t")
        cmd = "interface port %s" % self.port_id
        self.run_switch_command(cmd)
        self.run_switch_command("shutdown")
        time.sleep(5)
        if self.networkinterface.ping_check(self.peer, count=5) is None:
            self.fail("pinging after disable port")
        self.run_switch_command("no shutdown")
        time.sleep(5)
        if self.networkinterface.ping_check(self.peer, count=5) is not None:
            self.fail("ping test failed")
        self.run_switch_command("end")

    def tearDown(self):
        '''
        unset ip address
        '''
        self.networkinterface.remove_ipaddr(self.ipaddr, self.netmask)
        self.networkinterface.restore_from_backup()
