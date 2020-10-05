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
# Author: Narasimhan V <sim@linux.vnet.ibm.com>
# Author: Manvanthara B Puttashankar <manvanth@linux.vnet.ibm.com>

"""
Ucmatose test
"""

import time
import netifaces
from netifaces import AF_INET
from avocado import Test
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import process, distro
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.network.hosts import LocalHost, RemoteHost
from avocado.utils.ssh import Session


class Ucmatose(Test):
    """
    Ucmatose Test.
    """

    def setUp(self):
        """
        Setup and install dependencies for the test.
        """
        self.test_name = "ucmatose"
        self.basic = self.params.get("basic_option", default="None")
        self.ext = self.params.get("ext_option", default="None")
        self.flag = self.params.get("ext_flag", default="0")
        if self.basic == "None" and self.ext == "None":
            self.cancel("No option given")
        if self.flag == "1" and self.ext != "None":
            self.option = self.ext
        else:
            self.option = self.basic
        if process.system("ibstat", shell=True, ignore_status=True) != 0:
            self.cancel("MOFED is not installed. Skipping")
        detected_distro = distro.detect()
        pkgs = []
        smm = SoftwareManager()
        if detected_distro.name == "Ubuntu":
            pkgs.extend(["openssh-client", "iputils-ping"])
        elif detected_distro.name == "SuSE":
            pkgs.extend(["openssh", "iputils"])
        else:
            pkgs.extend(["openssh-clients", "iputils"])
        for pkg in pkgs:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel("Not able to install %s" % pkg)
        interfaces = netifaces.interfaces()
        self.flag = self.params.get("ext_flag", default="0")
        self.iface = self.params.get("interface", default="")
        self.peer_ip = self.params.get("peer_ip", default="")
        self.peer_user = self.params.get("peer_user", default="root")
        self.peer_password = self.params.get("peer_password", '*',
                                             default="None")
        self.ipaddr = self.params.get("host_ip", default="")
        self.netmask = self.params.get("netmask", default="")
        local = LocalHost()
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
        self.timeout = "2m"
        self.local_ip = netifaces.ifaddresses(self.iface)[AF_INET][0]['addr']
        self.mtu = self.params.get("mtu", default=1500)
        self.remotehost = RemoteHost(self.peer_ip, self.peer_user,
                                     password=self.peer_password)
        self.peer_interface = self.remotehost.get_interface_by_ipaddr(self.peer_ip).name
        self.peer_networkinterface = NetworkInterface(self.peer_interface,
                                                      self.remotehost)

        if detected_distro.name == "Ubuntu":
            cmd = "service ufw stop"
        # FIXME: "redhat" as the distro name for RHEL is deprecated
        # on Avocado versions >= 50.0.  This is a temporary compatibility
        # enabler for older runners, but should be removed soon
        elif detected_distro.name in ['rhel', 'fedora', 'redhat']:
            cmd = "systemctl stop firewalld"
        elif detected_distro.name == "SuSE":
            if detected_distro.version == 15:
                cmd = "systemctl stop firewalld"
            else:
                cmd = "rcSuSEfirewall2 stop"
        elif detected_distro.name == "centos":
            cmd = "service iptables stop"
        else:
            self.cancel("Distro not supported")
        if process.system(cmd, ignore_status=True, shell=True) != 0:
            self.cancel("Unable to disable firewall")
        output = self.session.cmd(cmd)
        if not output.exit_status == 0:
            self.cancel("Unable to disable firewall on peer")

    def test(self):
        """
        Test ucmatose
        """
        if self.peer_networkinterface.set_mtu(self.mtu) is not None:
            self.fail("Failed to set mtu in peer")
        if self.networkinterface.set_mtu(self.mtu) is not None:
            self.fail("Failed to set mtu in host")
        self.log.info(self.test_name)
        logs = "> /tmp/ib_log 2>&1 &"
        cmd = " timeout %s %s -b %s %s %s" % (self.timeout, self.test_name,
                                              self.peer_ip, self.option, logs)
        output = self.session.cmd(cmd)
        if not output.exit_status == 0:
            self.fail("SSH connection (or) Server command failed")
        time.sleep(5)
        self.log.info("Client data - %s(%s)" % (self.test_name, self.option))
        cmd = "timeout %s %s -s %s -b %s %s" \
            % (self.timeout, self.test_name, self.peer_ip,
               self.local_ip, self.option)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("Client command failed")
        time.sleep(5)
        self.log.info("Server data - %s(%s)" % (self.test_name, self.option))
        cmd = "timeout %s cat /tmp/ib_log && rm -rf /tmp/ib_log" \
            % (self.timeout)
        output = self.session.cmd(cmd)
        if not output.exit_status == 0:
            self.fail("Server output retrieval failed")

    def tearDown(self):
        """
        unset ip
        """
        if self.networkinterface.set_mtu('1500') is not None:
            self.fail("Failed to set mtu in host")
        if self.peer_networkinterface.set_mtu('1500') is not None:
            self.fail("Failed to set mtu in peer")
        self.remotehost.remote_session.quit()
