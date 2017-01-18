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
# Author: Prudhvi Miryala <mprudhvi@linux.vnet.ibm.com>
# Co-Author: Narasimhan V <sim@linux.vnet.ibm.com>

"""
Netperf is a benchmark that can be used to measure the performance of
many different types of networking. It provides tests for both
unidirectional throughput, and end-to-end latency.
"""


import os
import time
import netifaces
from avocado import main
from avocado import Test
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import distro
from avocado.utils import build
from avocado.utils import archive
from avocado.utils import process


class Netperf(Test):
    """
    Netperf Test
    """
    def setUp(self):
        """
        To check and install dependencies for the test
        """
        smm = SoftwareManager()
        detected_distro = distro.detect()
        pkgs = ['gcc']
        if detected_distro.name == "Ubuntu":
            pkgs.append('openssh-client')
        else:
            pkgs.append('openssh-clients')
        for pkg in pkgs:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.skip("%s package is need to test" % pkg)
        interfaces = netifaces.interfaces()
        self.iface = self.params.get("Iface", default="")
        self.peer_ip = self.params.get("PEERIP", default="")
        if self.iface not in interfaces:
            self.skip("%s interface is not available" % self.iface)
        if self.peer_ip == "":
            self.skip("%s peer machine is not available" % self.peer_ip)
        self.timeout = self.params.get("timeout", default="600")
        self.netperf_run = self.params.get("NETSERVER_RUN", default="0")
        self.netperf = os.path.join(self.srcdir, 'netperf')
        print self.netperf
        tarball = self.fetch_asset('ftp://ftp.netperf.org/netperf/'
                                   'netperf-2.7.0.tar.bz2', expire='7d')
        archive.extract(tarball, self.netperf)
        self.version = os.path.basename(tarball.split('.tar.')[0])
        print self.version
        self.neperf = os.path.join(self.netperf, self.version)
        print self.neperf
        tmp = "scp -r %s root@%s:" % (self.neperf, self.peer_ip)
        if process.system(tmp, shell=True, ignore_status=True) != 0:
            self.skip("unable to copy the netperf into peer machine")
        tmp = "cd /root/%s;./configure ppc64le;make" % self.version
        cmd = "ssh %s \"%s\"" % (self.peer_ip, tmp)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("test failed because command failed in peer machine")
        time.sleep(5)
        os.chdir(self.neperf)
        process.system('./configure ppc64le', shell=True)
        build.make(self.neperf)
        self.perf = os.path.join(self.neperf, 'src', 'netperf')

    def test(self):
        """
        netperf test
        """
        if self.netperf_run == 0:
            tmp = "chmod 777 /root/%s/src" % self.version
            cmd = "ssh %s \"%s\"" % (self.peer_ip, tmp)
            if process.system(cmd, shell=True, ignore_status=True) != 0:
                self.fail("test failed because netserver not available")
            cmd = "ssh %s \"/root/%s/src/netserver\"" % (self.peer_ip,
                                                         self.version)
            if process.system(cmd, shell=True, ignore_status=True) != 0:
                self.fail("test failed because netserver not available")
            else:
                self.netperf_run = 1
        time.sleep(5)
        msg = "timeout %s %s -H %s" % (
            self.timeout, self.perf, self.peer_ip)
        if process.system(msg, shell=True, ignore_status=True) != 0:
            self.fail("test failed because netperf not working")
        msg = "timeout %s %s -H %s -t UDP_STREAM -- -m 63000" % \
              (self.timeout, self.perf, self.peer_ip)
        if process.system(msg, shell=True, ignore_status=True) != 0:
            self.fail("test failed because netperf not working")
        msg = "timeout %s %s -H %s -t TCP_RR" % \
              (self.timeout, self.perf, self.peer_ip)
        if process.system(msg, shell=True, ignore_status=True) != 0:
            self.fail("test failed because netperf not working")
        msg = "timeout %s %s -H %s -t UDP_RR" % \
              (self.timeout, self.perf, self.peer_ip)
        if process.system(msg, shell=True, ignore_status=True) != 0:
            self.fail("test failed because netperf not working")

    def tearDown(self):
        """
        removing the data in peer machine
        """
        msg = "pkill netserver; rm -rf /root/%s" % self.version
        cmd = "ssh %s \"%s\"" % (self.peer_ip, msg)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("test failed because peer sys not connected")


if __name__ == "__main__":
    main()
