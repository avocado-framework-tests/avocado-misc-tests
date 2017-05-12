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
# Bandwidth Performance test for infiniband adaptors
# ib_send_bw test
# ib_write_bw test
# ib_read_bw test
# ib_atomic_bw test
#
#


import time
import netifaces
from avocado import main
from avocado import Test
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import process, distro


class Bandwidth_Perf(Test):
    '''
    Infiniband adaptors bandwidth performance tests using four tools
    tools are ib_send_bw,ib_write_bw,ib_read_bw,ib_atomic_bw
    '''
    def setUp(self):
        '''
        check the availability of perftest package installed
        perftest package should be installed
        '''
        smm = SoftwareManager()
        detected_distro = distro.detect()
        pkgs = ["perftest"]
        if detected_distro.name == "Ubuntu":
            pkgs.append('openssh-client')
        elif detected_distro.name == "SuSE":
            pkgs.append('openssh')
        else:
            pkgs.append('openssh-clients')
        for pkg in pkgs:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.skip("%s package is need to test" % pkg)
        interfaces = netifaces.interfaces()
        self.flag = self.params.get("ext_flag", default="0")
        self.IF = self.params.get("interface", default="")
        self.peer_ip = self.params.get("peer_ip", default="")
        if self.IF not in interfaces:
            self.skip("%s interface is not available" % self.IF)
        if self.peer_ip == "":
            self.skip("%s peer machine is not available" % self.peer_ip)
        self.CA = self.params.get("CA_NAME", default="mlx4_0")
        self.PORT = self.params.get("PORT_NUM", default="1")
        self.PEER_CA = self.params.get("PEERCA", default="mlx4_0")
        self.PEER_PORT = self.params.get("PEERPORT", default="1")
        self.to = self.params.get("timeout", default="600")
        self.tool_name = self.params.get("tool")
        if self.tool_name == "":
            self.skip("should specify tool name")
        self.log.info("test with %s" % (self.tool_name))
        self.test_op = self.params.get("test_opt", default="").split(",")
        self.ext_test_op = self.params.get("ext_opt", default="").split(",")

        if detected_distro.name == "Ubuntu":
            cmd = "service ufw stop"
        # FIXME: "redhat" as the distro name for RHEL is deprecated
        # on Avocado versions >= 50.0.  This is a temporary compatibility
        # enabler for older runners, but should be removed soon
        elif detected_distro.name in ['rhel', 'fedora', 'redhat']:
            cmd = "systemctl stop firewalld"
        elif detected_distro.name == "SuSE":
            cmd = "rcSuSEfirewall2 stop"
        elif detected_distro.name == "centos":
            cmd = "service iptables stop"
        else:
            self.skip("Distro not supported")
        if process.system("%s && ssh %s %s" % (cmd, self.peer_ip, cmd),
                          ignore_status=True, shell=True) != 0:
            self.skip("Unable to disable firewall")

    def bandwidthperf_exec(self, arg1, arg2, arg3):
        '''
        bandwidth performance exec function
        '''
        logs = "> /tmp/ib_log 2>&1 &"
        cmd = "ssh %s \" timeout %s %s -d %s -i %s %s %s %s\" " \
            % (self.peer_ip, self.to, arg1, self.PEER_CA, self.PEER_PORT,
               arg2, arg3, logs)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("ssh failed to remote machine\
                      or  faing data from remote machine failed")
        time.sleep(2)
        self.log.info("client data for %s(%s)" % (arg1, arg2))
        cmd = "timeout %s %s -d %s -i %s %s %s %s" \
            % (self.to, arg1, self.CA, self.PORT, self.peer_ip,
               arg2, arg3)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("client command failed for the tool %s" % self.tool_name)
        self.log.info("server data for %s(%s)" % (arg1, arg2))
        cmd = "ssh %s \"timeout %s cat /tmp/ib_log && rm -rf /tmp/ib_log\" " %\
              (self.peer_ip, self.to)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("ssh failed to remote machine\
                      or fetching data from remote machine failed")

    def test_ib_bandwidth(self):
        '''
        test options are mandatory
        ext test options are depends upon user
        '''
        for val in self.test_op:
            self.bandwidthperf_exec(self.tool_name, val, "")
        if self.flag == "1":
            for val in self.ext_test_op:
                self.bandwidthperf_exec(self.tool_name, val, "")
        else:
            self.log.info("Extended test option skipped")


if __name__ == "__main__":
    main()
