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


import os
from avocado import Test
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils.ssh import Session
from avocado.utils import process
from avocado.utils import distro
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.network.hosts import LocalHost


class ReceiveMulticastTest(Test):
    '''
    check multicast receive
    using ping tool
    '''

    def setUp(self):
        '''
        To check and install dependencies for the test
        '''
        local = LocalHost()
        interfaces = os.listdir('/sys/class/net')
        self.peer = self.params.get("peer_ip", default="")
        self.user = self.params.get("user_name", default="root")
        self.peer_password = self.params.get("peer_password",
                                             '*', default="None")
        device = self.params.get("interface", default=None)
        if device in interfaces:
            self.iface = device
        elif local.validate_mac_addr(device) and device in local.get_all_hwaddr():
            self.iface = local.get_interface_by_hwaddr(device).name
        else:
            self.iface = None
            self.cancel("%s interface is not available" % device)
        self.ipaddr = self.params.get("host_ip", default="")
        self.netmask = self.params.get("netmask", default="")
        self.hbond = self.params.get("hbond", default=False)
        if self.hbond:
            self.networkinterface = NetworkInterface(self.iface, local,
                                                     if_type='Bond')
        else:
            self.networkinterface = NetworkInterface(self.iface, local)
        try:
            self.networkinterface.add_ipaddr(self.ipaddr, self.netmask)
            self.networkinterface.save(self.ipaddr, self.netmask)
        except Exception:
            self.networkinterface.save(self.ipaddr, self.netmask)
        self.networkinterface.bring_up()

        self.session = Session(self.peer, user=self.user,
                               password=self.peer_password)
        if not self.session.connect():
            self.cancel("failed connecting to peer")
        self.count = self.params.get("count", default="500000")
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
                self.cancel("%s package is need to test" % pkg)
        if self.peer == "":
            self.cancel("peer ip should specify in input")
        cmd = "ip addr show  | grep %s" % self.peer
        output = self.session.cmd(cmd)
        result = ""
        result = result.join(output.stdout.decode("utf-8"))
        self.peerif = result.split()[-1]
        if self.peerif == "":
            self.cancel("unable to get peer interface")
        cmd = "ip -f inet -o addr show %s | awk '{print $4}' | cut -d / -f1"\
              % self.iface
        self.local_ip = process.system_output(cmd, shell=True).strip()
        if self.local_ip == "":
            self.cancel("unable to get local ip")

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
            self.fail("unable to set all multicast option to test interface")
        cmd = "ip route add 224.0.0.0/4 dev %s" % self.peerif
        output = self.session.cmd(cmd)
        if not output.exit_status == 0:
            self.fail("Unable to add route for Peer interface")
        cmd = "timeout 600 ping -I %s 224.0.0.1 -c %s -f" % (self.peerif,
                                                             self.count)
        output = self.session.cmd(cmd)
        if not output.exit_status == 0:
            self.fail("multicast test failed")

    def tearDown(self):
        '''
        delete multicast route and turn off multicast option
        '''
        if self.iface:
            cmd = "ip route del 224.0.0.0/4"
            output = self.session.cmd(cmd)
            if not output.exit_status == 0:
                self.log.info("Unable to delete multicast route added for peer")
            cmd = "echo 1 > /proc/sys/net/ipv4/icmp_echo_ignore_broadcasts"
            if process.system(cmd, shell=True, verbose=True,
                              ignore_status=True) != 0:
                self.log.info("unable to unset all multicast option")
            cmd = "ip link set %s allmulticast off" % self.iface
            if process.system(cmd, shell=True, verbose=True,
                              ignore_status=True) != 0:
                self.log.info("unable to unset all multicast option")
            self.networkinterface.remove_ipaddr(self.ipaddr, self.netmask)
            try:
                self.networkinterface.restore_from_backup()
            except Exception:
                self.networkinterface.remove_cfg_file()
                self.log.info("backup file not available, could not restore file.")
            self.session.quit()
