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
# Copyright: 2019 IBM
# Author: Narasimhan V <sim@linux.vnet.ibm.com>
#

"""
Tests the network driver and interface with 'ethtool' command.
Different parameters are specified in Parameters section of multiplexer file.
Interfaces are specified in Interfaces section of multiplexer file.
This test needs to be run as root.
"""

import netifaces
from avocado import main
from avocado import Test
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import process
from avocado.utils import distro
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.network.hosts import LocalHost
from avocado.utils import wait


class Ethtool(Test):
    '''
    To test different types of pings
    '''

    def setUp(self):
        '''
        To check and install dependencies for the test
        '''
        smm = SoftwareManager()
        pkgs = ["ethtool", "net-tools"]
        detected_distro = distro.detect()
        if detected_distro.name == "Ubuntu":
            pkgs.extend(["iputils-ping"])
        elif detected_distro.name == "SuSE":
            pkgs.extend(["iputils"])
        else:
            pkgs.extend(["iputils"])
        for pkg in pkgs:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel("%s package is need to test" % pkg)
        interfaces = netifaces.interfaces()
        interface = self.params.get("interface")
        if interface not in interfaces:
            self.cancel("%s interface is not available" % interface)
        self.iface = interface
        self.ipaddr = self.params.get("host_ip", default="")
        self.netmask = self.params.get("netmask", default="")
        self.peer = self.params.get("peer_ip")
        if not self.peer:
            self.cancel("No peer provided")
        local = LocalHost()
        if self.iface[0:2] == 'ib':
            self.networkinterface = NetworkInterface(self.iface, local,
                                                     if_type='Infiniband')
            try:
                self.networkinterface.add_ipaddr(self.ipaddr, self.netmask)
                self.networkinterface.save(self.ipaddr, self.netmask)
            except Exception:
                self.networkinterface.save(self.ipaddr, self.netmask)
        else:
            self.networkinterface = NetworkInterface(self.iface, local)
            try:
                self.networkinterface.add_ipaddr(self.ipaddr, self.netmask)
                self.networkinterface.save(self.ipaddr, self.netmask)
            except Exception:
                self.networkinterface.save(self.ipaddr, self.netmask)
        self.networkinterface.bring_up()
        if not wait.wait_for(self.networkinterface.is_link_up, timeout=120):
            self.cancel("Link up of interface is taking longer than 120s")
        if self.networkinterface.ping_check(self.peer, count=5) is not None:
            self.cancel("No connection to peer")
        self.args = self.params.get("arg", default='')
        self.elapse = self.params.get("action_elapse", default='')
        self.priv_test = self.params.get("privflag_test", default=False)
        if self.priv_test:
            cmd = "ethtool --show-priv-flags %s" % (self.iface)
            self.ret_val = process.run(cmd, shell=True, verbose=True,
                                       ignore_status=True)
            if self.ret_val.exit_status:
                self.cancel("Device Doesn't support Private flags")

    def interface_state_change(self, interface, state, status):
        '''
        Set the interface state specified, and return True if done.
        Returns False otherwise.
        '''
        cmd = "ip link set dev %s %s" % (interface, state)
        if state == "up":
            if process.system(cmd, shell=True, ignore_status=True) != 0:
                return False
            if not wait.wait_for(self.networkinterface.is_link_up,
                                 timeout=120):
                self.fail("Link up of interface is taking longer than 120s")
        else:
            if process.system(cmd, shell=True, ignore_status=True) != 0:
                return False
        if status != self.interface_link_status(interface):
            return False
        return True

    def interface_link_status(self, interface):
        '''
        Return the status of the interface link from ethtool.
        '''
        cmd = "ethtool %s" % interface
        for line in process.system_output(cmd, shell=True,
                                          ignore_status=True).decode("utf-8") \
                                                             .splitlines():
            if 'Link detected' in line:
                return line.split()[-1]
        return ''

    def test_ethtool(self):
        '''
        Test the ethtool args provided
        '''
        for state, status in zip(["down", "up"], ["no", "yes"]):
            if not self.interface_state_change(self.iface, state, status):
                self.fail("interface %s failed" % state)
            cmd = "ethtool %s %s %s" % (self.args, self.iface, self.elapse)
            ret = process.run(cmd, shell=True, verbose=True,
                              ignore_status=True)
            if ret.exit_status != 0:
                if "Operation not supported" in ret.stderr_text:
                    self.log.warn("%s failed" % self.args)
                else:
                    self.fail("failed")
        if self.networkinterface.ping_check(self.peer, count=10000,
                                            options='-f') is not None:
            self.fail("flood ping test failed")
        if self.priv_test:
            self.ethtool_toggle_priv_flags()

    def ethtool_toggle_priv_flags(self):
        '''
        Toggle the priv flag settings of the driver.
        '''
        priv_pass = []
        priv_fail = []
        for oper in ('toggle', 'setback'):
            for line in self.ret_val.stdout_text.splitlines():
                if "off" in line:
                    val = "on"
                else:
                    val = "off"
                if "flags" not in line:
                    priv_flag = line.split(':')[0]
                    cmd = "ethtool --set-priv-flags %s \"%s\" %s" % \
                          (self.iface, priv_flag.rstrip(), val)
                    ret1 = process.run(cmd, shell=True, verbose=True,
                                       ignore_status=True)
                    if ret1.exit_status == 0 or 'supported' in \
                       ret1.stderr_text:
                        priv_pass.append(priv_flag.rstrip())
                    else:
                        priv_fail.append(priv_flag.rstrip())
            if self.networkinterface.ping_check(self.peer, count=500000,
                                                options='-f') is not None:
                self.fail("Ping failed oper = %s" % oper)
        if priv_fail:
            self.fail("Private flags could not be toggled: %s" %
                      ",".join(list(set(priv_fail))))

    def tearDown(self):
        '''
        Set the interface up at the end of test.
        '''
        self.interface_state_change(self.iface, "up", "yes")
        self.networkinterface.remove_ipaddr(self.ipaddr, self.netmask)


if __name__ == "__main__":
    main()
