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
# Copyright: 2017 IBM
# Author: Harish Sriram <harish@linux.vnet.ibm.com>
# Bridge interface test


import netifaces
from avocado import main
from avocado import Test
from avocado.utils import process
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.network.hosts import LocalHost


class Bridging(Test):
    '''
    Test bridge interface
    '''

    def check_failure(self, cmd):
        if process.system(cmd, sudo=True, shell=True, ignore_status=True):
            self.fail("Command %s failed" % cmd)

    def setUp(self):
        self.host_interface = self.params.get("interface",
                                              default=None)
        if not self.host_interface:
            self.cancel("User should specify host interface")

        interfaces = netifaces.interfaces()
        if self.host_interface not in interfaces:
            self.cancel("Interface is not available")

        self.peer_ip = self.params.get("peer_ip", default=None)
        if not self.peer_ip:
            self.cancel("User should specify peer IP")
        self.ipaddr = self.params.get("host_ip", default="")
        self.netmask = self.params.get("netmask", default="")
        self.bridge_interface = self.params.get("bridge_interface",
                                                default="br0")

    def test_bridge_create(self):
        '''
        Set up the ethernet bridge configuration in the linux kernel
        '''
        self.check_failure('ip link add dev %s type bridge'
                           % self.bridge_interface)
        check_flag = False
        cmd = 'ip -d link show %s' % self.bridge_interface
        check_br = process.system_output(cmd, verbose=True,
                                         ignore_status=True).decode("utf-8")
        for line in check_br.splitlines():
            if line.find('bridge'):
                check_flag = True
        if not check_flag:
            self.fail('Bridge interface is not created')
        self.check_failure('ip link set %s master %s'
                           % (self.host_interface, self.bridge_interface))
        self.check_failure('ip addr flush dev %s' % self.host_interface)

    def test_bridge_run(self):
        '''
        run bridge test
        '''
        local = LocalHost()
        networkinterface = NetworkInterface(self.bridge_interface, local,
                                            if_type="Bridge")
        networkinterface.add_ipaddr(self.ipaddr, self.netmask)
        networkinterface.bring_up()
        networkinterface.save(self.ipaddr, self.netmask)
        if networkinterface.ping_check(self.peer_ip, count=5) is not None:
            self.fail('Ping using bridge failed')
        networkinterface.remove_ipaddr(self.ipaddr, self.netmask)

    def test_bridge_delete(self):
        '''
        Set to original state
        '''
        self.check_failure('ip link del dev %s' % self.bridge_interface)


if __name__ == "__main__":
    main()
