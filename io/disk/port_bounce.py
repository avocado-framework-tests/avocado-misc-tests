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
# this script runs portbounce test on different ports of fc or fcoe switches.

import re
import time
import telnetlib
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils import genio, pci
from avocado.utils import multipath


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
        self.pci_adrs = self.params.get("pci_device", default=None).split(",")
        self.sbt = int(self.params.get("sbt", '*', default=10))
        self.lbt = int(self.params.get("lbt", '*', default=250))
        self.count = int(self.params.get("count", '*', default="2"))
        self.prompt = ">"
        self.verify_sleep_time = 20
        self.port_ids = []
        self.dic = {}
        for pci_id in self.pci_adrs:
            port_id = self.get_switch_port(pci_id)
            self.port_ids.append(port_id)
            self.dic[port_id] = pci_id

    def fc_login(self, switch_ip, username, password):
        '''
        telnet Login method for remote fc switch
        '''
        self.tnc = telnetlib.Telnet(switch_ip)
        self.tnc.read_until('login: ')
        self.tnc.write(username + '\n')
        self.tnc.read_until('assword: ')
        self.tnc.write(password + '\n')
        ret = self.tnc.read_until(self.prompt)
        assert self.prompt in ret

    def _send_only_result(self, command, response):
        output = response.splitlines()
        if command in output[0]:
            output.pop(0)
        output.pop()
        output = [element.lstrip()+'\n' for element in output]
        response = ''.join(output)
        response = response.strip()
        return ''.join(response)

    def fc_run_command(self, command, timeout=300):
        '''
        Telnet Run command method for running commands on fc switch
        '''
        self.log.info("Running the command on fc switch %s", command)
        if not hasattr(self, 'tnc'):
            self.fail("telnet connection to the fc switch not yet done")
        self.tnc.write(command + '\n')
        response = self.tnc.read_until(self.prompt)
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
        test_ports = []
        self.log.info("short port bounce for individual ports:")
        for port in self.port_ids:
            test_ports = []
            test_ports.append(port)
            for _ in range(self.count):
                self.porttoggle(test_ports, self.sbt)

        self.log.info("Long port bounce for individual ports:")
        for port in self.port_ids:
            test_ports = []
            test_ports.append(port)
            for _ in range(self.count):
                self.porttoggle(test_ports, self.lbt)

        self.log.info("port bounce for all ports:")
        for _ in range(self.count):
            self.porttoggle(self.port_ids, 300)
            time.sleep(20)

    def porttoggle(self, test_ports, sleep_time):
        '''
        port bounce starts here
        '''
        switch_info = self.fc_run_command("switchshow")
        self.log.info("Swicth info: %s", switch_info)

        # Port Disable
        self.log.info("Disable port(s) %s", test_ports)
        port_input = " ".join(test_ports)
        try:
            self.fc_run_command("portdisable %s" % port_input)
        except CommandFailed as cf:
            self.log.info("port disable failed for port(s) %s, details: %s",
                          test_ports, str(cf))

        # Port disable verification both in switch and OS
        time.sleep(self.verify_sleep_time)
        self.verify_port_disable(test_ports)
        self.verify_port_toggle_host(test_ports, "Linkdown")
        self.mpath_fail_check(test_ports)
        time.sleep(sleep_time)

        # Port Enable
        self.log.info("Enable port(s) %s", test_ports)
        try:
            self.fc_run_command("portenable %s" % port_input)
        except CommandFailed as cf:
            self.log.info("port enable failed for port %s, details: %s",
                          test_ports, str(cf))
        time.sleep(self.verify_sleep_time)
        self.verify_port_enable(test_ports)
        self.verify_port_toggle_host(test_ports, "Online")
        time.sleep(self.verify_sleep_time)
        self.mpath_pass_check(test_ports)

    def verify_port_disable(self, test_ports):
        '''
        checking port link status after disabling the switch port
        '''
        self.log.info("verifying port disables")
        switch_info = self.fc_run_command("switchshow")
        for port in test_ports:
            self.log.info("verify port %s disable in %s", port, test_ports)
            port_string = ".*%s.*Disabled" % port
            obj = re.search(port_string, switch_info)
            if obj:
                self.log.info("Port %s is disabled", port)
            else:
                self.log.debug("switch_info: %s", switch_info)
                msg = "Port %s is failed to disable" % port
                self.failure_list[port] = msg

    def verify_port_toggle_host(self, test_ports, status):
        """
        Verifies port enable/disable status change in host
        side for corresponding fc adapter
        """
        for port in test_ports:
            pci_id = self.dic[port]
            fc_host = self.get_fc_host(pci_id)
            state = genio.read_file("/sys/class/fc_host/%s/port_state"
                                    % fc_host).rstrip("\n")
            if state == status:
                self.log.info("PCI_BUS: %s, port status %s got reflected",
                              pci_id, state)
            else:
                self.fail("port state not changed in host expected state: %s, \
                          actual_state: %s", status, state)

    def verify_port_enable(self, test_ports):
        '''
        checking port link after enabling the switch port
        '''
        switch_info = self.fc_run_command("switchshow")
        for port in test_ports:
            self.log.info("switch:verfy prt %s enble in %s", port, test_ports)
            port_string = ".*%s.*Online" % port
            obj = re.search(port_string, switch_info)
            if obj:
                self.log.info("switch Port %s is enabled in %s",
                              port, test_ports)
            else:
                self.log.debug("switch_info: %s", switch_info)
                msg = "switch:enable %s in %s failed" % (port, test_ports)
                self.failure_list[port] = msg

    def mpath_fail_check(self, ports):
        '''
        checking mpath disk status after disabling the switch port
        '''
        for port in ports:
            pci_id = self.dic[port]
            paths = pci.get_disks_in_pci_address(pci_id)
            err_paths = []
            self.log.info("verify fail path status for port %s in %s",
                          port, ports)
            for path in paths:
                path_stat = multipath.get_path_status(path.split("/")[-1])
                if path_stat[0] == 'active' or path_stat[2] == 'ready':
                    err_paths.append(path)
        if err_paths:
            self.error("following paths did not failed : %s" % err_paths)
        else:
            self.log.info("Disable path verification is success")

    def mpath_pass_check(self, ports):
        '''
        checking mpath disk status after enabling the switch port
        '''
        for port in ports:
            pci_id = self.dic[port]
            paths = pci.get_disks_in_pci_address(pci_id)
            err_paths = []
            self.log.info("verify enable path status for port %s in %s",
                          port, ports)
            for path in paths:
                path_stat = multipath.get_path_status(path.split("/")[-1])
                if path_stat[0] == 'failed' or path_stat[2] == 'faulty':
                    err_paths.append(path)
        if err_paths:
            self.error("following paths did not recover %s" % err_paths)
        else:
            self.log.info("enable path verification is success")

    def get_wwpn(self, fc_host):
        '''
        find and return the wwpn of a fc_host
        '''
        cmd = 'cat /sys/class/fc_host/%s/port_name' % fc_host
        wwpn = process.getoutput(cmd)[2:]
        wwpn = ':'.join([wwpn[i:i+2] for i in range(0, len(wwpn), 2)])
        return wwpn

    def get_fc_host(self, pci_addr):
        '''
        find and returns fc_host for given pci_address
        '''
        cmd = "ls -l /sys/class/fc_host/ | grep -i %s" % pci_addr
        return process.getoutput(cmd).split("/")[-1]

    def get_switch_port(self, pci_addr):
        '''
        finds and returns the switch port number for given pci_address
        '''
        fc_host = self.get_fc_host(pci_addr)
        wwpn = self.get_wwpn(fc_host)
        self.log.info("value of wwpn=%s", wwpn)
        self.fc_login(self.switch_name, self.userid, self.password)
        cmd = "switchshow"
        switch_info = self.fc_run_command(cmd)
        self.log.info("switchinfo = \n %s\n", switch_info)
        string_line = ".*%s.*" % wwpn
        line = re.search(string_line, switch_info)
        line = line.group(0)
        port_id = line.split("  ")[1]
        self.log.info("port_id value= %s", port_id)
        return port_id

    def tearDown(self):
        '''
        checks for any error or failure messages in dmesg and
        bring backs the switch port_online after test completion
        '''
        output = process.system_output("dmesg -T --level=alert,crit,err,warn",
                                       ignore_status=True,
                                       shell=True, sudo=True)

        self.log.debug("Kernel Errors: %s", output)
        # verify given test ports are online after test.
        self.verify_port_enable(self.port_ids)


if __name__ == "__main__":
    main()
