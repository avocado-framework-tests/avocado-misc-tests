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
# Author: Harsha Thyagaraja <harshkid@linux.vnet.ibm.com>

import os
from avocado import Test
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils import process
from avocado.utils import distro
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.network.hosts import LocalHost, RemoteHost


class MultiportStress(Test):
    '''
    To perform IO stress on multiple ports on a NIC adapter
    '''

    def setUp(self):
        '''
        To check and install dependencies for the test
        '''
        self.host_interfaces = []
        interfaces = os.listdir('/sys/class/net')
        self.local = LocalHost()
        devices = self.params.get("interfaces", default=None)
        for device in devices.split(" "):
            if device in interfaces:
                self.host_interfaces.append(device)
            elif self.local.validate_mac_addr(device) and device in self.local.get_all_hwaddr():
                self.host_interfaces.append(self.local.get_interface_by_hwaddr(device).name)
            else:
                self.host_interfaces = None
                self.cancel("Please check the network device")
        smm = SoftwareManager()
        if distro.detect().name == 'Ubuntu':
            pkg = 'iputils-ping'
        else:
            pkg = 'iputils'
        if not smm.check_installed(pkg) and not smm.install(pkg):
            self.cancel("Package %s is needed to test" % pkg)
        self.peer_ips = self.params.get("peer_ips",
                                        default="").split(" ")
        self.peer_public_ip = self.params.get("peer_public_ip", default="")
        self.count = self.params.get("count", default="1000")
        self.ipaddr = self.params.get("host_ips", default="").split(" ")
        self.netmask = self.params.get("netmask", default="")
        for ipaddr, interface in zip(self.ipaddr, self.host_interfaces):
            networkinterface = NetworkInterface(interface, self.local)
            try:
                networkinterface.add_ipaddr(ipaddr, self.netmask)
                networkinterface.save(ipaddr, self.netmask)
            except Exception:
                networkinterface.save(ipaddr, self.netmask)
            networkinterface.bring_up()
        self.peer_user = self.params.get("peer_user", default="root")
        self.peer_password = self.params.get("peer_password", '*',
                                             default="None")
        self.mtu = self.params.get("mtu", default=1500)
        self.remotehost = RemoteHost(self.peer_ips[0], self.peer_user,
                                     password=self.peer_password)
        self.remotehost_public = RemoteHost(self.peer_public_ip,
                                            self.peer_user,
                                            password=self.peer_password)
        for peer_ip in self.peer_ips:
            peer_interface = self.remotehost.get_interface_by_ipaddr(
                peer_ip).name
            peer_networkinterface = NetworkInterface(peer_interface,
                                                     self.remotehost)
            if peer_networkinterface.set_mtu(self.mtu) is not None:
                self.cancel("Failed to set mtu in peer")
        for host_interface in self.host_interfaces:
            self.networkinterface = NetworkInterface(
                host_interface, self.local)
            if self.networkinterface.set_mtu(self.mtu) is not None:
                self.cancel("Failed to set mtu in host")

    def multiport_ping(self, ping_option):
        '''
        Ping to multiple peers parallelly
        '''
        parallel_procs = []
        for host, peer in zip(self.host_interfaces, self.peer_ips):
            self.log.info('Starting Ping test')
            cmd = "ping -I %s %s -c %s %s" % (host, peer, self.count,
                                              ping_option)
            obj = process.SubProcess(cmd, verbose=False, shell=True)
            obj.start()
            parallel_procs.append(obj)
        self.log.info('Wait for background processes to finish'
                      ' before proceeding')
        for proc in parallel_procs:
            proc.wait()
        errors = []
        for proc in parallel_procs:
            out_buf = proc.get_stdout()
            out_buf += proc.get_stderr()
            for val in out_buf.decode("utf-8").splitlines():
                if 'packet loss' in val and ', 0% packet loss,' not in val:
                    errors.append(out_buf)
                    break
        if errors:
            self.fail(b"\n".join(errors))

    def test_multiport_ping(self):
        self.multiport_ping('')

    def test_multiport_floodping(self):
        self.multiport_ping('-f')

    def tearDown(self):
        '''
        unset ip for host interface
        '''
        if self.host_interfaces:
            for host_interface in self.host_interfaces:
                networkinterface = NetworkInterface(host_interface, self.local)
                if networkinterface.set_mtu("1500") is not None:
                    self.cancel("Failed to set mtu in host")
            for peer_ip in self.peer_ips:
                peer_interface = self.remotehost.get_interface_by_ipaddr(
                    peer_ip).name
                try:
                    peer_networkinterface = NetworkInterface(peer_interface,
                                                             self.remotehost)
                    peer_networkinterface.set_mtu("1500")
                except Exception:
                    peer_public_networkinterface = NetworkInterface(peer_interface,
                                                                    self.remotehost_public)
                    peer_public_networkinterface.set_mtu("1500")
            for ipaddr, interface in zip(self.ipaddr, self.host_interfaces):
                networkinterface = NetworkInterface(interface, self.local)
                networkinterface.remove_ipaddr(ipaddr, self.netmask)
                try:
                    networkinterface.restore_from_backup()
                except Exception:
                    self.log.info(
                        "backup file not available, could not restore file.")
                self.remotehost.remote_session.quit()
                if hasattr(self, 'remotehost_public'):
                    self.remotehost_public.remote_session.quit()
