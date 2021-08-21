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
# Copyright: 2017 IBM
# Author: Pridhiviraj Paidipeddi <ppaidipe@linux.vnet.ibm.com>
# VLAN Testcase

import time

from avocado import Test
from avocado.utils import process
from avocado.utils.network.hosts import LocalHost, RemoteHost
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.process import CmdError

import paramiko


class VlanTest(Test):

    """
    :param switch_name: Switch name or IP
    :param userid: userid of the switch to login into
    :param password: password of the switch for user userid
    :param vlan_num: vlan number where the port port_id will be added
    :param host_port: host port id where the VLAN test will run
    :param peer_port: peer port id where the VLAN test will run
    :param interface: Host test N/W Interface
    :param peer_interface: Peer test N/W Interface
    :param peer_ip: IP address of peer
    :param peer_user: Userid of the peer
    :param peer_password: Password of the peer to ssh into
    :param netmask: netmask of the test N/W Interfaces
    """

    def setUp(self):
        """
        test parameters
        """
        self.switch_name = self.params.get("switch_name", '*', default=None)
        self.userid = self.params.get("userid", '*', default=None)
        self.password = self.params.get("password", '*', default=None)
        self.vlan_num = self.params.get("vlan_num", '*', default=None)
        self.host_port = self.params.get("host_port", '*', default=None)
        self.peer_port = self.params.get("peer_port", '*', default=None)
        self.host_ip = self.params.get("host_ip", '*', default=None)
        self.peer_ip = self.params.get("peer_ip", '*', default=None)
        self.netmask = self.params.get("netmask", '*', default=None)
        self.peer_public_ip = self.params.get("peer_public_ip", '*', default=None)
        self.peer_user = self.params.get("peer_user", '*', default=None)
        self.peer_password = self.params.get("peer_password", '*', default=None)
        self.cidr_value = self.params.get("cidr_value", '*', default=None)
        self.local_host = LocalHost()
        self.remote_host = RemoteHost(host=self.peer_ip, user=self.peer_user,
                                      password=self.peer_password)
        self.host_interface = NetworkInterface(self.params.get("interface", default=None),
                                               self.local_host)
        if 'ib' in self.host_interface.name:
            self.cancel("vlan is not supported for IB")
        self.peer_interface = NetworkInterface(self.params.get("peer_interface", default=None),
                                               self.remote_host)
        self.prompt = ">"
        self.test_type = None
        self.host_vlan_interface = None
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

    def test_default_vlan1(self):
        """
        Scenario 1:  keep both host & peer in default VLAN id, VLAN 1.
                     Now ping each other. it should PASS
        """
        # PVID tagging should be disabled for this test
        self.vlan_port_conf("1", "1")

        self.host_interface.ping_check(peer_ip=self.peer_ip, count=5)
        self.peer_interface.ping_check(peer_ip=self.host_interface.get_ipaddrs()[0], count=5)

    def test_vlan_1_2230(self):
        """
        Scenario 2: Keep host in vlan 1 and Peer in vlan 2230.
                    Now ping. it should FAIL
        """
        self.vlan_port_conf("1", "2230")
        # before ping need few sec for interface to set vlan
        time.sleep(5)

        self.host_interface.ping_check(peer_ip=self.peer_ip, count=5)
        self.peer_interface.ping_check(peer_ip=self.peer_ip, count=5)

    def test_vlan_id(self):
        """
        Scenario 3: Keep both in the vlan id (taken from yaml file), and
                    create vlan interfaces and then ping. It should PASS.
        """
        # PVID tagging should be enabled for this test
        self.vlan_port_conf(self.vlan_num, self.vlan_num)

        host_vlan_intf = self.conf_vlan_intf(self.host_interface, self.vlan_num)
        peer_vlan_intf = self.conf_vlan_intf(self.peer_interface, self.vlan_num)

        time.sleep(5)
        host_vlan_intf.ping_check(peer_ip=peer_vlan_intf.get_ipaddrs(), count=5)
        peer_vlan_intf.ping_check(peer_ip=host_vlan_intf.get_ipaddrs(), count=5)

        # Disable PVID tagging as other tests need it to be in disabled.
        self.run_switch_command("no vlan dot1q tag native")
        self.restore_intf(self.host_interface)
        self.restore_intf(self.peer_interface)

    def vlan_port_conf(self, host_vlan, peer_vlan):
        """
        Set both host & peer interface ports with corresponding
        vlan's (host_vlan, peer_vlan)
        """
        self.log.info("Enabling the privilege mode")
        self.run_switch_command("enable")
        self.log.info("Entering configuration mode")
        self.run_switch_command("conf t")
        self.set_vlan_port(host_vlan, self.host_port)
        self.set_vlan_port(peer_vlan, self.peer_port)

    def set_vlan_port(self, vlan_num, port_id):
        """
        Sets the interface port to a vlan num
        """
        cmd = "show mac-address-table interface port %s" % port_id
        self.run_switch_command(cmd)
        self.log.info("Going to port %s", port_id)
        self.run_switch_command("interface port %s" % port_id)
        self.log.info("Changing the VLAN to %s of port %s", vlan_num,
                      port_id)
        self.run_switch_command("switchport mode trunk")
        self.run_switch_command("switchport trunk native vlan %s" % vlan_num)
        # Enable PVID tagging only for test test_vlan_id
        if hasattr(self, 'test_type') and self.test_type == "full":
            self.run_switch_command("vlan dot1q tag native")
            # Disable PVID tagging for other tests
        else:
            self.run_switch_command("no vlan dot1q tag native")
        self.log.info("Saving the configuration")
        self.run_switch_command("write memory")
        self.run_switch_command("exit")
        self.run_switch_command(cmd)


    def conf_vlan_intf(self, interface, vlan_num):
        """
        Vlan configuration of an interface
        """
        ip = interface.get_ipaddrs()
        vlan_interface_name = interface.name + '.' + vlan_num
        interface.remove_ipaddr(ip, self.cidr_value)
        interface.add_vlan_tag(vlan_num, vlan_interface_name)
        vlan_interface = NetworkInterface(vlan_interface_name, interface.host)
        vlan_interface.add_ipaddr(ip, self.cidr_value)
        vlan_interface.bring_up()
        return vlan_interface

    def restore_intf(self, interface):
        """
        Restore host interfaces
        """
        ip = ""
        for v in interface.vlans.values():
            vlan_interface = NetworkInterface(v, interface.host)
            ip = vlan_interface.get_ipaddrs()
        interface.remove_all_vlans()
        interface.bring_down()
        interface.add_ipaddr(ip)
        interface.bring_up()

    def tearDown(self):
        """
        Restore back the default VLAN ID 1
        and also restore interfaces back when full test is run
        """
        self.vlan_port_conf("1", "1")
        self.remote_host.remote_session.quit()
