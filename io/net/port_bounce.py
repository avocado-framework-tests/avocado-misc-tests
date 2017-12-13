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


class CommandFailed(Exception):
    def __init__(self, command, output, exitcode):
        self.command = command
        self.output = output
        self.exitcode = exitcode

    def __str__(self):
        return "Command '%s' exited with %d.\nOutput:\n%s" \
               % (self.command, self.exitcode, self.output)


class PortBounceTest(Test):

    """
    :param type: <fc/fcoe> : type of switch fc/fcoe <in small case>
    :param fcoe_fc: <yes/no> : If port is an FC port in FCOE switch
    :param switch_name: FC Switch name/ip
    :param userid: FC switch user name to login
    :param password: FC switch password to login
    :param port_ids: FC switch port ids where port needs to disable/enable
    :param pci_bus_addrs: List of PCI bus address for corresponding fc ports
    :param sbt: short bounce time in seconds
    :param lbt: long bounce time in seconds
    :param count: Number of times test to run
    """

    def setUp(self):
        """
        test parameters
        """
        self.parameters()

    def parameters(self):
        self.fc_type = self.params.get("type", '*', default=None)
        self.fcoe_fc = self.params.get("fcoe_fc", '*', default=None)
        self.switch_name = self.params.get("switch_name", '*', default=None)
        self.userid = self.params.get("userid", '*', default=None)
        self.password = self.params.get("password", '*', default=None)
        self.port_ids = self.params.get("port_ids",
                                        '*', default=None).split(",")
        self.pci_bus_addrs = self.params.get("pci_bus_addrs",
                                             '*', default=None).split(",")
        self.sbt = int(self.params.get("sbt", '*', default=5))
        self.lbt = int(self.params.get("lbt", '*', default=250))
        self.count = int(self.params.get("count", '*', default="2"))
        self.prompt = ">"

    def fc_login(self, ip, username, password):
        '''
        telnet Login method for remote fc switch
        '''
        self.tnc = telnetlib.Telnet(ip)
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
        if self.fc_type == "fcoe":
            if self.fcoe_fc == "yes":
                test = self.porttoggle_fcoe_fc
            else:
                test = self.porttoggle_fcoe
        else:
            test = self.porttoggle
        self.failure_list = {}
        self.port_bounce(test)
        if self.failure_list:
            self.fail("Some ports failed in portbounce tests, details: %s",
                      self.failure_list)

    def port_bounce(self, test):
        test_ports = []
        for port in self.port_ids:
            test_ports.append(port)
            self.log.info("Portbounce test for port(s) %s for %s times",
                          test_ports, self.count)
            for i in range(self.count):
                self.log.info("Port(s) %s, Short Portbounce test", test_ports)
                test(self, test_ports, self.sbt)
                self.log.info("Port(s) %s, Long Portbounce test", test_ports)
                test(self, test_ports, self.lbt)
                self.log.info("%s portbounce test(s) completed for Port(s) %s",
                              i+1, test_ports)

    @staticmethod
    def porttoggle(self, test_ports, sleep_time):
        self.fc_login(self.switch_name, self.userid, self.password)
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
        time.sleep(sleep_time)
        self.verify_port_disable(test_ports)
        self.verify_port_toggle_host("Linkdown")

        # Port Enable
        self.log.info("Enable port(s) %s", test_ports)
        try:
            self.fc_run_command("portenable %s" % port_input)
        except CommandFailed as cf:
            self.log.info("port enable failed for port %s, details: %s",
                          test_ports, str(cf))
        time.sleep(5)
        self.verify_port_enable(test_ports)
        self.verify_port_toggle_host("Online")

    def verify_port_disable(self, test_ports):
        """
        Verifies port disable in fc switch
        """
        switch_info = self.fc_run_command("switchshow")
        for port in test_ports:
            port_string = ".*%s.*No_Sync" % port
            Obj = re.search(port_string, switch_info)
            if Obj:
                self.log.info("Port %s is disabled", port)
            else:
                self.log.debug("switch_info: %s", switch_info)
                msg = "Port %s is failed to disable" % port
                self.failure_list[port] = msg

    def verify_port_enable(self, test_ports):
        """
        Verifies port enable in fc switch
        """
        switch_info = self.fc_run_command("switchshow")
        for port in test_ports:
            port_string = ".*%s.*Online" % port
            Obj = re.search(port_string, switch_info)
            if Obj:
                self.log.info("Port %s is enabled", port)
            else:
                self.log.debug("switch_info: %s", switch_info)
                msg = "Port %s is failed to enable" % port
                self.failure_list[port] = msg

    def verify_port_toggle_host(self, status):
        """
        Verifies port enable/disable status change in host
        side for corresponding fc adapter
        """
        for bus_id in self.pci_bus_addrs:
            pci_class = pci.get_pci_class_name(bus_id)
            intf = pci.get_interfaces_in_pci_address(bus_id, pci_class)[-1]
            state = genio.read_file("/sys/class/fc_host/%s/port_state"
                                    % intf).rstrip("\n")
            self.log.info("Host bus: %s, state: %s", bus_id, state)
            if state == status:
                self.log.info("bus: %s, port status %s got reflected",
                              bus_id, state)
            else:
                self.fail("port state not changed in host expected state: %s, \
                          actual_state: %s", status, state)

    def porttoggle_fcoe(self, port, sleep_time):
        pass

    def porttoggle_fcoe_fc(self, port, sleep_time):
        pass

    def tearDown(self):
        output = process.system_output("dmesg -T --level=alert,crit,err,warn",
                                       ignore_status=True,
                                       shell=True, sudo=True)

        self.log.debug("Kernel Errors: %s", output)
        # verify given test ports are online after test.
        self.verify_port_enable(self.port_ids)
        self.verify_port_toggle_host("Online")


if __name__ == "__main__":
    main()
