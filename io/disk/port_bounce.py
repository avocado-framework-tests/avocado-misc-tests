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
# Author: Naresh Bannoth <nbannoth@in.ibm.com>
# this script runs portbounce test on different ports of fc or fcoe switches.

import re
import time

import paramiko
# import telnetlib
from avocado import Test
from avocado.utils import genio, multipath, process, wait

# import shutil
# try:
#    import pxssh
# except ImportError:
#    from pexpect import pxssh


class CommandFailed(Exception):
    '''
    exception class
    '''
    def __init__(self, command, output, exitcode):
        self.command = command
        self.output = output
        self.exitcode = exitcode

    def __str__(self):
        return "Command '%s' exited with %d.\nOutput:\n%s" \
               % (self.command, self.exitcode, self.output)


class PortBounceTest(Test):

    """
    :param switch_name: FC Switch name/ip
    :param userid: FC switch user name to login
    :param password: FC switch password to login
    :param port_ids: FC switch port ids where port needs to disable/enable
    :param pci_adrs: List of PCI bus address for corresponding fc ports
    :param sbt: short bounce time in seconds
    :param lbt: long bounce time in seconds
    :param count: Number of times test to run
    """

    def setUp(self):
        """
        test parameters
        """
        self.switch_name = self.params.get("switch_name", '*', default=None)
        self.userid = self.params.get("userid", '*', default=None)
        self.password = self.params.get("password", '*', default=None)
        self.wwids = self.params.get("wwids", default=None).split(" ")
        self.sbt = int(self.params.get("sbt", '*', default=10))
        self.lbt = int(self.params.get("lbt", '*', default=250))
        self.count = int(self.params.get("count", '*', default="2"))
        self.prompt = ">"
        self.verify_sleep_time = 20
        self.port_ids = []
        self.host = []
        self.dic = {}
        system_wwids = multipath.get_multipath_wwids()
        for wwid in self.wwids:
            paths = []
            if wwid not in system_wwids:
                self.wwids.remove(wwid)
                continue
            paths = multipath.get_paths(wwid)
            for path in paths:
                self.host.append(self.get_fc_host(path))
        self.host = list(dict.fromkeys(self.host))
        self.log.info("AllHostValues: %s" % self.host)

        self.switch_login(self.switch_name, self.userid, self.password)
        for host in self.host:
            port_id = self.get_switch_port(host)
            self.port_ids.append(port_id)
            self.dic[port_id] = host
        self.log.info("AllSwitchPorts:%s " % self.port_ids)

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

    def _send_only_result(self, command, response):
        output = response.decode("utf-8").splitlines()
        self.log.info("output in sendonlyresult: %s" % output)
        if command in output[0]:
            output.pop(0)
        output.pop()
        output = [element.lstrip() + '\n' for element in output]
        response = ''.join(output)
        response = response.strip()
        self.log.info(''.join(response))
        return ''.join(response)

    def run_command(self, command, timeout=300):
        '''
        Run command method for running commands on fc switch
        '''
        self.log.info("Running the %s command on fc/nic switch", command)
        if not hasattr(self, 'tnc'):
            self.fail("telnet connection to the fc/nic switch not yet done")
        self.remote_conn.send(command + '\n')
        time.sleep(self.verify_sleep_time)
        response = self.remote_conn.recv(4000)
        self.log.info("response before sendonly_output: %s", response)
        return self._send_only_result(command, response)

    def test(self):
        '''
        Test method
        '''
        self.failure_list = {}
        self.port_bounce()
        if self.failure_list:
            self.fail("failed ports, details: %s" % self.failure_list)

    def port_bounce(self):
        '''
        defins and test for different scenarios
        '''
        bounce_time = [self.sbt, self.lbt]
        self.log.info("short/long port bounce for individual ports:")
        for b_time in bounce_time:
            self.log.info("test is running for %s bounce time" % b_time)
            for port in self.port_ids:
                # appending the each port into list and sending same list
                # element for port_toggle which are usefull in verification
                # methods
                test_ports = []
                test_ports.append(port)
                for _ in range(self.count):
                    self.porttoggle(test_ports, b_time)

        self.log.info("port bounce for all ports:")
        for _ in range(self.count):
            self.porttoggle(self.port_ids, 300)

    def porttoggle(self, test_ports, sleep_time):
        '''
        port bounce starts here
        '''
        # Port disable and verification both in switch and OS
        self.port_enable_disable(test_ports, 'disable')
        time.sleep(self.verify_sleep_time)
        self.verify_switch_port_state(test_ports, 'Disabled')
        self.verify_port_host_state(test_ports, "Linkdown")
        self.mpath_state_check(test_ports, "failed", "faulty")
        time.sleep(sleep_time)

        # Port Enable and verification both in switch and OS
        self.port_enable_disable(test_ports, 'enable')
        time.sleep(self.verify_sleep_time)
        self.verify_switch_port_state(test_ports, 'Online')
        self.verify_port_host_state(test_ports, "Online")
        time.sleep(self.verify_sleep_time)
        self.mpath_state_check(test_ports, 'active', 'ready')

    def port_enable_disable(self, test_ports, typ):
        '''
        enable or disable the port based on typ variable passed
        '''
        switch_info = self.run_command("switchshow")
        self.log.info("Swicth info: %s", switch_info)

        # Port Disable/enable
        self.log.info("%s port(s) %s", typ, test_ports)
        port_input = " ".join(test_ports)
        try:
            self.run_command("port%s %s" % (typ, port_input))
        except CommandFailed as cf:
            self.log.info("port %s failed for port(s) %s, details: %s",
                          typ, test_ports, str(cf))

    def verify_switch_port_state(self, test_ports, state):
        '''
        checking port link status after disabling the switch port
        '''
        self.log.info("verifying switch port %s", state)
        switch_info = self.run_command("switchshow")
        for port in test_ports:
            self.log.info("verify port %s %s in %s", port, state, test_ports)
            port_string = ".*%s.*%s" % (port, state)
            obj = re.search(port_string, switch_info)
            if obj:
                self.log.info("Port %s is %s(ed)", port, state)
            else:
                self.log.debug("switch_info: %s", switch_info)
                msg = "Port %s is failed to %s" % (port, state)
                self.failure_list[port] = msg

    def verify_port_host_state(self, test_ports, status):
        """
        Verifies port enable/disable status change in host
        side for corresponding fc adapter
        """
        for port in test_ports:
            self.log.info("OS host check for %s", status)
            state = genio.read_file("/sys/class/fc_host/%s/port_state"
                                    % self.dic[port]).rstrip("\n")
            if status == "Linkdown":
                if state == status or state == "Offline":
                    self.log.info("host:%s verify status:%s success",
                                  self.dic[port], state)
                else:
                    self.fail("port state not changed in host expected \
                              state: %s,actual_state: %s" % (status, state))
            elif state == status:
                self.log.info("host:%s verify status:%s success",
                              self.dic[port], state)
            else:
                self.fail("port state not changed in host expected \
                          state: %s,actual_state: %s" % (status, state))

    def mpath_state_check(self, ports, state1, state2):
        '''
        checking mpath disk status after disabling the switch port
        '''
        curr_path = ''
        err_paths = []

        def is_path_online():
            path_stat = multipath.get_path_status(curr_path)
            if path_stat[0] != state1 or path_stat[2] != state2:
                return False
            return True

        for port in ports:
            paths = self.get_paths(self.dic[port])
            self.log.info("verify %s path status for port %s in %s",
                          state1, port, ports)
            for path in paths:
                curr_path = path
                if not wait.wait_for(is_path_online, timeout=10):
                    err_paths.append("%s:%s" % (port, curr_path))
        if err_paths:
            self.error("following paths not %s: %s" % (state1, err_paths))
        else:
            self.log.info("%s path verification is success", state1)

    def get_paths(self, fc_host):
        '''
        returns the list of paths coressponding to the given fc_host
        '''
        paths = []
        cmd = 'ls -l /sys/block/ | grep -i %s' % fc_host
        for line in process.getoutput(cmd):
            if "/%s/" % fc_host in line:
                paths.append(line.split("/")[-1])
        return paths

    def get_wwpn(self, fc_host):
        '''
        find and return the wwpn of a fc_host
        '''
        cmd = 'cat /sys/class/fc_host/%s/port_name' % fc_host
        wwpn = process.getoutput(cmd)[2:]
        wwpn = ':'.join([wwpn[i:i+2] for i in range(0, len(wwpn), 2)])
        return wwpn

    def get_fc_host(self, path):
        '''
        find and returns fc_host for given disk
        '''
        cmd = 'ls -l /sys/block/ | grep -i %s' % path
        out = process.getoutput(cmd)
        for line in out.split("/"):
            if "host" in line:
                return line

    def get_switch_port(self, host):
        '''
        finds and returns the switch port number for given fc_host
        '''
        wwpn = self.get_wwpn(host)
        self.log.info("value of wwpn=%s", wwpn)
        cmd = 'nodefind %s | grep -i "Port Index"' % wwpn
        switch_info = self.run_command(cmd)
        self.log.info("switchinfo = \n %s\n", switch_info)
        return switch_info.split(" ")[-1]

    def tearDown(self):
        '''
        checks for any error or failure messages in dmesg and
        bring backs the switch port_online after test completion
        '''
        self.port_enable_disable(self.port_ids, 'enable')
        time.sleep(self.verify_sleep_time)
        self.verify_switch_port_state(self.port_ids, 'Online')
        output = process.system_output("dmesg -T --level=alert,crit,err,warn",
                                       ignore_status=True,
                                       shell=True, sudo=True)

        self.log.debug("Kernel Errors: %s", output)
