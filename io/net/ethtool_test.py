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
from avocado.utils import configure_network
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
        configure_network.set_ip(self.ipaddr, self.netmask, self.iface)
        self.peer = self.params.get("peer_ip")
        if not self.peer:
            self.cancel("No peer provided")
        self.args = self.params.get("arg", default='')
        self.elapse = self.params.get("action_elapse", default='')

    def interface_state_change(self, interface, state, status):
        '''
        Set the interface state specified, and return True if done.
        Returns False otherwise.
        '''
        cmd = "ip link set dev %s %s" % (interface, state)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            return False
        if not wait.wait_for(configure_network.interface_link_up,
                             timeout=120, args=[self.iface]):
            return False
        return True

    def test_ethtool(self):
        '''
        Test the ethtool args provided
        '''
        if not wait.wait_for(configure_network.interface_link_up,
                             timeout=120, args=[self.iface]):
            self.fail("interface UP failed")
        else:
            cmd = "ethtool %s %s %s" % (self.args, self.iface, self.elapse)
            ret = process.run(cmd, shell=True, verbose=True,
                              ignore_status=True)
            if ret.exit_status != 0:
                self.fail("failed")
            if not wait.wait_for(configure_network.interface_link_up,
                                 timeout=120, args=[self.iface]):
                print("Link is taking longer time to link up after \
                      running ethtool command")
                return False
            else:
                if not self.ping_check('-c 5'):
                    self.fail("ping failed after interface is up")

    def ping_check(self, options):
        '''
        Checks if ping to peer works fine and returns True.
        Returns False otherwise.
        '''
        cmd = "ping -I %s %s %s" % (self.iface, options, self.peer)
        if process.system(cmd, shell=True, verbose=True,
                          ignore_status=True) != 0:
            return False
        return True

    def tearDown(self):
        '''
        Set the interface up at the end of test.
        '''
        self.interface_state_change(self.iface, "up", "yes")
        configure_network.unset_ip(self.iface)


if __name__ == "__main__":
    main()
