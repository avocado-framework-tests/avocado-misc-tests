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
# Copyright: 2018 IBM
# Author: Narasimhan V <sim@linux.vnet.ibm.com>

"""
iperf is a tool for active measurements of the maximum achievable
bandwidth on IP networks.
"""

import os
try:
    import pxssh
except ImportError:
    from pexpect import pxssh
import netifaces
from avocado import main
from avocado import Test
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import build
from avocado.utils import archive
from avocado.utils import process
from avocado.utils.genio import read_file


class Iperf(Test):
    """
    Iperf Test
    """

    def setUp(self):
        """
        To check and install dependencies for the test
        """
        self.peer_user = self.params.get("peer_user_name", default="root")
        self.peer_ip = self.params.get("peer_ip", default="")
        self.peer_password = self.params.get("peer_password", '*',
                                             default=None)
        self.peer_login(self.peer_ip, self.peer_user, self.peer_password)
        smm = SoftwareManager()
        for pkg in ["gcc", "autoconf", "perl", "m4", "libtool"]:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel("%s package is need to test" % pkg)
            cmd = "%s install %s" % (smm.backend.base_command, pkg)
            output, exitcode = self.run_command(cmd)
            if exitcode != 0:
                self.cancel("unable to install the package %s on peer machine "
                            % pkg)
        interfaces = netifaces.interfaces()
        self.iface = self.params.get("interface", default="")
        if self.iface not in interfaces:
            self.cancel("%s interface is not available" % self.iface)
        if self.peer_ip == "":
            self.cancel("%s peer machine is not available" % self.peer_ip)
        iperf_download = self.params.get("iperf_download", default="https:"
                                         "//github.com/esnet/"
                                         "iperf/archive/master.zip")
        tarball = self.fetch_asset("iperf.zip", locations=[iperf_download],
                                   expire='7d')
        archive.extract(tarball, self.teststmpdir)
        self.iperf_dir = os.path.join(self.teststmpdir, "iperf-master")
        cmd = "scp -r %s %s@%s:/tmp" % (self.iperf_dir, self.peer_user,
                                        self.peer_ip)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.cancel("unable to copy the iperf into peer machine")
        cmd = "cd /tmp/iperf-master;./bootstrap.sh;./configure;make"
        output, exitcode = self.run_command(cmd)
        if exitcode != 0:
            self.cancel("Unable to compile Iperf into peer machine")
        self.iperf_run = str(self.params.get("IPERF_SERVER_RUN", default=0))
        if self.iperf_run == '1':
            cmd = "/tmp/iperf-master/src/iperf3 -s &"
            output, exitcode = self.run_command(cmd)
            if exitcode != 0:
                self.log.debug("Command %s failed %s", cmd, output)
        os.chdir(self.iperf_dir)
        process.system('./bootstrap.sh', shell=True)
        process.system('./configure', shell=True)
        build.make(self.iperf_dir)
        self.iperf = os.path.join(self.iperf_dir, 'src')
        self.expected_tp = self.params.get("EXPECTED_THROUGHPUT", default="85")

    def peer_login(self, ip, username, password):
        '''
        SSH Login method for remote peer server
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
        Test run is a One way throughput test. In this test, we have one host
        transmitting (or receiving) data from a client. This transmit large
        messages using multiple threads or processes.
        """
        speed = int(read_file("/sys/class/net/%s/speed" % self.iface))
        os.chdir(self.iperf)
        cmd = "./iperf3 -c %s" % self.peer_ip
        result = process.run(cmd, shell=True, ignore_status=True)
        if result.exit_status:
            self.fail("FAIL: Iperf Run failed")
        for line in result.stdout.deocde("utf-8").splitlines():
            if 'sender' in line:
                tput = int(line.split()[6].split('.')[0])
                if tput < (int(self.expected_tp) * speed) / 100:
                    self.fail("FAIL: Throughput Actual - %s%%, Expected - %s%%"
                              ", Throughput Actual value - %s "
                              % ((tput*100)/speed, self.expected_tp,
                                 str(tput)+'Mb/sec'))

    def tearDown(self):
        """
        Killing Iperf process in peer machine
        """
        cmd = "pkill iperf; rm -rf /tmp/iperf-master"
        output, exitcode = self.run_command(cmd)
        if exitcode != 0:
            self.fail("Either the ssh to peer machine machine\
                       failed or iperf process was not killed")


if __name__ == "__main__":
    main()
