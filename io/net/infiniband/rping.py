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
Rping test
"""

import time
import netifaces
from netifaces import AF_INET
from avocado import Test
from avocado import main
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import process


class Rping(Test):
    """
    rping Test.
    """
    def setUp(self):
        """
        Setup and install dependencies for the test.
        """
        self.test_name = "rping"
        self.basic = self.params.get("basic_option", default="None")
        self.ext = self.params.get("ext_option", default="None")
        self.flag = self.params.get("ext_flag", default="0")
        if self.basic == "None" and self.ext == "None":
            self.skip("No option given")
        if self.flag == "1" and self.ext != "None":
            self.option = self.ext
        else:
            self.option = self.basic
        if process.system("ibstat", shell=True, ignore_status=True) != 0:
            self.skip("MOFED is not installed. Skipping")
        depends = ["openssh-clients", "iputils*"]
        smm = SoftwareManager()
        for package in depends:
            if not smm.check_installed(package):
                if not smm.install(package):
                    self.skip("Not able to install %s" % package)
        interfaces = netifaces.interfaces()
        self.iface = self.params.get("Iface", default="")
        self.peer_ip = self.params.get("PEERIP", default="")
        self.ipv6_peer = self.params.get("IPV6_PEER", default="")
        if self.iface not in interfaces:
            self.skip("%s interface is not available" % self.iface)
        if self.peer_ip == "":
            self.skip("%s peer machine is not available" % self.peer_ip)
        self.timeout = "2m"
        self.local_ip = netifaces.ifaddresses(self.iface)[AF_INET][0]['addr']
        self.option = self.option.replace("PEERIP", self.peer_ip)
        self.option = self.option.replace("LOCALIP", self.local_ip)
        self.option = self.option.replace("IPV6_PEER", self.ipv6_peer)
        self.option_list = self.option.split(",")

    def test(self):
        """
        Test rping
        """
        self.log.info(self.test_name)
        self.log.info("Client data - %s(%s)" % (self.test_name, self.option))
        logs = "> /tmp/ib_log 2>&1 &"
        cmd = "ssh %s timeout %s %s -s %s -c %s %s %s" \
            % (self.peer_ip, self.timeout, self.test_name,
               self.option_list[0], self.option_list[1], self.option, logs)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("SSH connection (or) Server command failed")
        time.sleep(5)
        cmd = "timeout %s %s -c %s" \
            % (self.timeout, self.test_name, self.option_list[1])
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("Client command failed")
        time.sleep(5)
        self.log.info("Server data - %s(%s)" % (self.test_name, self.option))
        cmd = "ssh %s timeout %s cat /tmp/ib_log; rm -rf /tmp/ib_log" \
            % (self.peer_ip, self.timeout)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("Server output retrieval failed")


if __name__ == "__main__":
    main()
