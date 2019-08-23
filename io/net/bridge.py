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

        cmd = "ip addr show %s | sed -nr 's/.*inet ([^ ]+)."\
            "*/\\1/p'" % self.host_interface
        self.cidr = process.system_output(
            '%s' % cmd, shell=True).decode("utf-8")
        cmd = "route -n | grep %s | grep -w UG | awk "\
            "'{ print $2 }'" % self.host_interface
        self.gateway = process.system_output(
            '%s' % cmd, shell=True).decode("utf-8")
        cmd = "ip addr show %s | grep inet | grep brd | "\
            "awk '{ print $4 }'" % self.host_interface
        self.broadcast = process.system_output(
            '%s' % cmd, shell=True).decode("utf-8")

    def test(self):
        '''
        Bridge Test
        Set up the ethernet bridge configuration in the linux kernel
        '''
        self.check_failure('ip link add dev br0 type bridge')
        check_flag = False
        check_br = process.system_output('ip -d link show br0', verbose=True,
                                         ignore_status=True).decode("utf-8")
        for line in check_br.splitlines():
            if line.find('bridge'):
                check_flag = True
        if not check_flag:
            self.fail('Bridge interface is not created')

        self.check_failure('ip link set %s master br0' % self.host_interface)
        self.check_failure('ip addr flush dev %s' % self.host_interface)
        self.check_failure('ip addr add %s broadcast %s dev br0' %
                           (self.cidr, self.broadcast))
        self.check_failure('ip link set br0 up')
        if self.gateway:
            self.check_failure('ip route add default via %s' %
                               self.gateway)
        if process.system('ping %s -I br0 -c 4' % self.peer_ip,
                          shell=True, ignore_status=True):
            self.fail('Ping using bridge failed')

    def tearDown(self):
        '''
        Set to original state
        '''
        self.check_failure('ip link set br0 down')
        self.check_failure('ip link del dev br0')
        self.check_failure('ip addr add %s broadcast %s dev %s' % (
            self.cidr, self.broadcast, self.host_interface))
        self.check_failure('ip link set %s up' % self.host_interface)
        if self.gateway:
            self.check_failure('ip route add default via %s' %
                               self.gateway)
        if process.system('ping %s -c 4' % self.peer_ip,
                          shell=True, ignore_status=True):
            self.fail('Ping failed when restoring back to provided interface')


if __name__ == "__main__":
    main()
