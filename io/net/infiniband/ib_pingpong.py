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
# ping pong test
# ibv_ud_pingpong
# ibv_uc_pingpong
# ibv_rc_pingpong
# ibv_srq_pingpong


import time
import netifaces
from avocado import main
from avocado import Test
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import process
from avocado.utils import distro


class pingpong(Test):
    '''
    ibv_ud_pingpong test
    ibv_ud_pingpong tool should be installed
    '''
    def setUp(self):
        '''
        To check and install dependencies for the test
        '''
        interfaces = netifaces.interfaces()
        self.flag = self.params.get("ext_flag", default="0")
        self.IF = self.params.get("interface", default="")
        self.PEER_IP = self.params.get("peer_ip", default="")
        if self.IF not in interfaces:
            self.skip("%s interface is not available" % self.IF)
        if self.PEER_IP == "":
            self.skip("%s peer machine is not available" % self.PEER_IP)
        self.CA = self.params.get("CA_NAME", default="mlx4_0")
        self.GID = int(self.params.get("GID_NUM", default="0"))
        self.PORT = int(self.params.get("PORT_NUM", default="1"))
        self.PEER_CA = self.params.get("PEERCA", default="mlx4_0")
        self.PEER_GID = int(self.params.get("PEERGID", default="0"))
        self.PEER_PORT = int(self.params.get("PEERPORT", default="1"))
        self.to = self.params.get("timeout", default="120")

        smm = SoftwareManager()
        detected_distro = distro.detect()
        pkgs = []
        if detected_distro.name == "Ubuntu":
            pkgs.extend(["ibverbs", 'openssh-client'])
            cmd = "service ufw stop"
        # FIXME: "redhat" as the distro name for RHEL is deprecated
        # on Avocado versions >= 50.0.  This is a temporary compatibility
        # enabler for older runners, but should be removed soon
        elif detected_distro.name in ['rhel', 'fedora', 'redhat']:
            pkgs.extend(["libibverbs", 'openssh-clients'])
            cmd = "systemctl stop firewalld"
        elif detected_distro.name == "SuSE":
            pkgs.append('openssh')
            cmd = "rcSuSEfirewall2 stop"
        elif detected_distro.name == "centos":
            pkgs.extend(['libibverbs', 'openssh-clients'])
            cmd = "service iptables stop"
        else:
            self.skip("Distro not supported")
        if process.system("%s && ssh %s %s" %
                          (cmd, self.PEER_IP, cmd),
                          ignore_status=True,
                          shell=True) != 0:
            self.skip("Unable to disable firewall")
        for pkg in pkgs:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.skip("%s package is need to test" % pkg)
        if process.system("ibstat", shell=True, ignore_status=True) != 0:
            self.skip("infiniband adaptors not available")

    def pingpong_exec(self, arg1, arg2, arg3):
        '''
        ping pong exec function
        '''
        test = arg2
        logs = "> /tmp/ib_log 2>&1 &"
        if test == "basic":
            test = ""
        msg = " \"timeout %s %s -d %s -g %d -i %d %s %s %s\" " \
            % (self.to, arg1, self.PEER_CA, self.PEER_GID, self.PEER_PORT,
               test, arg3, logs)
        cmd = "ssh %s %s" % (self.PEER_IP, msg)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("ssh failed to remote machine")
        time.sleep(2)
        self.log.info("client data for %s(%s)" % (arg1, arg2))
        self.log.info("%s -d %s -g %d %s -i %d %s %s"
                      % (arg1, self.CA, self.GID, self.PEER_IP, self.PORT,
                         test, arg3))
        tmp = "timeout %s %s -d %s -g %d -i %d %s %s %s" \
            % (self.to, arg1, self.CA, self.GID, self.PORT, self.PEER_IP,
               test, arg3)
        if process.system(tmp, shell=True, ignore_status=True) != 0:
            self.fail("test failed")
        self.log.info("server data for %s(%s)" % (arg1, arg2))
        self.log.info("%s -d %s -g %d -i %d %s %s"
                      % (arg1, self.PEER_CA, self.PEER_GID, self.PEER_PORT,
                         test, arg3))
        msg = " \"timeout %s cat /tmp/ib_log && rm -rf /tmp/ib_log\" " \
            % self.to
        cmd = "ssh %s %s" % (self.PEER_IP, msg)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("test failed")

    def test_ib_pingpong(self):
        '''
        test options are mandatory
        ext test options are depends upon user
        '''
        tool_name = self.params.get("tool")
        self.log.info("test with %s" % (tool_name))
        if "ib" not in self.IF and tool_name == "ibv_ud_pingpong":
            tmp = "grep -w -B 1 %s" % self.PEER_IP
            cmd = " \` ifconfig | %s | head -1 | cut -f1 -d ' ' \` " % tmp
            msg = "ssh %s \"ifconfig %s mtu 9000\"" % (self.PEER_IP, cmd)
            process.system(msg, shell=True)
            con_msg = "ifconfig %s mtu 9000" % (self.IF)
            process.system(con_msg, shell=True)
            time.sleep(10)
        val1 = ""
        val2 = ""
        test_op = self.params.get("test_opt", default="").split(",")
        for val in test_op:
            try:
                val1, val2 = val.split()
            except ValueError:
                pass
            self.pingpong_exec(tool_name, val1, val2)
        ext_test_op = self.params.get("ext_test_opt", default="").split(",")
        if self.flag == "1":
            for val in ext_test_op:
                self.pingpong_exec(tool_name, val, "")
        else:
            self.log.info("Extended test option skipped")
        '''
        change MTU to 1500 for non-IB tests
        '''
        if "ib" not in self.IF and tool_name == "ibv_ud_pingpong":
            tmp = "grep -w -B 1 %s" % self.PEER_IP
            cmd = "\`ifconfig | %s | head -1 | cut -f1 -d' '\`" % tmp
            msg = "ssh %s \"ifconfig %s mtu 1500\"" % (self.PEER_IP, cmd)
            process.system(msg, shell=True)
            con_msg = "ifconfig %s mtu 1500" % (self.IF)
            process.system(con_msg, shell=True)
            time.sleep(10)


if __name__ == "__main__":
    main()
