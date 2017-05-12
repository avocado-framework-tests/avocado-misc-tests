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
# test multicasting
# to test we need to enable  multicast option on host
# then ping from peer to multicast group

import netifaces
from avocado import main
from avocado import Test
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import process
from avocado.utils import distro


class ReceiveMulticastTest(Test):
    '''
    check multicast receive
    using ping tool
    '''

    def setUp(self):
        '''
        To check and install dependencies for the test
        '''
        smm = SoftwareManager()
        pkgs = ["net-tools"]
        detected_distro = distro.detect()
        if detected_distro.name == "Ubuntu":
            pkgs.extend(["openssh-client", "iputils-ping"])
        elif detected_distro.name == "SuSE":
            pkgs.extend(["openssh", "iputils"])
        else:
            pkgs.extend(["openssh-clients", "iputils"])
        for pkg in pkgs:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.skip("%s package is need to test" % pkg)
        interfaces = netifaces.interfaces()
        self.iface = self.params.get("interface")
        if self.iface not in interfaces:
            self.skip("%s interface is not available" % self.iface)
        self.peer = self.params.get("peer_ip", default="")
        if self.peer == "":
            self.skip("peer ip should specify in input")
        self.user = self.params.get("user_name", default="root")
        msg = "ip addr show  | grep %s | grep -oE '[^ ]+$'" % self.peer
        cmd = "ssh %s@%s \"%s\"" % (self.user, self.peer, msg)
        self.peerif = process.system_output(cmd, shell=True).strip()
        if self.peerif == "":
            self.skip("unable to get peer interface")
        cmd = "ip -f inet -o addr show %s | awk '{print $4}' | cut -d / -f1"\
              % self.iface
        self.local_ip = process.system_output(cmd, shell=True).strip()
        if self.local_ip == "":
            self.skip("unable to get local ip")

    def test_multicast(self):
        '''
        ping to peer machine
        '''
        cmd = "echo 0 > /proc/sys/net/ipv4/icmp_echo_ignore_broadcasts"
        if process.system(cmd, shell=True, verbose=True,
                          ignore_status=True) != 0:
            self.fail("unable to set value to icmp_echo_ignore_broadcasts")
        cmd = "ip link set %s allmulticast on" % self.iface
        if process.system(cmd, shell=True, verbose=True,
                          ignore_status=True) != 0:
            self.fail("unable to set all mulicast option to test interface")
        msg = "ping -I %s 224.0.0.1 -c 1 | grep %s" %\
              (self.peerif, self.local_ip)
        cmd = "timeout 600 ssh %s@%s \"%s\"" % (self.user, self.peer, msg)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("multicast test failed")

    def tearDown(self):
        '''
        turn off multicast option
        '''
        cmd = "echo 1 > /proc/sys/net/ipv4/icmp_echo_ignore_broadcasts"
        if process.system(cmd, shell=True, verbose=True,
                          ignore_status=True) != 0:
            self.log.info("unable to unset all mulicast option")
        cmd = "ip link set %s allmulticast off" % self.iface
        if process.system(cmd, shell=True, verbose=True,
                          ignore_status=True) != 0:
            self.log.info("unable to unset all mulicast option")


if __name__ == "__main__":
    main()
