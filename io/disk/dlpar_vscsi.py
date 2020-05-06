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
DLPAR operations
"""

try:
    import pxssh
except ImportError:
    from pexpect import pxssh
from avocado import Test
from avocado import main
from avocado.utils import process


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


class DlparTest(Test):
    '''
    DLPAR disk script does vscsi device add,remove.
    Update the details in yaml file.
    '''

    def setUp(self):
        '''
        Gather necessary test inputs.
        '''
        self.disk = self.params.get('disk', default=None)
        self.num_of_dlpar = int(self.params.get("num_of_dlpar", default='1'))
        self.vios_ip = self.params.get('vios_ip', '*', default=None)
        self.vios_user = self.params.get('vios_username', '*', default=None)
        self.vios_pwd = self.params.get('vios_pwd', '*', default=None)
        self.login(self.vios_ip, self.vios_user, self.vios_pwd)
        cmd = "lscfg -l %s" % self.disk
        for line in process.system_output(cmd, shell=True).decode("utf-8") \
                                                          .splitlines():
            if self.disk in line:
                self.slot = line.split()[-1].split('-')[-2]
        cmd = "lsdev -slots"
        output = self.run_command(cmd)
        for line in output.splitlines():
            if self.slot in line:
                self.host = line.split()[-1]
        self.log.info(self.host)
        cmd = "lsscsi -vl"
        output = process.system_output(cmd, shell=True)
        for line in output.decode("utf-8").splitlines():
            if self.disk in line:
                value = line.split()[0].replace('[', '').replace(']', '')
        for line in output.decode("utf-8").splitlines():
            if value in line:
                if "dir" in line:
                    self.disk_dir = line.split()[-1].replace('[', '') \
                                                    .replace(']', '')
        cmd = r"cat %s/inquiry" % self.disk_dir
        output = process.system_output(cmd, shell=True)
        self.hdisk_name = output.split()[2].strip(b'0001').decode("utf-8")
        self.log.info(self.hdisk_name)
        cmd = "lsmap -all|grep -p %s" % self.hdisk_name
        output = self.run_command(cmd)
        for line in output.splitlines():
            if "VTD" in line:
                self.vscsi = line.split()[-1]
        if not self.vscsi:
            self.cancel("failed to get vscsi")
        self.log.info(self.vscsi)

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

    def dlpar_remove(self):
        '''
        dlpar remove operation
        '''
        cmd = "rmvdev -vdev %s" % self.hdisk_name
        try:
            output = self.run_command(cmd)
            self.log.info(output)
        except CommandFailed as cf:
            self.fail("failed dlpar remove operation, %s" % cf)

    def dlpar_add(self):
        '''
        dlpar add operation
        '''
        cmd = "mkvdev -vdev %s -vadapter %s -dev %s" % (self.hdisk_name,
                                                        self.host, self.vscsi)
        try:
            output = self.run_command(cmd)
            self.log.info(output)
        except CommandFailed as cf:
            self.fail("Failed dlpar add operation, %s" % cf)

    def test_dlpar(self):
        '''
        vscsi dlpar remove and add operation
        '''
        for _ in range(self.num_of_dlpar):
            self.dlpar_remove()
            self.dlpar_add()

    def tearDown(self):
        if self.pxssh.isalive():
            self.pxssh.terminate()


if __name__ == "__main__":
    main()
