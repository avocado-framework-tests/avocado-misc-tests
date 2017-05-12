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

"""
ping to peer machine with 5 ICMP packets
Secure Shell (SSH) is a cryptographic network protocol for operating
network services securely over an unsecured network
Scp allows files to be copied to, from, or between different hosts.
"""

import time
import hashlib
import netifaces
from avocado import main
from avocado import Test
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import process
from avocado.utils import distro


class ScpTest(Test):
    '''
    check the ssh into peer
    check the scp into peer
    '''

    def setUp(self):
        '''
        To check and install dependencies for the test
        '''
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
                self.skip("%s package is need to test" % pkg)
        interfaces = netifaces.interfaces()
        self.iface = self.params.get("interface")
        if self.iface not in interfaces:
            self.skip("%s interface is not available" % self.iface)
        self.peer = self.params.get("peer_ip", default="")
        if self.peer == "":
            self.skip("peer ip should specify in input")
        self.user = self.params.get("user_name", default="root")

    def test_ping(self):
        '''
        ping to peer machine
        '''
        cmd = "ping -I %s %s -c 5" % (self.iface, self.peer)
        if process.system(cmd, shell=True, verbose=True,
                          ignore_status=True) != 0:
            self.fail("ping test failed")

    def test_scpandssh(self):
        '''
        check scp and ssh
        '''
        cmd = "ssh %s@%s \"echo hi\"" % (self.user, self.peer)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("unable to ssh into peer machine")
        process.run("dd if=/dev/zero of=/tmp/tempfile bs=1024000000 count=1",
                    shell=True)
        time.sleep(15)
        md_val1 = hashlib.md5(open('/tmp/tempfile', 'rb').read()).hexdigest()
        time.sleep(5)
        cmd = "timeout 600 scp /tmp/tempfile %s@%s:/tmp" %\
              (self.user, self.peer)
        ret = process.system(cmd, shell=True, verbose=True, ignore_status=True)
        time.sleep(15)
        if ret != 0:
            self.fail("unable to copy into peer machine")
        cmd = "timeout 600 scp %s@%s:/tmp/tempfile /tmp" %\
              (self.user, self.peer)
        ret = process.system(cmd, shell=True, verbose=True, ignore_status=True)
        time.sleep(15)
        if ret != 0:
            self.fail("unable to copy from peer machine")
        md_val2 = hashlib.md5(open('/tmp/tempfile', 'rb').read()).hexdigest()
        time.sleep(5)
        if md_val1 != md_val2:
            self.fail("Test Failed")

    def tearDown(self):
        '''
        remove data both peer and host machine
        '''
        self.log.info('removing data')
        cmd = "rm /tmp/tempfile"
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.log.info("unable to remove data from client")
        msg = "rm /tmp/tempfile"
        cmd = "ssh %s@%s \"%s\"" % (self.user, self.peer, msg)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.log.info("unable to remove data from peer")


if __name__ == "__main__":
    main()
