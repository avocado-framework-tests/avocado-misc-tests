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
# Copyright: 2017 IBM
# Author: Pridhiviraj Paidipeddi <ppaidipe@linux.vnet.ibm.com>
# Author: Venkat Rao B <vrbagal1@linux.vnet.ibm.com>

import os
import shutil
try:
    import pxssh
except ImportError:
    from pexpect import pxssh
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils import distro
from avocado.utils import pci
from avocado.utils.software_manager import SoftwareManager
from avocado.utils.process import CmdError


class CommandFailed(Exception):
    def __init__(self, command, output, exitcode):
        self.command = command
        self.output = output
        self.exitcode = exitcode

    def __str__(self):
        return "Command '%s' exited with %d.\nOutput:\n%s" \
               % (self.command, self.exitcode, self.output)


class DlparPci(Test):
    '''
    DLPAR PCI script does pci add,remove and also move operation from one
    lpar to another lpar. Update the details in yaml file.
    For move operation, please configure another lpar and update in yaml file.
    And also make sure both rsct and rsct_rm services up and running
    '''

    def setUp(self):
        '''
        set up required packages and gather necessary test inputs.
        Test all services.
        '''
        sm = SoftwareManager()
        detected_distro = distro.detect()
        self.log.info("Test is running on:" + detected_distro.name)
        if not sm.check_installed("ksh") and not sm.install("ksh"):
            self.error('ksh is needed for the test to be run')
        if detected_distro.name == "Ubuntu":
            if not sm.check_installed("python-paramiko") and not \
                                      sm.install("python-paramiko"):
                self.error('python-paramiko is needed for the test to be run')
            ubuntu_url = self.params.get('ubuntu_url', default=None)
            debs = self.params.get('debs', default=None)
            for deb in debs:
                deb_url = os.path.join(ubuntu_url, deb)
                deb_install = self.fetch_asset(deb_url, expire='7d')
                shutil.copy(deb_install, self.workdir)
                process.system("dpkg -i %s/%s" % (self.workdir, deb),
                               ignore_status=True, sudo=True)
        else:
            url = self.params.get('url', default=None)
            rpm_install = self.fetch_asset(url, expire='7d')
            shutil.copy(rpm_install, self.workdir)
            os.chdir(self.workdir)
            process.run('chmod +x ibmtools')
            process.run('./ibmtools --install --managed')
        try:
            process.run("startsrc -g rsct", shell=True, sudo=True)
        except CmdError as details:
            self.log.debug(str(details))
            self.cancel("Command startsrc -g rsct failed")

        try:
            process.run("startsrc -g rsct_rm", shell=True, sudo=True)
        except CmdError as details:
            self.log.debug(str(details))
            self.cancel("Command startsrc -g rsct_rm failed")

        output = process.system_output("lssrc -a", ignore_status=True,
                                       shell=True, sudo=True)
        if "inoperative" in output:
            self.cancel("Failed to start the rsct and rsct_rm services")

        self.hmc_ip = self.params.get("hmc_ip", '*', default=None)
        self.hmc_pwd = self.params.get("hmc_pwd", '*', default=None)
        self.hmc_username = self.params.get("hmc_username", '*', default=None)
        self.lpar_1 = self.params.get("lpar_1", '*', default=None)
        self.lpar_2 = self.params.get("lpar_2", '*', default=None)
        self.pci_device = self.params.get("pci_device", '*', default=None)
        self.server = self.params.get("server", '*', default=None)
        self.loc_code = pci.get_slot_from_sysfs(self.pci_device)
        self.num_of_dlpar = int(self.params.get("num_of_dlpar", default='1'))
        if self.loc_code is None:
            self.cancel("Failed to get the location code for the pci device")
        self.login(self.hmc_ip, self.hmc_username, self.hmc_pwd)
        self.run_command("uname -a")
        cmd = 'lshwres -r io -m ' + self.server + \
              ' --rsubtype slot --filter lpar_names=' + self.lpar_1 + \
              ' -F drc_index,lpar_id,drc_name | grep -i %s ' % self.loc_code

        output = self.run_command(cmd)
        self.drc_index = output[-1].split(',')[0]
        self.lpar_id = output[-1].split(',')[1]
        self.log.info("lpar_id : %s, loc_code: %s, drc_index: %s",
                      self.lpar_id, self.loc_code, self.drc_index)

    def login(self, ip, username, password):
        '''
        SSH Login method for remote server
        '''
        p = pxssh.pxssh()
        # Work-around for old pxssh not having options= parameter
        p.SSH_OPTS = p.SSH_OPTS + " -o 'StrictHostKeyChecking=no'"
        p.SSH_OPTS = p.SSH_OPTS + " -o 'UserKnownHostsFile /dev/null' "
        p.force_password = True

        p.login(ip, username, password)
        p.sendline()
        p.prompt(timeout=60)
        # Ubuntu likes to be "helpful" and alias grep to
        # include color, which isn't helpful at all. So let's
        # go back to absolutely no messing around with the shell
        p.set_unique_prompt()
        p.prompt(timeout=60)
        self.pxssh = p

    def run_command(self, command, timeout=300):
        '''
        SSH Run command method for running commands on remote server
        '''
        self.log.info("Running the command on hmc %s", command)
        c = self.pxssh
        c.sendline(command)
        c.expect("\n")  # from us
        c.expect(c.PROMPT, timeout=timeout)
        output = c.before.splitlines()
        c.sendline("echo $?")
        c.prompt(timeout)
        return output

    def test_dlpar(self):
        '''
        DLPAR remove, add and move operations from lpar_1 to lpar_2
        '''
        for i in range(self.num_of_dlpar):
            self.dlpar_remove()
            self.dlpar_add()
            self.dlpar_move()

    def test_drmgr(self):
        '''
        drmgr remove, add and replace operations
        '''
        self.do_drmgr('Q')
        for _ in range(self.num_of_dlpar):
            self.do_drmgr('r')
            self.do_drmgr('a')
        for _ in range(self.num_of_dlpar):
            self.do_drmgr('R')

    def do_drmgr(self, operation):
        '''
        drmgr operation
        '''
        cmd = "echo -e \"\n\" | drmgr -c pci -s %s -%s" % (self.loc_code,
                                                           operation)
        if process.system(cmd, shell=True, sudo=True, ignore_status=True):
            self.fail("drmgr operation %s fails" % operation)

    def dlpar_remove(self):
        '''
        dlpar remove operation
        '''
        self.changehwres(self.server, 'r', self.lpar_id, self.lpar_1,
                         self.drc_index, 'remove')
        output = self.listhwres(self.server, self.lpar_1, self.drc_index)
        if output:
            self.log.debug(output)
            self.fail("lshwres still lists the drc after dlpar remove")

    def dlpar_add(self):
        '''
        dlpar add operation
        '''
        self.changehwres(self.server, 'a', self.lpar_id, self.lpar_1,
                         self.drc_index, 'add')
        output = self.listhwres(self.server, self.lpar_1, self.drc_index)
        if self.drc_index not in output[0]:
            self.log.debug(output)
            self.fail("lshwres fails to list the drc after dlpar add")

    def dlpar_move(self):
        '''
        dlpar move operation from lpar_1 to lpar2 and back from
        lpar_2 to lpar_1
        '''
        if self.lpar_2 is None:
            return

        self.changehwres(self.server, 'm', self.lpar_id, self.lpar_2,
                         self.drc_index, 'move')

        output = self.listhwres(self.server, self.lpar_1, self.drc_index)
        if self.drc_index in output[0]:
            self.log.debug(output)
            self.fail("lshwres still lists the drc in lpar_1 after \
                      dlpar move to lpar_2")

        output = self.listhwres(self.server, self.lpar_2, self.drc_index)
        if self.drc_index not in output[0]:
            self.log.debug(output)
            self.fail("lshwres fails to list the drc in lpar_2 after \
                       dlpar move")

        # dlpar move operation from lpar2 to lpar1
        self.changehwres(self.server, 'm', self.lpar_id, self.lpar_1,
                         self.drc_index, 'move')

        output = self.listhwres(self.server, self.lpar_1, self.drc_index)
        if self.drc_index not in output[0]:
            self.log.debug(output)
            self.fail("lshwres fails to list the drc in lpar_1 after \
                       dlpar move")

        output = self.listhwres(self.server, self.lpar_2, self.drc_index)
        if self.drc_index in output[0]:
            self.log.debug(output)
            self.fail("lshwres still lists the drc in lpar_2 after \
                      dlpar move to lpar_1")

    def listhwres(self, server, lpar, drc_index):
        cmd = 'lshwres -r io -m %s \
               --rsubtype slot --filter lpar_names= %s \
               | grep -i %s' % (server, lpar, drc_index)
        try:
            cmd = self.run_command(cmd)
        except CommandFailed as cf:
            self.log.debug(str(cf))
            self.fail("lshwres operation failed ")
        return cmd

    def changehwres(self, server, operation, lpar_id, lpar, drc_index, msg):
        if operation == 'm':
            cmd = 'chhwres -r io --rsubtype slot -m %s \
               -o %s --id %s -t %s -l %s ' % (server, operation, lpar_id,
                                              lpar, drc_index)
        else:
            cmd = 'chhwres -r io --rsubtype slot -m %s \
                   -o %s --id %s -l %s ' % (server, operation, lpar_id,
                                            drc_index)
        try:
            cmd = self.run_command(cmd)
        except CommandFailed as cf:
            self.log.debug(str(cf))
            self.fail("dlpar %s operation failed" % msg)

    def tearDown(self):
        if self.pxssh.isalive():
            self.pxssh.terminate()


if __name__ == "__main__":
    main()
