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
# Copyright: 2018 IBM
# Author: Harsha Thyagaraja <harshkid@linux.vnet.ibm.com>

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
from avocado.utils.software_manager import SoftwareManager
from avocado.utils.process import CmdError
from avocado import skipIf, skipUnless

IS_POWER_NV = 'PowerNV' in open('/proc/cpuinfo', 'r').read()
IS_KVM_GUEST = 'qemu' in open('/proc/cpuinfo', 'r').read()


class CommandFailed(Exception):
    def __init__(self, command, output, exitcode):
        self.command = command
        self.output = output
        self.exitcode = exitcode

    def __str__(self):
        return "Command '%s' exited with %d.\nOutput:\n%s" \
               % (self.command, self.exitcode, self.output)


class NetworkVirtualization(Test):
    '''
    Adding and deleting Backing devices to Network
    Virtualized ports from the vios
    '''
    @skipUnless("ppc" in distro.detect().arch,
                "supported only on Power platform")
    @skipIf(IS_POWER_NV or IS_KVM_GUEST,
            "This test is not supported on KVM guest or PowerNV platform")
    def setUp(self):
        '''
        set up required packages and gather necessary test inputs
        '''
        smm = SoftwareManager()
        detected_distro = distro.detect()
        self.log.info("Test is running on:" + detected_distro.name)
        if not smm.check_installed("ksh") and not smm.install("ksh"):
            self.error('ksh is needed for the test to be run')
        if detected_distro.name == "Ubuntu":
            if not smm.check_installed("python-paramiko") and not \
                                      smm.install("python-paramiko"):
                self.error('python-paramiko is needed for the test to be run')
            ubuntu_url = self.params.get('ubuntu_url', default=None)
            debs = self.params.get('debs', default=None)
            for deb in debs:
                deb_url = os.path.join(ubuntu_url, deb)
                deb_install = self.fetch_asset(deb_url, expire='7d')
                shutil.copy(deb_install, self.srcdir)
                process.system("dpkg -i %s/%s" % (self.srcdir, deb),
                               ignore_status=True, sudo=True)
        else:
            url = self.params.get('url', default=None)
            rpm_install = self.fetch_asset(url, expire='7d')
            shutil.copy(rpm_install, self.srcdir)
            os.chdir(self.srcdir)
            process.run('chmod +x ibmtools')
            process.run('./ibmtools --install --managed')
        self.hmc_ip = self.params.get("hmc_ip", '*', default=None)
        self.hmc_pwd = self.params.get("hmc_pwd", '*', default=None)
        self.hmc_username = self.params.get("hmc_username", '*', default=None)
        self.lpar = self.params.get("lpar", '*', default=None)
        self.server = self.params.get("server", '*', default=None)
        self.count = int(self.params.get("count", '*', default="1"))
        self.lpar_profile_name = self.params.get("lpar_profile_name", '*',
                                                 default=None)
        self.slot_num = self.params.get("slot_num", '*', default=None)
        self.vios_name = self.params.get("vios_name", '*', default=None)
        self.sriov_port = self.params.get("sriov_port", '*', default=None)
        self.sriov_adapter_id = self.params.get("sriov_adapter_id", '*',
                                                default=None)
        self.bandwidth = self.params.get("bandwidth", '*', default=None)
        self.login(self.hmc_ip, self.hmc_username, self.hmc_pwd)
        self.run_command("uname -a")
        cmd = 'lssyscfg -m ' + self.server + \
              ' -r lpar --filter lpar_names=' + self.lpar + \
              ' -F lpar_id'
        self.lpar_id = self.run_command(cmd)[-1]
        cmd = 'lssyscfg -m ' + self.server + \
              ' -r lpar --filter lpar_names=' + self.vios_name + \
              ' -F lpar_id'
        self.vios_id = self.run_command(cmd)[-1]
        self.backing_devices = "sriov/%s/%s/%s/%s/%s"\
                               % (self.vios_name, self.vios_id,
                                  self.sriov_adapter_id, self.sriov_port,
                                  self.bandwidth)

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

    def test(self):
        '''
        Start rsct services and performs add and remove operations
        of Network virtualized ports
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

        for _ in range(self.count):
            self.network_virtualization_backing_device_add()
            self.network_virtualization_backing_device_remove()

    def network_virtualization_backing_device_remove(self):
        '''
        Network virtualized port remove operation
        '''
        self.changehwres(self.server, 'r', self.lpar_id, self.slot_num,
                         self.backing_devices, 'remove')
        output = self.listhwres(self.server, self.lpar)
        # To Do: parse the output for pass/fail
        if 'slot_num=%s' % self.slot_num in str(output):
            self.log.debug(output)
            self.fail("lshwres still lists the Network virtualized interface \
                       after remove operation")

    def network_virtualization_backing_device_add(self):
        '''
        Network virtualized port add operation
        '''
        self.changehwres(self.server, 'a', self.lpar_id, self.slot_num,
                         self.backing_devices, 'add')
        output = self.listhwres(self.server, self.lpar)
        for device in output:
            logical_port_id = self.list_backing_devices(self.server,
                                                        self.vios_name)
            if device not in logical_port_id:
                self.fail("Failed to add a  Backing device")

    def listhwres(self, server, lpar):
        cmd = 'lshwres -r virtualio -m  %s --rsubtype vnic --level lpar --filter \
               "lpar_names=%s" -F slot_num,backing_device_states' \
               % (server, lpar)
        try:
            output = self.run_command(cmd)
            print output
            backing_dev_list = []
            for i in output:
                if i.startswith('%s,') % self.slot_num:
                    for j in i.split(',')[1:]:
                        backing_dev_list.append(j.split('/')[1])
                    print backing_dev_list
        except CommandFailed as cf:
            self.log.debug(str(cf))
            self.fail("lshwres operation failed ")
        return backing_dev_list

    def changehwres(self, server, operation, lpar_id, slot_num,
                    backing_devices, msg):
        if operation == 'a':
            cmd = 'chhwres -r virtualio --rsubtype vnic -o s -m %s -s %s --id %s \
                   -a backing_devices+=%s' % (server, slot_num,
                                              lpar_id, backing_devices)
        else:
            cmd = 'chhwres -r virtualio --rsubtype vnic -o s -m %s -s %s --id %s \
                   -a backing_devices-=%s' % (server, slot_num,
                                              lpar_id, backing_devices)
        try:
            cmd = self.run_command(cmd)
        except CommandFailed as cf:
            self.log.debug(str(cf))
            self.fail("Network virtualization %s operation failed" % msg)

    def list_backing_devices(self, server, vios_name):
        cmd = 'lshwres -r virtualio --rsubtype vnicbkdev -m %s --filter \
               lpar_names=%s  -F logical_port_id' % (server, vios_name)
        try:
            logical_port_id = self.run_command(cmd)
            print logical_port_id
        except CommandFailed as cf:
            self.log.debug(str(cf))
            self.fail("Failed to get list of backing devices")
        return logical_port_id

    def tearDown(self):
        if self.pxssh.isalive():
            self.pxssh.terminate()


if __name__ == "__main__":
    main()
