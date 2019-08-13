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
Udaddy - RDMA CM datagram setup and simple ping-pong test.
"""

import time
try:
    import pxssh
except ImportError:
    from pexpect import pxssh
import netifaces
from netifaces import AF_INET
from avocado import Test
from avocado import main
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import process, distro


class Udady(Test):
    """
    Udaddy Test.
    """

    def setUp(self):
        """
        Setup and install dependencies for the test.
        """
        self.test_name = "udaddy"
        self.basic = self.params.get("basic_option", default="None")
        self.ext = self.params.get("ext_option", default="None")
        self.flag = self.params.get("ext_flag", default="0")
        if self.basic == "None" and self.ext == "None":
            self.cancel("No option given")
        if self.flag == "1" and self.ext != "None":
            self.option = self.ext
        else:
            self.option = self.basic
        if process.system("ibstat", shell=True, ignore_status=True) != 0:
            self.cancel("MOFED is not installed. Skipping")
        detected_distro = distro.detect()
        pkgs = []
        smm = SoftwareManager()
        if detected_distro.name == "Ubuntu":
            pkgs.extend(["openssh-client", "iputils-ping"])
        elif detected_distro.name == "SuSE":
            pkgs.extend(["openssh", "iputils"])
        else:
            pkgs.extend(["openssh-clients", "iputils"])
        for pkg in pkgs:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel("Not able to install %s" % pkg)
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
        self.timeout = "2m"
        self.local_ip = netifaces.ifaddresses(self.iface)[AF_INET][0]['addr']

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

    def test(self):
        """
        Test udaddy
        """
        self.log.info(self.test_name)
        logs = "> /tmp/ib_log 2>&1 &"
        cmd = " timeout %s %s -b %s %s %s" % (self.timeout, self.test_name,
                                              self.peer_ip, self.option, logs)
        output, exitcode = self.run_command(cmd)
        if exitcode != 0:
            self.fail("SSH connection (or) Server command failed")
        time.sleep(5)
        self.log.info("Client data - %s(%s)" % (self.test_name, self.option))
        cmd = "timeout %s %s -s %s -b %s %s" \
            % (self.timeout, self.test_name, self.peer_ip,
               self.local_ip, self.option)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("Client command failed")
        time.sleep(5)
        self.log.info("Server data - %s(%s)" % (self.test_name, self.option))
        cmd = "timeout %s cat /tmp/ib_log && rm -rf /tmp/ib_log" \
            % (self.timeout)
        output, exitcode = self.run_command(cmd)
        if exitcode != 0:
            self.fail("Server output retrieval failed")


if __name__ == "__main__":
    main()
