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
# Copyright: 2019 IBM
# Author: Narasimhan V <sim@linux.vnet.ibm.com>
# Co-author: Kalpana Shetty <kalshett@in.ibm.com>

'''
Tests for Basic Live Partition Mobility
'''

import time
try:
    import pxssh
except ImportError:
    from pexpect import pxssh
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils import distro
from avocado.utils.software_manager import SoftwareManager
from avocado.utils.process import CmdError
from avocado import skipIf, skipUnless

IS_POWER_NV = 'PowerNV' in open('/proc/cpuinfo', 'r').read()
IS_KVM_GUEST = 'qemu' in open('/proc/cpuinfo', 'r').read()


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


class LPM(Test):
    '''
    Performs LPM from source server to remote server, and back.
    '''
    @skipUnless("ppc" in distro.detect().arch,
                "supported only on Power platform")
    @skipIf(IS_POWER_NV or IS_KVM_GUEST,
            "This test is not supported on KVM guest or PowerNV platform")
    def setUp(self):
        '''
        set up required packages and gather necessary test inputs
        '''
        self.install_packages()
        self.rsct_service_start()

        self.hmc_ip = self.get_mcp_component("HMCIPAddr")
        if not self.hmc_ip:
            self.cancel("HMC IP not got from lsrsrc command")
        self.hmc_user = self.params.get("hmc_username", default='hscroot')
        self.hmc_pwd = self.params.get("hmc_pwd", '*', default='abc123')

        self.lpar = self.get_partition_name("Partition Name")
        if not self.lpar:
            self.cancel("LPAR Name not got from lsrsrc command")

        self.login(self.hmc_ip, self.hmc_user, self.hmc_pwd)

        cmd = 'lssyscfg -r sys -F name'
        output = self.run_command(cmd)
        self.server = ''

        for sys in output:
            cmd = 'lssyscfg -r lpar -F name -m %s' % sys
            lpars = self.run_command(cmd)
            for lpar in lpars:
                if lpar in self.lpar:
                    self.server = sys
                    break
        if not self.server:
            self.cancel("Managed System not got")

        self.source_server = self.params.get("source_server", default=None)
        if not self.source_server:
            self.cancel("No Source Server specified for LPM")

        self.remote_server = self.params.get("remote_server", default=None)
        if not self.remote_server:
            self.cancel("No Remote Server specified for LPM")

        if 'back' in str(self.name.name):
            current_server = self.remote_server
        else:
            current_server = self.server

        cmd = 'lssyscfg -r lpar -F name -m %s' % current_server
        output = self.run_command(cmd)
        for line in output:
            if "%s-" % self.lpar in line:
                self.lpar = line
                break

        if not self.is_lpar_in_server(current_server, self.lpar):
            self.cancel("%s not in %s" % (self.lpar, current_server))

    @staticmethod
    def get_mcp_component(component):
        '''
        probes IBM.MCP class for mentioned component and returns it.
        '''
        for line in process.system_output('lsrsrc IBM.MCP %s' % component,
                                          ignore_status=True, shell=True,
                                          sudo=True).splitlines():
            if component in line:
                return line.split()[-1].strip('{}\"')
        return ''

    @staticmethod
    def get_partition_name(component):
        '''
        get partition name from lparstat -i
        '''

        for line in process.system_output('lparstat -i', ignore_status=True,
                                          shell=True, sudo=True).splitlines():
            if component in line:
                return line.split(':')[-1].strip()

    def login(self, ipaddr, username, password):
        '''
        SSH Login method for remote server
        '''
        pxh = pxssh.pxssh()
        # Work-around for old pxssh not having options= parameter
        pxh.SSH_OPTS = pxh.SSH_OPTS + " -o 'StrictHostKeyChecking=no'"
        pxh.SSH_OPTS = pxh.SSH_OPTS + " -o 'UserKnownHostsFile /dev/null' "
        pxh.force_password = True

        pxh.login(ipaddr, username, password)
        pxh.sendline()
        pxh.prompt(timeout=60)
        # Ubuntu likes to be "helpful" and alias grep to
        # include color, which isn't helpful at all. So let's
        # go back to absolutely no messing around with the shell
        pxh.set_unique_prompt()
        pxh.prompt(timeout=60)
        self.pxssh = pxh

    def run_command(self, command, timeout=3000):
        '''
        SSH Run command method for running commands on remote server
        '''
        self.log.info("Running the command on hmc: %s", command)
        con = self.pxssh
        con.sendline(command)
        con.expect("\n")  # from us
        con.expect(con.PROMPT, timeout=timeout)
        output = con.before.splitlines()
        self.log.info("kal: %s", output)
        con.sendline("echo $?")
        con.prompt(timeout)
        return output

    def rsct_service_start(self):
        '''
        Running rsct services which is necessary for Network
        virtualization tests
        '''
        try:
            for svc in ["rsct", "rsct_rm"]:
                process.run('startsrc -g %s' % svc, shell=True, sudo=True)
        except CmdError as details:
            self.log.debug(str(details))
            self.fail("Starting service %s failed", svc)

        output = process.system_output("lssrc -a", ignore_status=True,
                                       shell=True, sudo=True)

        if "inoperative" in output:
            self.fail("Failed to start the rsct and rsct_rm services")

    def install_packages(self):
        '''
        Install required packages
        '''
        smm = SoftwareManager()
        detected_distro = distro.detect()
        self.log.info("Test is running on: %s", detected_distro.name)
        for pkg in ['ksh', 'src', 'rsct.basic', 'rsct.core.utils',
                    'rsct.core', 'DynamicRM']:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel('%s is needed for the test to be run' % pkg)

    def set_msp(self, server, vios_id):
        '''
        Sets the msp for the specified VIOS
        '''
        cmd = "chsyscfg -m %s -r lpar -i lpar_id=%s,msp=1" % (server,
                                                              vios_id)
        self.run_command(cmd)

    def do_migrate(self, server, remote_server, lpar, params):
        '''
        Migrate the LPAR from server to remote server
        '''
        cmd = "migrlpar -o m -m %s -t %s -p %s %s" % (server,
                                                      remote_server,
                                                      lpar, params)
        self.log.debug("\n".join(self.run_command(cmd)))
        time.sleep(10)
        if not self.is_lpar_in_server(remote_server, lpar):
            self.fail("%s not in %s" % (lpar, remote_server))
        # TODO: find a way to ensure migrated lpar is stable
        time.sleep(300)

    def is_lpar_in_server(self, server, lpar):
        '''
        Check if the LPAR is found in the server.
        Returns True, if found.
        Returns False, otherwise.
        '''
        cmd = "lssyscfg -r lpar -m %s -F name,state" % server
        output = "\n".join(self.run_command(cmd))
        if "%s," % lpar in output:
            return True
        return False

    def get_lpar_id(self, server, lpar_name):
        '''
        Gets the lpar id of given lpar on the server.
        '''
        cmd = "lssyscfg -m %s -r lpar --filter lpar_names=%s \
              -F lpar_id" % (server, lpar_name)
        return self.run_command(cmd)[-1]

    def test_migrate(self):
        '''
        Migrate the LPAR from given server to remote server.
        No additional param required for basic lpm.
        '''
        self.do_migrate(self.server, self.remote_server, self.lpar, ' ')

    def test_migrate_back(self):
        '''
        Migrate the LPAR from given remote server back to server.
        No additional param required for basic lpm.
        '''
        self.do_migrate(self.remote_server, self.source_server, self.lpar, ' ')

    def tearDown(self):
        if self.pxssh.isalive():
            self.pxssh.terminate()


if __name__ == "__main__":
    main()
