#!/usr/bin/python

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
# Author: Bismruti Bidhibrata Pattjoshi<bbidhibr@in.ibm.com>

"""
Veth DLPAR operations
"""

import time
try:
    import pxssh
except ImportError:
    from pexpect import pxssh
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils.network.hosts import LocalHost
from avocado.utils.network.interfaces import NetworkInterface


class CommandFailed(Exception):
    '''
    Defines the exception called when a
    command fails
    '''
    def __init__(self, command, output, exitcode):
        Exception.__init__(self, command, output, exitcode)
        self.command = command
        self.output = output
        self.exitcode = exitcode

    def __str__(self):
        return "Command '%s' exited with %d.\nOutput:\n%s" \
               % (self.command, self.exitcode, self.output)


class VethdlparTest(Test):
    '''
    DLPAR veth script does veth device add,remove.
    Update the details in yaml file.
    '''

    def setUp(self):
        '''
        Gather necessary test inputs.
        '''
        self.interface = self.params.get('interface', default=None)
        self.peer_ip = self.params.get('peer_ip', default=None)
        self.num_of_dlpar = int(self.params.get("num_of_dlpar", default='1'))
        self.vios_ip = self.params.get('vios_ip', '*', default=None)
        self.vios_user = self.params.get('vios_username', '*', default=None)
        self.vios_pwd = self.params.get('vios_pwd', '*', default=None)
        self.login(self.vios_ip, self.vios_user, self.vios_pwd)
        cmd = "lscfg -l %s" % self.interface
        for line in process.system_output(cmd, shell=True).decode("utf-8") \
                                                          .splitlines():
            if self.interface in line:
                self.slot = line.split()[-1].split('-')[-2]
        cmd = "lsmap -all -net"
        output = self.run_command(cmd)
        for line in output.splitlines():
            if self.slot in line:
                self.iface = line.split()[0]
        cmd = "lsmap -vadapter %s -net" % self.iface
        output = self.run_command(cmd)
        for line in output.splitlines():
            if "SEA" in line:
                self.sea = line.split()[-1]
        if not self.sea:
            self.cancel("failed to get SEA")
        self.log.info(self.sea)
        local = LocalHost()
        self.networkinterface = NetworkInterface(self.interface, local)
        if self.networkinterface.ping_check(self.peer_ip, count=5) is not None:
            self.cancel("peer connection is failed")

    def login(self, ipaddr, username, password):
        '''
        SSH Login method for remote server
        '''
        pxh = pxssh.pxssh(encoding='utf-8')
        # Work-around for old pxssh not having options= parameter
        pxh.SSH_OPTS = "%s  -o 'StrictHostKeyChecking=no'" % pxh.SSH_OPTS
        pxh.SSH_OPTS = "%s  -o 'UserKnownHostsFile /dev/null' " % pxh.SSH_OPTS
        pxh.force_password = True

        pxh.login(ipaddr, username, password)
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
        con.expect(con.PROMPT, timeout=timeout)
        output = "".join(con.before)
        con.sendline("echo $?")
        con.prompt(timeout)
        exitcode = int(''.join(con.before.splitlines()[1:]))
        if exitcode != 0:
            raise CommandFailed(command, output, exitcode)
        return output

    def veth_dlpar_remove(self):
        '''
        veth dlpar remove operation
        '''
        cmd = "rmdev -l %s" % self.sea
        cmd_l = "echo \"%s\" | oem_setup_env" % cmd
        try:
            output = self.run_command(cmd_l)
            self.log.info(output)
        except CommandFailed as cf:
            self.fail("failed dlpar remove operation as %s" % cf)

    def veth_dlpar_add(self):
        '''
        veth dlpar add operation
        '''
        cmd = "mkdev -l %s" % self.sea
        cmd_l = "echo \"%s\" | oem_setup_env" % cmd
        try:
            output = self.run_command(cmd_l)
            self.log.info(output)
        except CommandFailed as cf:
            self.fail("Failed dlpar add operation as %s" % cf)

    def test_dlpar(self):
        '''
        veth dlapr remove and add operation
        '''
        for _ in range(self.num_of_dlpar):
            self.veth_dlpar_remove()
            time.sleep(30)
            self.veth_dlpar_add()
            if self.networkinterface.ping_check(self.peer_ip,
                                                count=5) is not None:
                self.fail("ping failed after add operation")

    def tearDown(self):
        if self.pxssh.isalive():
            self.pxssh.terminate()


if __name__ == "__main__":
    main()
