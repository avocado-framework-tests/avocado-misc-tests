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
# Author: Narasimhan V <sim@linux.vnet.ibm.com>

'''
RDMA test for infiniband adaptors
'''


import time
try:
    import pxssh
except ImportError:
    from pexpect import pxssh
import netifaces
from avocado import main
from avocado import Test
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import process, distro


class RDMA(Test):
    '''
    RDMA test for infiniband adaptors
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
                self.cancel("%s package is need to test" % pkg)
        interfaces = netifaces.interfaces()
        self.iface = self.params.get("interface", default="")
        self.peer_ip = self.params.get("peer_ip", default="")
        self.peer_user = self.params.get("peer_user_name", default="root")
        self.peer_password = self.params.get("peer_password", '*',
                                             default="passw0rd")
        self.peer_login(self.peer_ip, self.peer_user, self.peer_password)
        if self.iface not in interfaces:
            self.cancel("%s interface is not available" % self.iface)
        if self.peer_ip == "":
            self.cancel("%s peer machine is not available" % self.peer_ip)
        self.ca_name = self.params.get("CA_NAME", default="mlx4_0")
        self.port = self.params.get("PORT_NUM", default="1")
        self.peer_ca = self.params.get("PEERCA", default="mlx4_0")
        self.peer_port = self.params.get("PEERPORT", default="1")
        self.tmo = self.params.get("TIMEOUT", default="600")
        self.tool_name = self.params.get("tool")
        if self.tool_name == "":
            self.cancel("should specify tool name")
        self.log.info("test with %s", self.tool_name)
        self.test_op = self.params.get("test_opt", default="")

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
        output, exitcode = self.run_command(cmd)
        if exitcode != 0:
            self.cancel("Unable to disable firewall on peer")

    def peer_login(self, ip, username, password):
        '''
        SSH Login method for remote peer server
        '''
        pxh = pxssh.pxssh()
        # Work-around for old pxssh not having options= parameter
        pxh.SSH_OPTS = "%s  -o 'StrictHostKeyChecking=no'" % pxh.SSH_OPTS
        pxh.SSH_OPTS = "%s  -o 'UserKnownHostsFile /dev/null' " % pxh.SSH_OPTS
        pxh.force_password = True

        pxh.login(ip, username, password)
        pxh.sendline()
        pxh.prompt(timeout=60)
        pxh.sendline('exec bash --norc --noprofile')
        # Ubuntu likes to be "helpful" and alias grep to
        # include color, which isn't helpful at all. So let's
        # go back to absolutely no messing around with the shell
        pxh.set_unique_prompt()
        self.pxssh = pxh

    def run_command(self, command, timeout=300):
        '''
        SSH Run command method for running commands on remote server
        '''
        self.log.info("Running the command on peer lpar %s", command)
        if not hasattr(self, 'pxssh'):
            self.fail("SSH Console setup is not yet done")
        con = self.pxssh
        con.sendline(command)
        con.expect("\n")  # from us
        if command.endswith('&'):
            return ("", 0)
        con.expect(con.PROMPT, timeout=timeout)
        output = con.before.splitlines()
        con.sendline("echo $?")
        con.prompt(timeout)
        try:
            exitcode = int(''.join(con.before.splitlines()[1:]))
        except Exception as exc:
            exitcode = 0
        return (output, exitcode)

    def rdma_exec(self, arg1, arg2, arg3):
        '''
        bandwidth performance exec function
        '''
        flag = 0
        logs = "> /tmp/ib_log 2>&1 &"
        cmd = "timeout %s %s -d %s -i %s %s %s %s" \
            % (self.tmo, arg1, self.peer_ca, self.peer_port, arg2, arg3, logs)
        output, exitcode = self.run_command(cmd)
        if exitcode != 0:
            self.fail("ssh failed to remote machine\
                      or  faing data from remote machine failed")
        time.sleep(2)
        self.log.info("client data for %s(%s)", arg1, arg2)
        cmd = "timeout %s %s -d %s -i %s %s %s %s" \
            % (self.tmo, arg1, self.ca_name, self.port, self.peer_ip,
               arg2, arg3)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            flag = 1
        self.log.info("server data for %s(%s)", arg1, arg2)
        cmd = "timeout %s cat /tmp/ib_log && rm -rf /tmp/ib_log" % (self.tmo)
        output, exitcode = self.run_command(cmd)
        if exitcode != 0:
            self.fail("ssh failed to remote machine\
                      or fetching data from remote machine failed")
        return flag

    def test(self):
        '''
        test options are mandatory
        '''
        if self.rdma_exec(self.tool_name, self.test_op, "") != 0:
            self.fail("Client cmd: %s %s" % (self.tool_name, self.test_op))


if __name__ == "__main__":
    main()
