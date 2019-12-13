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

"""
Tcpdump Test.
"""

import os
import netifaces
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils import distro
from avocado.utils import archive
from avocado.utils import build
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import configure_network
from avocado.utils.configure_network import PeerInfo


class TcpdumpTest(Test):
    """
    Test the tcpdump for specified interface.
    """

    def setUp(self):
        """
        Set up.
        """
        self.iface = self.params.get("interface", default="")
        self.count = self.params.get("count", default="500")
        self.peer_ip = self.params.get("peer_ip", default="")
        self.drop = self.params.get("drop_accepted", default="10")
        self.host_ip = self.params.get("host_ip", default="")
        self.option = self.params.get("option", default='')
        # Check if interface exists in the system
        interfaces = netifaces.interfaces()
        if self.iface not in interfaces:
            self.cancel("%s interface is not available" % self.iface)
        if not self.peer_ip:
            self.cancel("peer ip should specify in input")
        self.ipaddr = self.params.get("host_ip", default="")
        self.netmask = self.params.get("netmask", default="")
        configure_network.set_ip(self.ipaddr, self.netmask, self.iface)
        self.peer_user = self.params.get("peer_user", default="root")
        self.peer_password = self.params.get("peer_password", '*',
                                             default="None")
        self.mtu = self.params.get("mtu", default=1500)
        self.peerinfo = PeerInfo(self.peer_ip, peer_user=self.peer_user,
                                 peer_password=self.peer_password)
        self.peer_interface = self.peerinfo.get_peer_interface(self.peer_ip)
        if not self.peerinfo.set_mtu_peer(self.peer_interface, self.mtu):
            self.cancel("Failed to set mtu in peer")
        if not configure_network.set_mtu_host(self.iface, self.mtu):
            self.cancel("Failed to set mtu in host")

        # Install needed packages
        smm = SoftwareManager()
        detected_distro = distro.detect()
        pkgs = ['tcpdump', 'flex', 'bison', 'gcc', 'gcc-c++', 'nmap']
        for pkg in pkgs:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel("%s package Can not install" % pkg)
        if detected_distro.name == "SuSE":
            self.nmap = os.path.join(self.teststmpdir, 'nmap')
            nmap_download = self.params.get("nmap_download", default="https:"
                                            "//nmap.org/dist/"
                                            "nmap-7.80.tar.bz2")
            tarball = self.fetch_asset(nmap_download)
            self.version = os.path.basename(tarball.split('.tar')[0])
            self.n_map = os.path.join(self.nmap, self.version)
            archive.extract(tarball, self.nmap)
            os.chdir(self.n_map)
            process.system('./configure ppc64le', shell=True)
            build.make(self.n_map)
            process.system('./nping/nping -h', shell=True)

    def test(self):
        """
        Performs the tcpdump test.
        """
        cmd = "ping -I %s %s -c %s" % (self.iface, self.peer_ip, self.count)
        output_file = os.path.join(self.outputdir, 'tcpdump')
        if self.option in ('tcp', 'udp', 'icmp'):
            obj = self.nping(self.option)
            obj.start()
        else:
            obj = process.SubProcess(cmd, verbose=False, shell=True)
            obj.start()
        cmd = "tcpdump -i %s -n -c %s" % (self.iface, self.count)
        if self.option in ('host', 'src'):
            cmd = "%s %s %s" % (cmd, self.option, self.host_ip)
        elif self.option == "dst":
            cmd = "%s %s %s" % (cmd, self.option, self.peer_ip)
        else:
            cmd = "%s %s" % (cmd, self.option)
        cmd = "%s -w '%s'" % (cmd, output_file)
        for line in process.run(cmd, shell=True,
                                ignore_status=True).stderr.decode("utf-8") \
                                                   .splitlines():
            if "packets dropped by interface" in line:
                self.log.info(line)
                if int(line[0]) >= (int(self.drop) * int(self.count) / 100):
                    self.fail("%s, more than %s percent" % (line, self.drop))
        obj.stop()

    def nping(self, param):
        """
        perform nping
        """
        cmd = "./nping/nping --%s %s -c %s" % (param, self.peer_ip, self.count)
        return process.SubProcess(cmd, verbose=False, shell=True)

    def tearDown(self):
        '''
        unset ip for host interface
        '''
        if not configure_network.set_mtu_host(self.iface, '1500'):
            self.cancel("Failed to set mtu in host")
        if not self.peerinfo.set_mtu_peer(self.peer_interface, '1500'):
            self.cancel("Failed to set mtu in peer")
        configure_network.unset_ip(self.iface)


if __name__ == "__main__":
    main()
