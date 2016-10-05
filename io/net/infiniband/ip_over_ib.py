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
# Ip Over IB test


import os
import time
import netifaces
from avocado import Test
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import build
from avocado.utils import git
from avocado.utils import process
from avocado.utils import distro


class ip_over_ib(Test):
    '''
    Ip Over IB Test
    '''
    def setUp(self):
        '''
        To check and install dependencies for the test
        '''
        sm = SoftwareManager()
        detected_distro = distro.detect()
        depends = ["openssh-clients", "git"]
        for pkg in depends:
            if not sm.check_installed(pkg) and not sm.install(pkg):
                self.skip("%s package is need to test" % package)
        interfaces = netifaces.interfaces()
        self.IF = self.params.get("Iface", default="")
        self.PEER_IP = self.params.get("PEERIP", default="")
        if self.IF not in interfaces:
            self.skip("%s interface is not available" % self.IF)
        if self.PEER_IP == "":
            self.skip("%s peer machine is not available" % self.PEER_IP)
        self.to = self.params.get("timeout", default="120")
        self.IPERF_RUN = self.params.get("IPERF_RUN", default="0")
        self.NETSERVER_RUN = self.params.get("NETSERVER_RUN", default="0")
        # source: git clone git://git.linux.ibm.com/power-io-fvt/eio_src.git
        git.get_repo('git://git.linux.ibm.com/power-io-fvt/eio_src.git',
                     destination_dir=self.srcdir)
        self.perf = os.path.join(self.srcdir, 'third-party/bin')
        time.sleep(5)

    def interface_setup(self, arg1):
        '''
        Bringup IPoIB Interface
        '''
        self.log.info("Bringup Interface %s with %s mode" % (self.IF, arg1))
        self.log.info("ifconfig %s down" % self.IF)
        cmd = "timeout %s ifconfig %s down" % (self.to, self.IF)
        if process.system(cmd, shell=True) != 0:
            self.fail("interface setup test failed")
        time.sleep(2)
        logs = "> /sys/class/net/%s/mode" % self.IF
        self.log.info("%s %s" % (arg1, logs))
        cmd = "timeout %s echo %s %s" % (self.to, arg1, logs)
        if process.system(cmd, shell=True) != 0:
            self.fail("interface setup test failed")
        time.sleep(2)
        self.log.info("cat /sys/class/net/%s/mode" % self.IF)
        cmd = "timeout %s cat /sys/class/net/%s/mode" % (self.to, self.IF)
        if process.system(cmd, shell=True) != 0:
            self.fail("interface setup test failed")
        self.log.info("ifconfig %s up" % self.IF)
        cmd = "timeout %s ifconfig %s up" % (self.to, self.IF)
        if process.system(cmd, shell=True) != 0:
            self.fail("interface setup test failed")

    def netperf_test(self, arg1, arg2):
        '''
        netperf test
        '''
        if self.NETSERVER_RUN == 0:
            tmp = "timeout %s scp %s root@%s:" \
                   % (self.to, self.perf+'/netserver', self.PEER_IP)
            if process.system(tmp, shell=True) != 0:
                self.fail("test failed because connect to peer sys failed")
            tmp = "chmod 777 /root/netserver"
            cmd = "ssh %s %s" % (self.PEER_IP, tmp)
            if process.system(cmd, shell=True) != 0:
                self.fail("test failed because netserver not available")
            cmd = "ssh %s /root/netserver" % self.PEER_IP
            if process.system(cmd, shell=True) != 0:
                self.fail("test failed because netserver not available")
            else:
                self.NETSERVER_RUN = 1
        self.log.info("%s -H %s %s" % (
                      self.perf+'/netperf', self.PEER_IP, arg2))
        msg = "timeout %s %s -H %s %s" % (
              self.to, self.perf+'/netperf', self.PEER_IP, arg2)
        if process.system(msg, shell=True) != 0:
            self.fail("test failed because netperf not working")
        if arg1 == "datagram" and arg2 != "":
            self.log.info("%s -H %s -t UDP_STREAM -- -m 63000" % (
                          self.perf+'/netperf', self.PEER_IP))
            msg = "timeout %s %s -H %s -t UDP_STREAM -- -m 63000" % \
                  (self.to, self.perf+'/netperf', self.PEER_IP)
            if process.system(msg, shell=True) != 0:
                self.fail("test failed because netperf not working")
        else:
            self.log.info("%s -H %s -t UDP_STREAM %s" % (
                          self.perf+'/netperf', self.PEER_IP, arg2))
            msg = "timeout %s %s -H %s -t UDP_STREAM %s" % \
                  (self.to, self.perf+'/netperf', self.PEER_IP, arg2)
            if process.system(msg, shell=True) != 0:
                self.fail("test failed because netperf not working")
        self.log.info("%s -H %s -t TCP_RR %s" % (
                      self.perf+'/netperf', self.PEER_IP, arg2))
        msg = "timeout %s %s -H %s -t TCP_RR %s" % \
              (self.to, self.perf+'/netperf', self.PEER_IP, arg2)
        if process.system(msg, shell=True) != 0:
            self.fail("test failed because netperf not working")
        self.log.info("%s -H %s -t UDP_RR %s" % (
                      self.perf+'/netperf', self.PEER_IP, arg2))
        msg = "timeout %s %s -H %s -t UDP_RR %s" % \
              (self.to, self.perf+'/netperf', self.PEER_IP, arg2)
        if process.system(msg, shell=True) != 0:
            self.fail("test failed because netperf not working")

    def iperf_tets(self, arg1):
        '''
        iperf test
        '''
        if self.IPERF_RUN == 0:
            tmp = "timeout %s scp %s root@%s:" % \
                   (self.to, self.perf+'/iperf', self.PEER_IP)
            if process.system(tmp, shell=True) != 0:
                self.fail("test failed because connect to peer sys failed")
            logs = "> /tmp/ib_log 2>&1 &"
            tmp = "chmod 777 /root/iperf"
            cmd = "ssh %s %s" % (self.PEER_IP, tmp)
            if process.system(cmd, shell=True) != 0:
                self.fail("test failed because connect to peer sys failed")
            tmp = "/root/iperf -s %s" % logs
            cmd = "ssh %s %s" % (self.PEER_IP, tmp)
            if process.system(cmd, shell=True, ignore_status=True) != 0:
                self.fail("test failed because connect to peer sys failed")
            else:
                self.IPERF_RUN = 1
        self.log.info("%s -d -c %s -P 20 -n 8192" % (
                      self.perf+'/iperf', self.PEER_IP))
        cmd = "timeout %s %s -d -c %s -P 20 -n 8192" % \
              (self.to, self.perf+'/iperf', self.PEER_IP)
        if process.system(cmd, shell=True) != 0:
            self.fail("test failed because iperf not working")
        self.log.info("server data for iperf")
        msg = "timeout %s cat /tmp/ib_log" % self.to
        cmd = "ssh %s %s" % (self.PEER_IP, msg)
        if process.system(cmd, shell=True) != 0:
            self.fail("test failed because connect to peer sys failed")

    def test_ip_over_ib(self):
        '''
        IPoIB Tests"
        '''
        test_name = self.params.get("tool")
        self.log.info("test with %s" % (test_name))
        if "ib" in self.IF:
            self.interface_setup(test_name)
            self.netperf_test(test_name, "")
            self.netperf_test(test_name, "-- -m 65000")
            self.iperf_tets(test_name)
            msg = "killall -9 iperf netserver; \
                   rm -rf /tmp/ib_log /root/iperf /root/netserver"
            cmd = "ssh %s %s" % (self.PEER_IP, msg)
            if process.system(cmd, shell=True) != 0:
                self.fail("test failed because peer sys not connected")
        else:
            self.log.info("Not applicable for the interface %s" % self.IF)


if __name__ == "__main__":
    main()
