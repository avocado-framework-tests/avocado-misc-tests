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

import os
import hashlib
from avocado import Test
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils import process
from avocado.utils import distro
from avocado.utils import genio
from avocado.utils.ssh import Session
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.network.hosts import LocalHost, RemoteHost
from avocado.utils import wait


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
        interfaces = os.listdir('/sys/class/net')
        local = LocalHost()
        device = self.params.get("interface")
        if device in interfaces:
            self.interface = device
        elif local.validate_mac_addr(device) and device in local.get_all_hwaddr():
            self.interface = local.get_interface_by_hwaddr(device).name
        else:
            self.interface = None
            self.cancel("Please check the network device")
        self.ipaddr = self.params.get("host_ip", default="")
        self.netmask = self.params.get("netmask", default="")
        self.ip_config = self.params.get("ip_config", default=True)
        self.hbond = self.params.get("hbond", default=False)
        if self.hbond:
            self.networkinterface = NetworkInterface(
                self.interface, local, if_type='Bond')
        else:
            self.networkinterface = NetworkInterface(self.interface, local)
        if self.ip_config:
            try:
                self.networkinterface.add_ipaddr(self.ipaddr, self.netmask)
                self.networkinterface.save(self.ipaddr, self.netmask)
            except Exception:
                self.networkinterface.save(self.ipaddr, self.netmask)
            self.networkinterface.bring_up()
        if not wait.wait_for(self.networkinterface.is_link_up, timeout=120):
            self.fail("Link up of interface is taking longer than 120 seconds")
        self.peer = self.params.get("peer_ip")
        if not self.peer:
            self.cancel("No peer provided")
        self.mtu = self.params.get("mtu", default=1500)
        self.peer_public_ip = self.params.get("peer_public_ip", default="")
        self.peer_user = self.params.get("peer_user", default="root")
        self.peer_password = self.params.get("peer_password", '*',
                                             default=None)
        if 'scp' or 'ssh' in str(self.name.name):
            self.session = Session(self.peer, user=self.peer_user,
                                   password=self.peer_password)
            self.session.cleanup_master()
            if not self.session.connect():
                self.cancel("failed connecting to peer")
        self.remotehost = RemoteHost(self.peer, self.peer_user,
                                     password=self.peer_password)
        self.peer_interface = self.remotehost.get_interface_by_ipaddr(
            self.peer).name
        self.peer_networkinterface = NetworkInterface(self.peer_interface,
                                                      self.remotehost)
        self.remotehost_public = RemoteHost(self.peer_public_ip, self.peer_user,
                                            password=self.peer_password)
        self.peer_public_networkinterface = NetworkInterface(self.peer_interface,
                                                             self.remotehost_public)
        self.mtu = self.params.get("mtu", default=1500)
        self.count = self.params.get("ping_count", default=500000)
        self.mtu_set()
        if self.networkinterface.ping_check(self.peer, count=5) is not None:
            self.cancel("No connection to peer")

    def mtu_set(self):
        '''
        set mtu size
        '''
        if self.peer_networkinterface.set_mtu(self.mtu) is not None:
            self.cancel("Failed to set mtu in peer")
        if self.networkinterface.set_mtu(self.mtu) is not None:
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
        path = '/sys/class/net/%s/device/uevent' % self.interface
        if os.path.exists(path):
            output = open(path, 'r').read()
            for line in output.splitlines():
                if "OF_NAME" in line:
                    if 'vnic' in line.split('=')[-1]:
                        self.cancel("Unsupported on vNIC")
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
        if self.networkinterface.ping_check(self.peer, count=10) is not None:
            self.fail("ping test failed")

    def test_floodping(self):
        '''
        Flood ping to peer machine
        '''
        if self.networkinterface.ping_check(self.peer, self.count,
                                            options='-f') is not None:
            self.fail("flood ping test failed")

    def test_ipv6_ping(self):
        '''
        Ping test with ipv6 address
        '''
        try:
            self.networkinterface.get_ipaddrs(version=6)
        except Exception:
            self.cancel("IPV6 address is not set for host interface")
        try:
            peer_ipv6 = self.peer_networkinterface.get_ipaddrs(version=6)
            if not peer_ipv6[0]:
                self.cancel("IPV6 address is not set for peer interface")
        except Exception:
            self.cancel(
                "Test failing while getting IPV6 address for peer interface")
        if self.networkinterface.ping_check(peer_ipv6[0], count=10) is not None:
            self.fail("IPV6 ping test failed")

    def test_ssh(self):
        '''
        Test ssh
        '''
        cmd = "echo hi"
        output = self.session.cmd(cmd)
        if not output.exit_status == 0:
            self.fail("unable to ssh into peer machine")

    def test_scp(self):
        '''
        Test scp
        '''
        process.run("dd if=/dev/zero of=/tmp/tempfile bs=1024000000 count=1",
                    shell=True)
        md_val1 = hashlib.md5(open('/tmp/tempfile', 'rb').read()).hexdigest()
        destination = "%s:/tmp" % self.peer
        output = self.session.copy_files('/tmp/tempfile', destination)
        if not output:
            self.fail("unable to copy into peer machine")

        source = "%s:/tmp/tempfile" % self.peer
        output = self.session.copy_files(source, '/tmp')
        if not output:
            self.fail("unable to copy from peer machine")

        md_val2 = hashlib.md5(open('/tmp/tempfile', 'rb').read()).hexdigest()
        if md_val1 != md_val2:
            self.fail("Test Failed")

    def test_jumbo_frame(self):
        '''
        Test jumbo frames
        '''
        if self.networkinterface.ping_check(self.peer, count=30,
                                            options='-i 0.1 -s %d'
                                            % (int(self.mtu) - 28)) is not None:
            self.fail("jumbo frame test failed")

    def test_statistics(self):
        '''
        Test Statistics
        '''
        rx_file = "/sys/class/net/%s/statistics/rx_packets" % self.interface
        tx_file = "/sys/class/net/%s/statistics/tx_packets" % self.interface
        rx_before = genio.read_file(rx_file)
        tx_before = genio.read_file(tx_file)
        self.networkinterface.ping_check(self.peer, self.count, options='-f')
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
        try:
            self.peer_networkinterface.set_mtu('1500')
        except Exception:
            self.peer_public_networkinterface.set_mtu('1500')
        if self.networkinterface.set_mtu('1500') is not None:
            self.cancel("Failed to set mtu in host")

    def offload_toggle_test(self, ro_type, ro_type_full):
        '''
        Check to toggle the LRO / GRO / GSO / TSO
        '''
        for state in ["off", "on"]:
            if not self.offload_state_change(ro_type,
                                             ro_type_full, state):
                self.fail("%s %s failed" % (ro_type, state))
            if self.networkinterface.ping_check(self.peer, self.count,
                                                options='-f') is not None:
                self.fail("ping failed in %s %s" % (ro_type, state))

    def offload_state_change(self, ro_type, ro_type_full, state):
        '''
        Change the state of LRO / GRO / GSO / TSO to specified state
        '''
        cmd = "ethtool -K %s %s %s" % (self.interface, ro_type, state)
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
        cmd = "ethtool -k %s" % self.interface
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
        cmd = "ip link set %s promisc on" % self.interface
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("failed to enable promisc mode")
        self.networkinterface.ping_check(self.peer, self.count, options='-f')
        cmd = "ip link set %s promisc off" % self.interface
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("failed to disable promisc mode")
        self.networkinterface.ping_check(self.peer, count=5)

    def tearDown(self):
        '''
        Remove the files created
        '''
        self.mtu_set_back()
        if 'scp' in str(self.name.name):
            process.run("rm -rf /tmp/tempfile")
            cmd = "rm -rf /tmp/tempfile"
            self.session.cmd(cmd)
        if self.ip_config:
            self.networkinterface.remove_ipaddr(self.ipaddr, self.netmask)
            try:
                self.networkinterface.restore_from_backup()
            except Exception:
                self.networkinterface.remove_cfg_file()
                self.log.info(
                    "backup file not available, could not restore file.")
        self.remotehost.remote_session.quit()
        if hasattr(self, 'remotehost_public'):
            self.remotehost_public.remote_session.quit()
        if 'scp' or 'ssh' in str(self.name.name):
            self.session.quit()
