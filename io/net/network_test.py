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
# Author: Prudhvi Miryala <mprudhvi@linux.vnet.ibm.com>
# Author: Narasimhan V <sim@linux.vnet.ibm.com>
#

"""
check the statistics of interface, test big ping
test lro and gro and interface
"""

import hashlib
import netifaces
from avocado import main
from avocado import Test
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import process
from avocado.utils import distro
from avocado.utils import genio
from avocado.utils.configure_network import PeerInfo
from avocado.utils import configure_network
from avocado.utils import wait
from avocado.utils import ssh


class NetworkTest(Test):
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
            pkgs.extend(["openssh-client", "iputils-ping"])
        elif detected_distro.name == "SuSE":
            pkgs.extend(["openssh", "iputils"])
        else:
            pkgs.extend(["openssh-clients", "iputils"])
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
        if not wait.wait_for(configure_network.is_interface_link_up,
                             timeout=120, args=[self.iface]):
            self.fail("Link up of interface is taking longer than 120 seconds")
        self.peer = self.params.get("peer_ip")
        if not self.peer:
            self.cancel("No peer provided")
        self.mtu = self.params.get("mtu", default=1500)
        self.peer_user = self.params.get("peer_user", default="root")
        self.peer_password = self.params.get("peer_password", '*',
                                             default=None)
        self.peerinfo = PeerInfo(self.peer, peer_user=self.peer_user,
                                 peer_password=self.peer_password)
        self.peer_interface = self.peerinfo.get_peer_interface(self.peer)
        self.mtu = self.params.get("mtu", default=1500)
        self.mtu_set()
        if not wait.wait_for(configure_network.is_interface_link_up,
                             timeout=120, args=[self.iface]):
            self.fail("Link up of interface is taking longer than 120 seconds")
        if not configure_network.ping_check(self.iface, self.peer, "5"):
            self.cancel("No connection to peer")

    def mtu_set(self):
        '''
        set mtu size
        '''
        if not self.peerinfo.set_mtu_peer(self.peer_interface, self.mtu):
            self.cancel("Failed to set mtu in peer")
        if not configure_network.set_mtu_host(self.iface, self.mtu):
            self.cancel("Failed to set mtu in host")

    def test_gro(self):
        '''
        Test GRO
        '''
        ro_type = "gro"
        ro_type_full = "generic-receive-offload"
        if not self.offload_state(ro_type_full):
            self.fail("Could not get state of %s" % ro_type)
        if self.offload_state(ro_type_full) == 'fixed':
            self.fail("Can not change the state of %s" % ro_type)
        self.offload_toggle_test(ro_type, ro_type_full)

    def test_gso(self):
        '''
        Test GSO
        '''
        ro_type = "gso"
        ro_type_full = "generic-segmentation-offload"
        if not self.offload_state(ro_type_full):
            self.fail("Could not get state of %s" % ro_type)
        if self.offload_state(ro_type_full) == 'fixed':
            self.fail("Can not change the state of %s" % ro_type)
        self.offload_toggle_test(ro_type, ro_type_full)

    def test_lro(self):
        '''
        Test LRO
        '''
        ro_type = "lro"
        ro_type_full = "large-receive-offload"
        if not self.offload_state(ro_type_full):
            self.fail("Could not get state of %s" % ro_type)
        if self.offload_state(ro_type_full) == 'fixed':
            self.fail("Can not change the state of %s" % ro_type)
        self.offload_toggle_test(ro_type, ro_type_full)

    def test_tso(self):
        '''
        Test TSO
        '''
        ro_type = "tso"
        ro_type_full = "tcp-segmentation-offload"
        if not self.offload_state(ro_type_full):
            self.fail("Could not get state of %s" % ro_type)
        if self.offload_state(ro_type_full) == 'fixed':
            self.fail("Can not change the state of %s" % ro_type)
        self.offload_toggle_test(ro_type, ro_type_full)

    def test_ping(self):
        '''
        ping to peer machine
        '''
        if not configure_network.ping_check(self.iface, self.peer, '10'):
            self.fail("ping test failed")

    def test_floodping(self):
        '''
        Flood ping to peer machine
        '''
        if not configure_network.ping_check(self.iface, self.peer,
                                            '500000', flood=True):
            self.fail("flood ping test failed")

    def test_ssh(self):
        '''
        Test ssh
        '''
        cmd = "ssh %s \"echo hi\"" % self.peer
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("unable to ssh into peer machine")

    def test_scp(self):
        '''
        Test scp
        '''
        process.run("dd if=/dev/zero of=/tmp/tempfile bs=1024000000 count=1",
                    shell=True)
        md_val1 = hashlib.md5(open('/tmp/tempfile', 'rb').read()).hexdigest()

        cmd = "timeout 600 scp /tmp/tempfile %s:/tmp" % self.peer
        ret = process.system(cmd, shell=True, verbose=True, ignore_status=True)
        if ret != 0:
            self.fail("unable to copy into peer machine")

        cmd = "timeout 600 scp %s:/tmp/tempfile /tmp" % self.peer
        ret = process.system(cmd, shell=True, verbose=True, ignore_status=True)
        if ret != 0:
            self.fail("unable to copy from peer machine")

        md_val2 = hashlib.md5(open('/tmp/tempfile', 'rb').read()).hexdigest()
        if md_val1 != md_val2:
            self.fail("Test Failed")

    def test_jumbo_frame(self):
        '''
        Test jumbo frames
        '''
        if not configure_network.ping_check(self.iface, self.peer, "30",
                                            option='-i 0.1 -s %d'
                                            % (int(self.mtu) - 28)):
            self.fail("jumbo frame test failed")

    def test_statistics(self):
        '''
        Test Statistics
        '''
        rx_file = "/sys/class/net/%s/statistics/rx_packets" % self.iface
        tx_file = "/sys/class/net/%s/statistics/tx_packets" % self.iface
        rx_before = genio.read_file(rx_file)
        tx_before = genio.read_file(tx_file)
        configure_network.ping_check(self.iface, self.peer, "500000",
                                     flood=True)
        rx_after = genio.read_file(rx_file)
        tx_after = genio.read_file(tx_file)
        if (rx_after <= rx_before) or (tx_after <= tx_before):
            self.log.debug("Before\nrx: %s tx: %s" % (rx_before, tx_before))
            self.log.debug("After\nrx: %s tx: %s" % (rx_after, tx_after))
            self.fail("Statistics not incremented properly")

    def mtu_set_back(self):
        '''
        Test set mtu back to 1500
        '''
        if not configure_network.set_mtu_host(self.iface, '1500'):
            self.cancel("Failed to set mtu in host")
        if not self.peerinfo.set_mtu_peer(self.peer_interface, '1500'):
            self.cancel("Failed to set mtu in peer")

    def offload_toggle_test(self, ro_type, ro_type_full):
        '''
        Check to toggle the LRO / GRO / GSO / TSO
        '''
        for state in ["off", "on"]:
            if not self.offload_state_change(ro_type,
                                             ro_type_full, state):
                self.fail("%s %s failed" % (ro_type, state))
            if not configure_network.ping_check(self.iface, self.peer,
                                                "500000", flood=True):
                self.fail("ping failed in %s %s" % (ro_type, state))

    def offload_state_change(self, ro_type, ro_type_full, state):
        '''
        Change the state of LRO / GRO / GSO / TSO to specified state
        '''
        cmd = "ethtool -K %s %s %s" % (self.iface, ro_type, state)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            return False
        if self.offload_state(ro_type_full) != state:
            return False
        return True

    def offload_state(self, ro_type_full):
        '''
        Return the state of LRO / GRO / GSO / TSO.
        If the state can not be changed, we return 'fixed'.
        If any other error, we return ''.
        '''
        cmd = "ethtool -k %s" % self.iface
        output = process.system_output(cmd, shell=True,
                                       ignore_status=True).decode("utf-8")
        for line in output.splitlines():
            if ro_type_full in line:
                if 'fixed' in line.split()[-1]:
                    return 'fixed'
                return line.split()[-1]
        return ''

    def test_promisc(self):
        '''
        promisc mode testing
        '''
        cmd = "ip link set %s promisc on" % self.iface
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("failed to enable promisc mode")
        configure_network.ping_check(self.iface, self.peer,
                                     "100000", flood=True)
        cmd = "ip link set %s promisc off" % self.iface
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("failed to disable promisc mode")
        configure_network.ping_check(self.iface, self.peer, "5")

    def test_ping6(self):
        '''
        IPV6 ping test to peer machine
        '''
        with ssh.Session(self.peer, user='root',
                         password=self.peer_password) as session:
            cmd = "ip addr show %s" % self.peer_interface
            result = session.cmd(cmd)
            if result.exit_status == 0:
                result_ip = result.stdout_text
                try:
                    for line in result_ip.splitlines():
                        if "inet6" in line:
                            ipv6 = line.split()[1].split('/')[0]
                except UnboundLocalError:
                    if ipv6 == "":
                        self.error("unable to get IPV6 of peer")
                        return False
        if not self.networkinterface.ping_check(self.iface, ipv6, '10'):
            self.fail("ping test fail")

    def tearDown(self):
        '''
        Remove the files created
        '''
        self.mtu_set_back()
        if 'scp' in str(self.name.name):
            process.run("rm -rf /tmp/tempfile")
            cmd = "timeout 600 ssh %s \" rm -rf /tmp/tempfile\"" % self.peer
            process.system(cmd, shell=True, verbose=True, ignore_status=True)
        configure_network.unset_ip(self.iface)


if __name__ == "__main__":
    main()
