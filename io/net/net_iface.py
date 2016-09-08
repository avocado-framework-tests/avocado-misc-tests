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
# Copyright: 2016 IBM
# Author: Prudhvi Miryala<mprudhvi@linux.vnet.ibm.com>
#

# test network interface
# check the status of interface throug ethtool, ip link show

import time
import netifaces
from avocado import main
from avocado import Test
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import process


class NetInterfaceTest(Test):
    '''
     check the network interface, and test
     the status of interface through
     ethtool and ip link show
    '''
    def setUp(self):
        '''
            To check and install dependencies for the test
        '''
        sm = SoftwareManager()
        network_tools = ("iputils", "ethtool", "net-tools")
        for pkg in network_tools:
            if not sm.check_installed(pkg) and not sm.install(pkg):
                self.skip("%s package is need to test" % pkg)
        interfaces = netifaces.interfaces()
        interface = self.params.get("iface")
        if interface not in interfaces:
            self.skip("%s interface is not available" % interface)
        self.interface = interface
        self.eth = "ethtool %s | grep 'Link detected:'" % self.interface
        self.ip_link = "ip link show %s | head -1" % self.interface
        self.eth_state = process.system_output(self.eth, shell=True)

    def testinterface(self):
        # test the interface
        if_down = "ifconfig %s down" % self.interface
        if_up = "ifconfig %s up" % self.interface
        # down the interface
        process.system(if_down, shell=True)
        # check the status of interface through ethtool
        ret = process.system_output(self.eth, shell=True)
        if 'yes' in ret:
            self.fail("interface test failed")
        # check the status of interface through ip link show
        ret = process.system_output(self.ip_link, shell=True)
        if 'UP' in ret:
            self.fail("interface test failed")
        # up the interface
        process.system(if_up, shell=True)
        time.sleep(4)
        # check the status of interface through ethtool
        ret = process.system_output(self.eth, shell=True)
        if 'no' in ret:
            self.fail("interface test failed")
        # check the status of interface through ip link show
        ret = process.system_output(self.ip_link, shell=True)
        if 'DOWN' in ret:
            self.fail("interface test failed")

    def tearDown(self):
        # set the intial state
        self.log.info('setting intial state')
        if 'yes' in self.eth_state:
            process.system("ifconfig %s up" % self.interface, shell=True)
        else:
            process.system("ifconfig %s down" % self.interface, shell=True)

if __name__ == "__main__":
    main()
