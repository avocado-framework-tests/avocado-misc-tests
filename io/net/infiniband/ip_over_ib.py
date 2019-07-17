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
Ip Over IB test
IPoIB can run over two infiniband transports
Unreliable Datagram (UD) mode or Connected mode (CM)
'''


import os
import time
import netifaces
from avocado import main
from avocado import Test
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import build
from avocado.utils import archive
from avocado.utils import process, distro


class IPOverIB(Test):
    '''
    Ip Over IB Test
    IPoIB can run over two infiniband transports,
    Unreliable Datagram (UD) mode or Connected mode (CM)
    '''

    def setUp(self):
        '''
        To check and install dependencies for the test
        '''
        smm = SoftwareManager()
        detected_distro = distro.detect()
        pkgs = ["gcc"]
        if detected_distro.name == "Ubuntu":
            pkgs.append('openssh-client')
        elif detected_distro.name == "SuSE":
            pkgs.append('openssh')
        else:
            pkgs.append('openssh-clients')
        for pkg in pkgs:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel("%s package is need to test" % pkg)
        interfaces = netifaces.interfaces()
        self.iface = self.params.get("interface", default="")
        self.peer_ip = self.params.get("peer_ip", default="")
        if self.iface not in interfaces:
            self.cancel("%s interface is not available" % self.iface)
        if self.peer_ip == "":
            self.cancel("%s peer machine is not available" % self.peer_ip)
        self.tmo = self.params.get("TIMEOUT", default="600")
        self.iperf_run = self.params.get("IPERF_RUN", default="0")
        self.netserver_run = self.params.get("NETSERVER_RUN", default="0")
        self.iper = os.path.join(self.teststmpdir, 'iperf')
        self.netperf = os.path.join(self.teststmpdir, 'netperf')
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
        if process.system("%s && ssh %s %s" % (cmd, self.peer_ip, cmd),
                          ignore_status=True, shell=True) != 0:
            self.cancel("Unable to disable firewall")

        tarball = self.fetch_asset('ftp://ftp.netperf.org/netperf/'
                                   'netperf-2.7.0.tar.bz2', expire='7d')
        archive.extract(tarball, self.netperf)
        version = os.path.basename(tarball.split('.tar.')[0])
        self.neperf = os.path.join(self.netperf, version)
        tmp = "scp -r %s root@%s:" % (self.neperf, self.peer_ip)
        if process.system(tmp, shell=True, ignore_status=True) != 0:
            self.cancel("unable to copy the netperf into peer machine")
        tmp = "cd /root/netperf-2.7.0;./configure ppc64le;make"
        cmd = "ssh %s \"%s\"" % (self.peer_ip, tmp)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("test failed because command failed in peer machine")
        time.sleep(5)
        os.chdir(self.neperf)
        process.system('./configure ppc64le', shell=True)
        build.make(self.neperf)
        self.perf = os.path.join(self.neperf, 'src')
        time.sleep(5)
        tarball = self.fetch_asset('iperf.zip', locations=[
            'https://github.com/esnet/iperf/archive/master.zip'], expire='7d')
        archive.extract(tarball, self.iper)
        self.ipe = os.path.join(self.iper, 'iperf-master')
        tmp = "scp -r %s root@%s:" % (self.ipe, self.peer_ip)
        if process.system(tmp, shell=True, ignore_status=True) != 0:
            self.cancel("unable to copy the iperf into peer machine")
        tmp = "cd /root/iperf-master;./configure;make"
        cmd = "ssh %s \"%s\"" % (self.peer_ip, tmp)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("test failed because command failed in peer machine")
        time.sleep(5)
        os.chdir(self.ipe)
        process.system('./configure', shell=True)
        build.make(self.ipe)
        self.iperf = os.path.join(self.ipe, 'src')

    def interface_setup(self, arg1):
        '''
        Bringup IPoIB Interface
        '''
        self.log.info("Bringup Interface %s with %s mode", self.iface, arg1)
        cmd = "timeout %s ip link set %s down" % (self.tmo, self.iface)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("interface setup test failed")
        time.sleep(2)
        logs = "> /sys/class/net/%s/mode" % self.iface
        cmd = "timeout %s echo %s %s" % (self.tmo, arg1, logs)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("interface setup test failed")
        time.sleep(2)
        cmd = "timeout %s cat /sys/class/net/%s/mode" % (self.tmo, self.iface)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("interface setup test failed")
        cmd = "timeout %s ip link set %s up" % (self.tmo, self.iface)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("interface setup test failed")

    def netperf_test(self, arg1, arg2):
        '''
        netperf test
        '''
        if self.netserver_run == 0:
            tmp = "chmod 777 /root/netperf-2.7.0/src"
            cmd = "ssh %s \"%s\"" % (self.peer_ip, tmp)
            if process.system(cmd, shell=True, ignore_status=True) != 0:
                self.fail("test failed because netserver not available")
            cmd = "ssh %s \"/root/netperf-2.7.0/src/netserver\"" % self.peer_ip
            if process.system(cmd, shell=True, ignore_status=True) != 0:
                self.fail("test failed because netserver not available")
            else:
                self.netserver_run = 1
        time.sleep(5)
        msg = "timeout %s %s -H %s %s" % (
            self.tmo, self.perf + '/netperf', self.peer_ip, arg2)
        if process.system(msg, shell=True, ignore_status=True) != 0:
            self.fail("test failed because netperf not working")
        if arg1 == "datagram" and arg2 != "":
            msg = "timeout %s %s -H %s -t UDP_STREAM -- -m 63000" % \
                  (self.tmo, self.perf + '/netperf', self.peer_ip)
            if process.system(msg, shell=True, ignore_status=True) != 0:
                self.fail("test failed because netperf not working")
        else:
            msg = "timeout %s %s -H %s -t UDP_STREAM %s" % \
                  (self.tmo, self.perf + '/netperf', self.peer_ip, arg2)
            if process.system(msg, shell=True, ignore_status=True) != 0:
                self.fail("test failed because netperf not working")
        msg = "timeout %s %s -H %s -t TCP_RR %s" % \
              (self.tmo, self.perf + '/netperf', self.peer_ip, arg2)
        if process.system(msg, shell=True, ignore_status=True) != 0:
            self.fail("test failed because netperf not working")
        msg = "timeout %s %s -H %s -t UDP_RR %s" % \
              (self.tmo, self.perf + '/netperf', self.peer_ip, arg2)
        if process.system(msg, shell=True, ignore_status=True) != 0:
            self.fail("test failed because netperf not working")

    def iperf_test(self):
        '''
        iperf test
        '''
        if self.iperf_run == 0:
            logs = "> /tmp/ib_log 2>&1 &"
            tmp = "chmod 777 /root/iperf-master/src/iperf3"
            cmd = "ssh %s \"%s\"" % (self.peer_ip, tmp)
            if process.system(cmd, shell=True, ignore_status=True) != 0:
                self.fail("test failed because connect to peer sys failed")
            tmp = " /root/iperf-master/src/iperf3 -s %s " % logs
            cmd = "ssh %s \"%s\"" % (self.peer_ip, tmp)
            if process.system(cmd, shell=True, ignore_status=True) != 0:
                self.fail("test failed because connect to peer sys failed")
            else:
                self.iperf_run = 1
        time.sleep(5)
        cmd = "timeout %s %s -c %s -P 20 -n 8192" % \
              (self.tmo, self.iperf + '/iperf3', self.peer_ip)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("test failed because iperf not working")
        self.log.info("server data for iperf")
        msg = "timeout %s cat /tmp/ib_log" % self.tmo
        cmd = "ssh %s \"%s\"" % (self.peer_ip, msg)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("test failed because connect to peer sys failed")

    def test_ip_over_ib(self):
        '''
        IPoIB Tests
        '''
        test_name = self.params.get("tool")
        self.log.info("test with %s", test_name)
        if "ib" in self.iface:
            self.interface_setup(test_name)
            self.netperf_test(test_name, "")
            self.netperf_test(test_name, "-- -m 65000")
            self.iperf_test()
        else:
            self.log.info("Not applicable for the interface %s", self.iface)

    def tearDown(self):
        '''
        removing the data in peer machine
        '''
        msg = "pkill iperf3; pkill netserver;rm -rf /tmp/ib_log;\
               rm -rf /root/iperf-master; rm -rf /root/netperf-2.7.0"
        cmd = "ssh %s \"%s\"" % (self.peer_ip, msg)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("test failed because peer sys not connected")


if __name__ == "__main__":
    main()
