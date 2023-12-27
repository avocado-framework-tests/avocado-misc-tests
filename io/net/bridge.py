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


import os
from avocado import Test
from avocado.utils import distro
from avocado.utils import process
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.network.hosts import LocalHost, RemoteHost


class Bridging(Test):
    '''
    Test bridge interface
    '''

    def check_failure(self, cmd):
        if process.system(cmd, sudo=True, shell=True, ignore_status=True):
            self.fail("Command %s failed" % cmd)

    def setUp(self):
        self.host_interfaces = []
        local = LocalHost()
        interfaces = os.listdir('/sys/class/net')
        devices = self.params.get("interfaces", default="").split(" ")
        for device in devices:
            if device in interfaces:
                self.host_interfaces.append(device)
            elif local.validate_mac_addr(device) and device in local.get_all_hwaddr():
                self.host_interfaces.append(local.get_interface_by_hwaddr(device).name)
            else:
                self.cancel("Please check the network device")
        if self.host_interfaces[0:2] == 'ib':
            self.cancel("Network Bridge is not supported for IB")

        self.peer_ip = self.params.get("peer_ip", default=None)
        if not self.peer_ip:
            self.cancel("User should specify peer IP")
        self.ipaddr = self.params.get("host_ip", default="")
        self.netmask = self.params.get("netmask", default="")
        self.peer_interface = self.params.get("peer_interface", default="")
        self.peer_public_ip = self.params.get("peer_public_ip", default="")
        self.user = self.params.get("user_name", default="root")
        self.password = self.params.get("peer_password", '*',
                                        default="None")
        self.bridge_interface = self.params.get("bridge_interface",
                                                default="br0")
        self.networkinterface = NetworkInterface(self.bridge_interface, local,
                                                 if_type="Bridge")

    def test_bridge_create(self):
        '''
        Set up the ethernet bridge configuration in the linux kernel
        '''
        detected_distro = distro.detect()
        net_path = 'network-scripts'
        if detected_distro.name == "SuSE":
            net_path = 'network'
        if os.path.exists('/etc/sysconfig/%s/ifcfg-%s' % (net_path, self.bridge_interface)):
            self.networkinterface.remove_cfg_file()
            self.check_failure('ip link del %s' % self.bridge_interface)
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
        for host_interface in self.host_interfaces:
            self.check_failure('ip link set %s master %s'
                               % (host_interface, self.bridge_interface))
            self.check_failure('ip addr flush dev %s' % host_interface)

    def test_bridge_run(self):
        '''
        run bridge test
        '''
        try:
            self.networkinterface.add_ipaddr(self.ipaddr, self.netmask)
            self.networkinterface.save(self.ipaddr, self.netmask)
        except Exception:
            self.networkinterface.save(self.ipaddr, self.netmask)
        self.networkinterface.bring_up()
        self.remotehost = RemoteHost(self.peer_public_ip, self.user,
                                     password=self.password)
        peer_networkinterface = NetworkInterface(self.peer_interface,
                                                 self.remotehost)
        try:
            peer_networkinterface.add_ipaddr(self.peer_ip, self.netmask)
            peer_networkinterface.save(self.peer_ip, self.netmask)
        except Exception:
            peer_networkinterface.save(self.peer_ip, self.netmask)
        peer_networkinterface.bring_up()
        if self.networkinterface.ping_check(self.peer_ip, count=5) is not None:
            self.fail('Ping using bridge failed')
        self.networkinterface.remove_ipaddr(self.ipaddr, self.netmask)
        peer_networkinterface.remove_ipaddr(self.peer_ip, self.netmask)

    def test_bridge_delete(self):
        '''
        Set to original state
        '''
        self.check_failure('ip link del dev %s' % self.bridge_interface)
        try:
            self.networkinterface.restore_from_backup()
        except Exception:
            self.networkinterface.remove_cfg_file()
