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
import telnetlib
try:
    import pxssh
except ImportError:
    from pexpect import pxssh

from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils.process import CmdError


class CommandFailed(Exception):
    def __init__(self, command, output, exitcode):
        self.command = command
        self.output = output
        self.exitcode = exitcode

    def __str__(self):
        return "Command '%s' exited with %d.\nOutput:\n%s" \
               % (self.command, self.exitcode, self.output)


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
        self.parameters()
        self.switch_login(self.switch_name, self.userid, self.password)
        self.peer_login(self.peer_ip, self.peer_user, self.peer_password)
        self.get_ips()

    def parameters(self):
        self.switch_name = self.params.get("switch_name", '*', default=None)
        self.userid = self.params.get("userid", '*', default=None)
        self.password = self.params.get("password", '*', default=None)
        self.vlan_num = self.params.get("vlan_num", '*', default=None)
        self.host_port = self.params.get("host_port", '*', default=None)
        self.peer_port = self.params.get("peer_port", '*', default=None)
        self.host_intf = self.params.get("interface", '*', default=None)
        self.peer_intf = self.params.get("peer_interface", '*', default=None)
        self.peer_ip = self.params.get("peer_ip", '*', default=None)
        self.peer_user = self.params.get("peer_user", '*', default=None)
        self.peer_password = self.params.get("peer_password", '*',
                                             default=None)
        self.cidr_value = self.params.get("cidr_value", '*', default=None)
        self.prompt = ">"

    def switch_login(self, ip, username, password):
        '''
        telnet Login method for remote fc switch
        '''
        self.tnc = telnetlib.Telnet(ip)
        self.tnc.read_until('username:')
        self.tnc.write(username + '\n')
        self.tnc.read_until('password:')
        self.tnc.write(password + '\n')
        ret = self.tnc.read_until(self.prompt)
        assert self.prompt in ret

    def _send_only_result(self, command, response):
        output = response.splitlines()
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
        Telnet Run command method for running commands on fc switch
        '''
        self.prompt = "#"
        self.log.info("Running the %s command on fc/nic switch", command)
        if not hasattr(self, 'tnc'):
            self.fail("telnet connection to the fc/nic switch not yet done")
        self.tnc.write(command + '\n')
        response = self.tnc.read_until(self.prompt)
        return self._send_only_result(command, response)

    def peer_login(self, ip, username, password):
        '''
        SSH Login method for remote peer server
        '''
        pxh = pxssh.pxssh()
        # Work-around for old pxssh not having options= parameter
        pxh.SSH_OPTS = "%s  -o 'StrictHostKeyChecking=no'" % pxh.SSH_OPTS
        pxh.SSH_OPTS = "%s  -o 'UserKnownHostsFile /dev/null' " % pxh.SSH_OPTS
        pxh.force_password = True

        pxh.login(ip, username, password)
        pxh.sendline()
        pxh.prompt(timeout=60)
        pxh.sendline('exec bash --norc --noprofile')
        # Ubuntu likes to be "helpful" and alias grep to
        # include color, which isn't helpful at all. So let's
        # go back to absolutely no messing around with the shell
        pxh.set_unique_prompt()
        self.pxssh = pxh

    def peer_logout(self):
        '''
        SSH Logout method for remote peer server
        '''
        if hasattr(self, 'pxssh'):
            self.pxssh.terminate()
        return

    def run_peer_command(self, command, timeout=300):
        '''
        SSH Run command method for running commands on remote server
        '''
        self.log.info("Running the command on peer lpar %s", command)
        if not hasattr(self, 'pxssh'):
            self.fail("SSH Console setup is not yet done")
        con = self.pxssh
        con.sendline(command)
        con.expect("\n")  # from us
        con.expect(con.PROMPT, timeout=timeout)
        output = con.before.splitlines()
        con.sendline("echo $?")
        con.prompt(timeout)
        exitcode = int(''.join(con.before.splitlines()[1:]))
        if exitcode != 0:
            raise CommandFailed(command, output, exitcode)
        return output

    def run_host_command(self, cmd):
        """
        Run command and fail the test if any command fails
        """
        try:
            process.run(cmd, shell=True, sudo=True)
        except CmdError as details:
            self.fail("Command %s failed %s" % (cmd, details))

    @staticmethod
    def run_cmd_output(cmd):
        """
        Execute the command and return output
        """
        return process.system_output(cmd, ignore_status=True,
                                     shell=True, sudo=True)

    @staticmethod
    def ping_check_host(self, intf, ip):
        '''
        ping check for peer in host
        '''
        cmd = "ping -I %s %s -c 5" % (intf, ip)
        if process.system(cmd, sudo=True, shell=True, ignore_status=True) != 0:
            return False
        return True

    def ping_check_peer(self, intf, ip):
        '''
        ping check for host in peer
        '''
        cmd = "ping -I %s %s -c 5" % (intf, ip)
        try:
            self.run_peer_command(cmd)
            return True
        except CommandFailed:
            return False

    def test_default_vlan1(self):
        """
        Scenario 1:  keep both host & peer in default VLAN id, VLAN 1.
                     Now ping each other. it should PASS
        """
        # PVID tagging should be disabled for this test
        self.vlan_port_conf("1", "1")
        if not self.ping_check_host(self.host_intf,
                                    self.ip_dic[self.peer_intf]):
            self.fail("Ping test failed for default vlan 1 in host")
        self.log.info("Ping test passed for default vlan 1 in host")
        if not self.ping_check_peer(self.peer_intf,
                                    self.ip_dic[self.host_intf]):
            self.fail("Ping test failed for default vlan 1 in peer")
        self.log.info("Ping test passed for default vlan 1 in peer")

    def test_vlan_1_2230(self):
        """
        Scenario 2: Keep host in vlan 1 and Peer in vlan 2230.
                    Now ping. it should FAIL
        """
        self.vlan_port_conf("1", "2230")
        if self.ping_check_host(self.host_intf, self.ip_dic[self.peer_intf]):
            self.fail("Ping test failed for vlan 1 & 2230 in host")
        self.log.info("Ping test passed for vlan 1 % 2230 in host")
        if self.ping_check_host(self.peer_intf, self.ip_dic[self.host_intf]):
            self.fail("Ping test failed for vlan 1 & 2230 in peer")
        self.log.info("Ping test passed for vlan 1 % 2230 in peer")

    def test_vlan_id(self):
        """
        Scenario 3: Keep both in the vlan id (taken from yaml file), and
                    create vlan interfaces and then ping. It should PASS.
        """
        # PVID tagging should be enabled for this test
        self.test_type = "full"
        self.vlan_port_conf(self.vlan_num, self.vlan_num)
        self.conf_host_vlan_intf(self.vlan_num)
        self.conf_peer_vlan_intf(self.vlan_num)
        time.sleep(5)
        if not self.ping_check_host("%s.%s" % (self.host_intf, self.vlan_num),
                                    self.ip_dic[self.peer_intf]):
            self.fail("Ping test failed for vlan %s in host" % self.vlan_num)
        self.log.info("Ping test passed for vlan %s in host" % self.vlan_num)
        if not self.ping_check_peer("%s.%s" % (self.peer_intf, self.vlan_num),
                                    self.ip_dic[self.host_intf]):
            self.fail("Ping test failed for vlan %s in peer" % self.vlan_num)
        self.log.info("Ping test passed for vlan %s in peer" % self.vlan_num)

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

    def get_ips(self):
        """
        save current interface ips before test starts
        """
        self.ip_dic = {}
        cmd = "ip addr list %s |grep 'inet ' |cut -d' ' -f6| \
              cut -d/ -f1" % self.host_intf
        self.ip_dic[self.host_intf] = self.run_cmd_output(cmd)

        cmd = "ip addr list %s |grep 'inet ' |cut -d' ' -f6| \
              cut -d/ -f1" % self.peer_intf
        self.ip_dic[self.peer_intf] = self.run_peer_command(cmd)[0]
        self.log.info("test interface & ips: %s", self.ip_dic)

    def conf_host_vlan_intf(self, vlan_num):
        """
        Vlan configuration on Host
        """
        ip = self.ip_dic[self.host_intf]
        self.run_host_command("ip addr flush dev %s" % self.host_intf)
        cmd = "ip link add link %s name %s.%s type vlan id %s" \
              % (self.host_intf, self.host_intf, vlan_num, vlan_num)
        self.run_host_command(cmd)
        cmd = "ip addr add %s/%s dev %s.%s" \
              % (ip, self.cidr_value, self.host_intf, vlan_num)
        self.run_host_command(cmd)
        self.run_host_command("ip link set %s.%s up" % (self.host_intf,
                                                        vlan_num))
        cmd = "ip addr show %s.%s" % (self.host_intf, vlan_num)
        self.run_host_command(cmd)

    def conf_peer_vlan_intf(self, vlan_num):
        """
        Vlan configuration on Peer
        """
        ip = self.ip_dic[self.peer_intf]
        self.run_peer_command("ip addr flush dev %s" % self.peer_intf)
        cmd = "ip link add link %s name %s.%s type vlan id %s" \
              % (self.peer_intf, self.peer_intf, vlan_num, vlan_num)
        self.run_peer_command(cmd)
        cmd = "ip addr add %s/%s dev %s.%s" \
              % (ip, self.cidr_value, self.peer_intf, vlan_num)
        self.run_peer_command(cmd)
        self.run_peer_command("ip link set %s.%s up" % (self.peer_intf,
                                                        vlan_num))
        cmd = "ip addr show %s.%s" % (self.peer_intf, vlan_num)
        self.run_peer_command(cmd)

    def restore_host_intf(self):
        """
        Restore host interfaces
        """
        cmd = "ip link delete %s.%s" % (self.host_intf, self.vlan_num)
        self.run_host_command(cmd)
        self.run_host_command("ifdown %s" % self.host_intf)
        self.run_host_command("ifup %s" % self.host_intf)

    def restore_peer_intf(self):
        """
        Restore peer interfaces
        """
        cmd = "ip link delete %s.%s" % (self.peer_intf, self.vlan_num)
        self.run_peer_command(cmd)
        self.run_peer_command("ifdown %s" % self.peer_intf)
        self.run_peer_command("ifup %s" % self.peer_intf)

    def tearDown(self):
        """
        Restore back the default VLAN ID 1
        and also restore interfaces back when full test is run
        """
        self.vlan_port_conf("1", "1")
        if hasattr(self, 'test_type') and self.test_type == "full":
            # Disable PVID tagging as other tests need it to be in disabled.
            self.run_switch_command("no vlan dot1q tag native")
            self.restore_host_intf()
            self.restore_peer_intf()
        self.peer_logout()


if __name__ == "__main__":
    main()
