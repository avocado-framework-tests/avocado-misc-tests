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

'''
ping pong test
ibv_ud_pingpong
ibv_uc_pingpong
ibv_rc_pingpong
ibv_srq_pingpong
'''


import time
import netifaces
from avocado import Test
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils import process
from avocado.utils import distro
from avocado.utils.ssh import Session
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.network.hosts import LocalHost, RemoteHost


class PingPong(Test):
    '''
    ibv_ud_pingpong test
    ibv_ud_pingpong tool should be installed
    '''

    def setUp(self):
        '''
        To check and install dependencies for the test
        '''
        local = LocalHost()
        interfaces = netifaces.interfaces()
        device = self.params.get("interface", default=None)
        if device in interfaces:
            self.iface = device
        elif local.validate_mac_addr(device) and device in local.get_all_hwaddr():
            self.iface = local.get_interface_by_hwaddr(device).name
        else:
            self.iface = None
            self.cancel("%s interface is not available" % device)

        self.flag = self.params.get("ext_flag", default="0")
        self.peer_ip = self.params.get("peer_ip", default="")
        self.peer_user = self.params.get("peer_user", default="root")
        self.peer_password = self.params.get("peer_password", '*',
                                             default="None")
        self.ipaddr = self.params.get("host_ip", default="")
        self.netmask = self.params.get("netmask", default="")
        if self.iface[0:2] == 'ib':
            self.networkinterface = NetworkInterface(self.iface, local,
                                                     if_type='Infiniband')
            try:
                self.networkinterface.add_ipaddr(self.ipaddr, self.netmask)
                self.networkinterface.save(self.ipaddr, self.netmask)
            except Exception:
                self.networkinterface.save(self.ipaddr, self.netmask)
        else:
            self.networkinterface = NetworkInterface(self.iface, local)
            try:
                self.networkinterface.add_ipaddr(self.ipaddr, self.netmask)
                self.networkinterface.save(self.ipaddr, self.netmask)
            except Exception:
                self.networkinterface.save(self.ipaddr, self.netmask)
        self.networkinterface.bring_up()
        self.session = Session(self.peer_ip, user=self.peer_user,
                               password=self.peer_password)
        if self.iface not in interfaces:
            self.cancel("%s interface is not available" % self.iface)
        if self.peer_ip == "":
            self.cancel("%s peer machine is not available" % self.peer_ip)
        self.ca_name = self.params.get("CA_NAME", default="mlx4_0")
        self.gid = int(self.params.get("GID_NUM", default="0"))
        self.port = int(self.params.get("PORT_NUM", default="1"))
        self.peer_ca = self.params.get("PEERCA", default="mlx4_0")
        self.peer_gid = int(self.params.get("PEERGID", default="0"))
        self.peer_port = int(self.params.get("PEERPORT", default="1"))
        self.tmo = self.params.get("TIMEOUT", default="120")
        self.mtu = self.params.get("mtu", default=1500)
        self.remotehost = RemoteHost(self.peer_ip, self.peer_user,
                                     password=self.peer_password)
        self.peer_interface = self.remotehost.get_interface_by_ipaddr(
            self.peer_ip).name
        self.peer_networkinterface = NetworkInterface(self.peer_interface,
                                                      self.remotehost)
        smm = SoftwareManager()
        detected_distro = distro.detect()
        pkgs = []
        if detected_distro.name == "Ubuntu":
            pkgs.extend(["ibverbs-utils", 'openssh-client'])
            cmd = "service ufw stop"
        # FIXME: "redhat" as the distro name for RHEL is deprecated
        # on Avocado versions >= 50.0.  This is a temporary compatibility
        # enabler for older runners, but should be removed soon
        elif detected_distro.name in ['rhel', 'fedora', 'redhat']:
            pkgs.extend(["libibverbs", 'openssh-clients'])
            cmd = "systemctl stop firewalld"
        elif detected_distro.name == "SuSE":
            pkgs.append('openssh')
            if detected_distro.version >= 15:
                cmd = "systemctl stop firewalld"
            else:
                cmd = "rcSuSEfirewall2 stop"
        elif detected_distro.name == "centos":
            pkgs.extend(['libibverbs', 'openssh-clients'])
            cmd = "service iptables stop"
        else:
            self.cancel("Distro not supported")
        if process.system(cmd, ignore_status=True, shell=True) != 0:
            self.cancel("Unable to disable firewall")
        output = self.session.cmd(cmd)
        if not output.exit_status == 0:
            self.cancel("Unable to disable firewall on peer")
        for pkg in pkgs:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel("%s package is need to test" % pkg)
        if process.system("ibstat", shell=True, ignore_status=True) != 0:
            self.cancel("infiniband adaptors not available")
        self.tool_name = self.params.get("tool")
        self.log.info("test with %s", self.tool_name)
        self.peer_iface = ''
        cmd = "ip addr show"
        output = self.session.cmd(cmd)
        for line in output.stdout.decode("utf-8").splitlines():
            if self.peer_ip in line:
                self.peer_iface = line.split()[-1]
                break

    def pingpong_exec(self, arg1, arg2, arg3):
        '''
        ping pong exec function
        '''
        test = arg2
        logs = "> /tmp/ib_log 2>&1 &"
        if test == "basic":
            test = ""
        cmd = "timeout %s %s -d %s -g %d -i %d %s %s %s" \
            % (self.tmo, arg1, self.peer_ca, self.peer_gid, self.peer_port,
               test, arg3, logs)
        output = self.session.cmd(cmd)
        if not output.exit_status == 0:
            self.fail("ssh failed to remote machine")
        time.sleep(2)
        self.log.info("client data for %s(%s)", arg1, arg2)
        self.log.info("%s -d %s -g %d %s -i %d %s %s", arg1, self.ca_name,
                      self.gid, self.peer_ip, self.port, test, arg3)
        tmp = "timeout %s %s -d %s -g %d -i %d %s %s %s" \
            % (self.tmo, arg1, self.ca_name, self.gid, self.port, self.peer_ip,
               test, arg3)
        if process.system(tmp, shell=True, ignore_status=True) != 0:
            self.fail("test failed")
        self.log.info("server data for %s(%s)", arg1, arg2)
        self.log.info("%s -d %s -g %d -i %d %s %s", arg1, self.peer_ca,
                      self.peer_gid, self.peer_port, test, arg3)
        cmd = "timeout %s cat /tmp/ib_log && rm -rf /tmp/ib_log" \
            % self.tmo
        output = self.session.cmd(cmd)
        if not output.exit_status == 0:
            self.fail("test failed")

    def test_ib_pingpong(self):
        '''
        test options are mandatory
        ext test options are depends upon user
        '''
        # change MTU to 9000 for non-IB tests
        if "ib" not in self.iface and self.tool_name == "ibv_ud_pingpong":
            self.mtu = "9000"
        if self.peer_networkinterface.set_mtu(self.mtu) is not None:
            self.fail("Failed to set mtu in peer")
        if self.networkinterface.set_mtu(self.mtu) is not None:
            self.fail("Failed to set mtu in host")
        time.sleep(10)
        val1 = ""
        val2 = ""
        test_op = self.params.get("test_opt", default="").split(",")
        for val in test_op:
            try:
                val1, val2 = val.split()
            except ValueError:
                pass
            self.pingpong_exec(self.tool_name, val1, val2)
        ext_test_op = self.params.get("ext_test_opt", default="").split(",")
        if self.flag == "1":
            for val in ext_test_op:
                self.pingpong_exec(self.tool_name, val, "")
        else:
            self.log.info("Extended test option skipped")

    def tearDown(self):
        if self.iface:
            if self.networkinterface.set_mtu('1500') is not None:
                self.fail("Failed to set mtu in host")
            if self.peer_networkinterface.set_mtu('1500') is not None:
                self.fail("Failed to set mtu in peer")
            self.remotehost.remote_session.quit()
