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

"""
check the statistics of interface, test big ping
test lro and gro and interface
"""

import time
import netifaces

from avocado import main
from avocado import Test
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import process
from avocado.utils import distro


class NetDataTest(Test):
    '''
    check the statistics of interface, test big ping
    test lro and gro and interface
    '''
    def setUp(self):
        '''
            To check and install dependencies for the test
        '''
        smm = SoftwareManager()
        pkgs = ["ethtool", "net-tools"]
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
        interface = self.params.get("interface")
        if interface not in interfaces:
            self.skip("%s interface is not available" % interface)
        mtu_list = self.params.get("size_val", default=1500)
        self.mtu_list = mtu_list.split()
        self.interface = interface
        self.peer = self.params.get("peer_ip")
        self.eth = "ethtool %s | grep 'Link detected:'" % self.interface
        self.eth_state = process.system_output(self.eth, shell=True)

    def teststatistics(self):
        '''
         check statistics of interface
        '''
        self.log.info("Statistic incrementer")
        rx_cmd = "cat /sys/class/net/%s/statistics/rx_packets" % self.interface
        tx_cmd = "cat /sys/class/net/%s/statistics/tx_packets" % self.interface
        rx_stat = int(process.system_output(rx_cmd, shell=True))
        tx_stat = int(process.system_output(tx_cmd, shell=True))
        # flooding ICMP packets to peer system through interface
        tmp = "ping -c 20 -f %s -I %s" % (self.peer, self.interface)
        process.system(tmp, shell=True)
        time.sleep(3)
        rx_stat_after = int(process.system_output(rx_cmd, shell=True))
        tx_stat_after = int(process.system_output(tx_cmd, shell=True))
        # check interface working or not
        if (rx_stat >= rx_stat_after) and (tx_stat >= tx_stat_after):
            self.fail("stat not incremented.wrong with IF %s" % self.interface)

    def testbigping(self):
        '''
        check with different maximum transfer unit values
        '''
        msg = "ip addr show  | grep %s | grep -oE '[^ ]+$'" % self.peer
        cmd = "ssh %s %s" % (self.peer, msg)
        errors = []
        self.peer_interface = process.system_output(cmd, shell=True).strip()
        mtuval = process.system_output("ip link show %s" % self.interface,
                                       shell=True).split()[4]
        for mtu in self.mtu_list:
            self.log.info("trying with mtu %s" % (mtu))
            # ping the peer machine with different maximum transfers unit sizes
            # and finally set maximum transfer unit size to 1500 Bytes
            msg = "ssh %s \"ifconfig %s mtu %s\"" % (self.peer,
                                                     self.peer_interface, mtu)
            process.system(msg, shell=True)
            con_msg = "ifconfig %s mtu %s" % (self.interface, mtu)
            process.system(con_msg, shell=True)
            time.sleep(10)
            mtu = int(mtu) - 28
            cmd_ping = "ping -i 0.1 -c 2 -s %s %s" % (mtu, self.peer)
            ret = process.system(cmd_ping, shell=True, ignore_status=True)
            if ret != 0:
                errors.append(str(int(mtu) + 28))
            con_msg = "ifconfig %s mtu %s" % (self.interface, mtuval)
            if process.system(con_msg, shell=True, ignore_status=True):
                self.log.debug("setting original mtu value in host failed")
            msg = "ssh %s \"ifconfig %s mtu %s\"" % (self.peer,
                                                     self.peer_interface,
                                                     mtuval)
            if process.system(msg, shell=True, ignore_status=True):
                self.log.debug("setting original mtu value in peer failed")
            time.sleep(10)

        if errors:
            self.fail("bigping test failed for %s" % " ".join(errors))

    def testgro(self):
        '''
        check gro is enabled or not
        '''
        self.log.info("Generic Receive Offload")
        tmp_on = "ethtool -K %s gro on" % self.interface
        tmp_off = "ethtool -K %s gro off" % self.interface
        ret = process.system(tmp_on, shell=True)
        if ret == 0:
            ret = process.system("ping -c 1 %s" % self.peer, shell=True)
            if ret != 0:
                self.fail("gro test failed")
            process.system(tmp_off, shell=True)
            ret = process.system("ping -c 1 %s" % self.peer, shell=True)
            if ret != 0:
                self.fail("gro test failed")
        else:
            self.fail("gro test failed")

    def testlro(self):
        '''
        check lro is enabled or not
        '''
        self.log.info("Largest Receive Offload")
        tmp = "ethtool -K %s lro off" % self.interface
        if process.system(tmp, shell=True) != 0:
            self.fail("LRO Test failed")
        ret = process.system("ping -c 1 %s" % self.peer, shell=True)
        if ret != 0:
            self.fail("lro test failed")
            msg = "ethtool -K %s lro on" % self.interface
            if process.system(msg, shell=True) != 0:
                self.fail("LRO Test failed")
                ret = process.system("ping -c 1 %s" % self.peer, shell=True)
                if ret != 0:
                    self.fail("lro test failed")

    def interface_wait(self, cmd):
        '''
         Waits for the interface to come up
        '''
        for i in range(0, 600, 5):
            if 'UP' or 'yes' in\
             process.system_output(cmd, shell=True, ignore_status=True):
                self.log.info("%s is up" % self.interface)
                return True
            time.sleep(5)
        return False

    def testinterface(self):
        '''
         test the interface
        '''
        if_down = "ifconfig %s down" % self.interface
        if_up = "ifconfig %s up" % self.interface
        # down the interface
        process.system(if_down, shell=True)
        # check the status of interface through ethtool
        ret = process.system_output(self.eth, shell=True)
        if 'yes' in ret:
            self.fail("interface test failed")
        # check the status of interface through ip link show
        ip_link = "ip link show %s | head -1" % self.interface
        ret = process.system_output(ip_link, shell=True)
        if 'UP' in ret:
            self.fail("interface test failed")
        # up the interface
        process.system(if_up, shell=True, ignore_status=True)
        self.log.info('Checking for interface status using ip link show')
        if not self.interface_wait(ip_link):
            self.fail("interface test failed")
        # check the status of interface through ethtool
        self.log.info('Checking for interface status using Ethtool')
        if not self.interface_wait(self.eth):
            self.fail("interface test failed")

    def tearDown(self):
        '''
         set the intial state
        '''
        self.log.info('setting intial state')
        if 'yes' in self.eth_state:
            process.system("ifconfig %s up" % self.interface, shell=True)
        else:
            process.system("ifconfig %s down" % self.interface, shell=True)


if __name__ == "__main__":
    main()
