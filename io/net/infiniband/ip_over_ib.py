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
# IPoIB can run over two infiniband transports
# Unreliable Datagram (UD) mode or Connected mode (CM)


import os
import time
import netifaces
from avocado import Test
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import build
from avocado.utils import archive
from avocado.utils import process
from avocado.utils import git


class ip_over_ib(Test):
    '''
    Ip Over IB Test
    IPoIB can run over two infiniband transports,
    Unreliable Datagram (UD) mode or Connected mode (CM)
    '''
    def setUp(self):
        '''
        To check and install dependencies for the test
        '''
        sm = SoftwareManager()
        depends = ["openssh-clients", "gcc"]
        for pkg in depends:
            if not sm.check_installed(pkg) and not sm.install(pkg):
                self.skip("%s package is need to test" % pkg)
        interfaces = netifaces.interfaces()
        self.IF = self.params.get("Iface", default="")
        self.PEER_IP = self.params.get("PEERIP", default="")
        if self.IF not in interfaces:
            self.skip("%s interface is not available" % self.IF)
        if self.PEER_IP == "":
            self.skip("%s peer machine is not available" % self.PEER_IP)
        self.to = self.params.get("timeout", default="600")
        self.IPERF_RUN = self.params.get("IPERF_RUN", default="0")
        self.NETSERVER_RUN = self.params.get("NETSERVER_RUN", default="0")
        self.iper = os.path.join(self.srcdir, 'perf')
        self.netperf = os.path.join(self.srcdir, 'netperf')
        tarball = self.fetch_asset('ftp://ftp.netperf.org/netperf/'
                                   'netperf-2.7.0.tar.bz2')
        archive.extract(tarball, self.netperf)
        version = os.path.basename(tarball.split('.tar.')[0])
        self.neperf = os.path.join(self.netperf, version)
        tmp = "scp -r %s root@%s:" % (self.neperf, self.PEER_IP)
        if process.system(tmp, shell=True, ignore_status=True) != 0:
            self.skip("unable to copy the netperf into peer machine")
        tmp = "cd /root/netperf-2.7.0;./configure ppc64le;make"
        cmd = "ssh %s \"%s\"" % (self.PEER_IP, tmp)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("test failed because command failed in peer machine")
        time.sleep(5)
        os.chdir(self.neperf)
        process.system('./configure ppc64le', shell=True)
        build.make(self.neperf)
        self.perf = os.path.join(self.neperf, 'src')
        time.sleep(5)
        git.get_repo('https://github.com/esnet/iperf.git',
                     destination_dir=self.iper)
        tmp = "scp -r %s root@%s:" % (self.iper, self.PEER_IP)
        if process.system(tmp, shell=True, ignore_status=True) != 0:
            self.skip("unable to copy the iperf into peer machine")
        tmp = "cd /root/perf;./configure;make"
        cmd = "ssh %s \"%s\"" % (self.PEER_IP, tmp)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("test failed because command failed in peer machine")
        time.sleep(5)
        process.system('./configure', shell=True)
        build.make(self.iper)
        self.iperf = os.path.join(self.iper, 'src')

    def interface_setup(self, arg1):
        '''
        Bringup IPoIB Interface
        '''
        self.log.info("Bringup Interface %s with %s mode" % (self.IF, arg1))
        cmd = "timeout %s ifconfig %s down" % (self.to, self.IF)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("interface setup test failed")
        time.sleep(2)
        logs = "> /sys/class/net/%s/mode" % self.IF
        cmd = "timeout %s echo %s %s" % (self.to, arg1, logs)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("interface setup test failed")
        time.sleep(2)
        cmd = "timeout %s cat /sys/class/net/%s/mode" % (self.to, self.IF)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("interface setup test failed")
        cmd = "timeout %s ifconfig %s up" % (self.to, self.IF)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("interface setup test failed")

    def netperf_test(self, arg1, arg2):
        '''
        netperf test
        '''
        if self.NETSERVER_RUN == 0:
            tmp = "chmod 777 /root/netperf-2.7.0/src"
            cmd = "ssh %s \"%s\"" % (self.PEER_IP, tmp)
            if process.system(cmd, shell=True, ignore_status=True) != 0:
                self.fail("test failed because netserver not available")
            cmd = "ssh %s \"/root/netperf-2.7.0/src/netserver\"" % self.PEER_IP
            if process.system(cmd, shell=True, ignore_status=True) != 0:
                self.fail("test failed because netserver not available")
            else:
                self.NETSERVER_RUN = 1
        time.sleep(5)
        msg = "timeout %s %s -H %s %s" % (
              self.to, self.perf+'/netperf', self.PEER_IP, arg2)
        if process.system(msg, shell=True, ignore_status=True) != 0:
            self.fail("test failed because netperf not working")
        if arg1 == "datagram" and arg2 != "":
            msg = "timeout %s %s -H %s -t UDP_STREAM -- -m 63000" % \
                  (self.to, self.perf+'/netperf', self.PEER_IP)
            if process.system(msg, shell=True, ignore_status=True) != 0:
                self.fail("test failed because netperf not working")
        else:
            msg = "timeout %s %s -H %s -t UDP_STREAM %s" % \
                  (self.to, self.perf+'/netperf', self.PEER_IP, arg2)
            if process.system(msg, shell=True, ignore_status=True) != 0:
                self.fail("test failed because netperf not working")
        msg = "timeout %s %s -H %s -t TCP_RR %s" % \
              (self.to, self.perf+'/netperf', self.PEER_IP, arg2)
        if process.system(msg, shell=True, ignore_status=True) != 0:
            self.fail("test failed because netperf not working")
        msg = "timeout %s %s -H %s -t UDP_RR %s" % \
              (self.to, self.perf+'/netperf', self.PEER_IP, arg2)
        if process.system(msg, shell=True, ignore_status=True) != 0:
            self.fail("test failed because netperf not working")

    def iperf_test(self):
        '''
        iperf test
        '''
        if self.IPERF_RUN == 0:
            logs = "> /tmp/ib_log 2>&1 &"
            tmp = "chmod 777 /root/perf/src/iperf3"
            cmd = "ssh %s \"%s\"" % (self.PEER_IP, tmp)
            if process.system(cmd, shell=True, ignore_status=True) != 0:
                self.fail("test failed because connect to peer sys failed")
            tmp = "/root/perf/src/iperf3 -s %s" % logs
            cmd = "ssh %s \"%s\"" % (self.PEER_IP, tmp)
            if process.system(cmd, shell=True, ignore_status=True) != 0:
                self.fail("test failed because connect to peer sys failed")
            else:
                self.IPERF_RUN = 1
        time.sleep(5)
        cmd = "timeout %s %s -c %s -P 20 -n 8192" % \
              (self.to, self.iperf+'/iperf3', self.PEER_IP)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("test failed because iperf not working")
        self.log.info("server data for iperf")
        msg = "timeout %s cat /tmp/ib_log" % self.to
        cmd = "ssh %s \"%s\"" % (self.PEER_IP, msg)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("test failed because connect to peer sys failed")

    def test_ip_over_ib(self):
        '''
        IPoIB Tests
        '''
        test_name = self.params.get("tool")
        self.log.info("test with %s" % (test_name))
        if "ib" in self.IF:
            self.interface_setup(test_name)
            self.netperf_test(test_name, "")
            self.netperf_test(test_name, "-- -m 65000")
            self.iperf_test()
        else:
            self.log.info("Not applicable for the interface %s" % self.IF)

    def tearDown(self):
        '''
        removing the data in peer machine
        '''
        msg = "pkill iperf3; pkill netserver; \
               rm -rf /tmp/ib_log;rm -rf /root/perf rm -rf /root/netperf-2.7.0"
        cmd = "ssh %s \"%s\"" % (self.PEER_IP, msg)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("test failed because peer sys not connected")


if __name__ == "__main__":
    main()
