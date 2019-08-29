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
#
# test multicasting
# to test we need to enable  multicast option on host
# then ping from peer to multicast group


try:
    import pxssh
except ImportError:
    from pexpect import pxssh
import netifaces
from avocado import main
from avocado import Test
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import process
from avocado.utils import distro


class ReceiveMulticastTest(Test):
    '''
    check multicast receive
    using ping tool
    '''

    def setUp(self):
        '''
        To check and install dependencies for the test
        '''
        self.peer = self.params.get("peer_ip", default="")
        self.user = self.params.get("user_name", default="root")
        self.peer_password = self.params.get("peer_password",
                                             '*', default="passw0rd")
        self.login(self.peer, self.user, self.peer_password)
        self.count = self.params.get("count", default="500000")
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
                self.cancel("%s package is need to test" % pkg)
        interfaces = netifaces.interfaces()
        self.iface = self.params.get("interface")
        if self.iface not in interfaces:
            self.cancel("%s interface is not available" % self.iface)
        if self.peer == "":
            self.cancel("peer ip should specify in input")
        cmd = "ip addr show  | grep %s | grep -oE '[^ ]+$'" % self.peer
        output, exitcode = self.run_command(cmd)
        self.peerif = ""
        self.peerif = self.peerif.join(output)
        if self.peerif == "":
            self.cancel("unable to get peer interface")
        cmd = "ip -f inet -o addr show %s | awk '{print $4}' | cut -d / -f1"\
              % self.iface
        self.local_ip = process.system_output(cmd, shell=True).strip()
        if self.local_ip == "":
            self.cancel("unable to get local ip")

    def login(self, ip, username, password):
        '''
        SSH Login method for remote server
        '''
        pxh = pxssh.pxssh(encoding='utf-8')
        # Work-around for old pxssh not having options= parameter
        pxh.SSH_OPTS = "%s  -o 'StrictHostKeyChecking=no'" % pxh.SSH_OPTS
        pxh.SSH_OPTS = "%s  -o 'UserKnownHostsFile /dev/null' " % pxh.SSH_OPTS
        pxh.force_password = True

        pxh.login(ip, username, password)
        pxh.sendline()
        pxh.prompt(timeout=60)
        pxh.sendline('exec bash --norc --noprofile')
        pxh.prompt(timeout=60)
        # Ubuntu likes to be "helpful" and alias grep to
        # include color, which isn't helpful at all. So let's
        # go back to absolutely no messing around with the shell
        pxh.set_unique_prompt()
        pxh.prompt(timeout=60)
        self.pxssh = pxh

    def run_command(self, command, timeout=300):
        '''
        SSH Run command method for running commands on remote server
        '''
        self.log.info("Running the command on peer lpar: %s", command)
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

    def test_multicast(self):
        '''
        ping to peer machine
        '''
        cmd = "echo 0 > /proc/sys/net/ipv4/icmp_echo_ignore_broadcasts"
        if process.system(cmd, shell=True, verbose=True,
                          ignore_status=True) != 0:
            self.fail("unable to set value to icmp_echo_ignore_broadcasts")
        cmd = "ip link set %s allmulticast on" % self.iface
        if process.system(cmd, shell=True, verbose=True,
                          ignore_status=True) != 0:
            self.fail("unable to set all mulicast option to test interface")
        cmd = "ip route add 224.0.0.0/4 dev %s" % self.peerif
        output, exitcode = self.run_command(cmd)
        if exitcode != 0:
            self.fail("Unable to add route for Peer interafce")
        msg = "0% packet loss"
        cmd = "ping -I %s 224.0.0.1 -c %s -f | grep \'%s\'" %\
              (self.peerif, self.count, msg)
        output, exitcode = self.run_command(cmd)
        if exitcode != 0:
            self.fail("multicast test failed")

    def tearDown(self):
        '''
        delete multicast route and turn off multicast option
        '''
        cmd = "ip route del 224.0.0.0/4"
        output, exitcode = self.run_command(cmd)
        if exitcode != 0:
            self.log.info("Unable to delete multicast route added for peer")
        cmd = "echo 1 > /proc/sys/net/ipv4/icmp_echo_ignore_broadcasts"
        if process.system(cmd, shell=True, verbose=True,
                          ignore_status=True) != 0:
            self.log.info("unable to unset all mulicast option")
        cmd = "ip link set %s allmulticast off" % self.iface
        if process.system(cmd, shell=True, verbose=True,
                          ignore_status=True) != 0:
            self.log.info("unable to unset all mulicast option")


if __name__ == "__main__":
    main()
