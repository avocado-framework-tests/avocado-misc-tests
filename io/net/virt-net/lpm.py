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

'''
Tests for Live Partition Mobility
'''

import time
from avocado import Test
from avocado.utils import process
from avocado.utils import distro
from avocado.utils import wait
from avocado.utils import dmesg
from avocado.utils.software_manager import SoftwareManager
from avocado.utils.ssh import Session
from avocado.utils.process import CmdError
from avocado import skipIf, skipUnless

IS_POWER_NV = 'PowerNV' in open('/proc/cpuinfo', 'r').read()
IS_KVM_GUEST = 'qemu' in open('/proc/cpuinfo', 'r').read()


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
        self.using_peer = False
        if (self.params.get("lpar", default='')
                and self.params.get("lpar_ip", default='')):
            self.lpar = self.params.get("lpar", default='')
            self.log.info("Migrating %s partition", self.lpar)
            self.lpar_ip = self.params.get("lpar_ip", default='')
            self.lpar_user = self.params.get("lpar_user", default='root')
            self.lpar_pwd = self.params.get("lpar_pwd", "*",
                                            default='********')
            self.peer_session = Session(self.lpar_ip, user=self.lpar_user,
                                        password=self.lpar_pwd)
            if not self.peer_session.connect():
                self.cancel("failed connecting to peer lpar")
            self.using_peer = True
        else:
            self.lpar = self.get_partition_name("Partition Name")
            if not self.lpar:
                self.cancel("LPAR Name not got from lparstat command")
            self.lpar_ip = self.get_mcp_component("MNName")
            if not self.lpar_ip:
                self.cancel("LPAR IP not got from lsrsrc command")
        self.rsct_service_start()

        self.hmc_ip = self.get_mcp_component("HMCIPAddr")
        if not self.hmc_ip:
            self.cancel("HMC IP not got from lsrsrc command")
        self.hmc_user = self.params.get("hmc_username", default='hscroot')
        self.hmc_pwd = self.params.get("hmc_pwd", '*', default='********')
        self.options = self.params.get("options", default='')
        self.net_device_type = self.params.get("net_device_type", default='')
        self.session = Session(self.hmc_ip, user=self.hmc_user,
                               password=self.hmc_pwd)
        if not self.session.connect():
            self.cancel("failed connecting to HMC")
        cmd = 'lssyscfg -r sys -F name'
        output = self.session.cmd(cmd)
        self.server = ''
        for line in output.stdout_text.splitlines():
            if line in self.lpar:
                self.server = line
                break
        if not self.server:
            self.cancel("Managed System not got")

        self.remote_server = self.params.get("remote_server", default=None)
        if not self.remote_server:
            self.cancel("No Remote Server specified for LPM")

        if 'back' in str(self.name.name):
            current_server = self.remote_server
        else:
            current_server = self.server

        if not self.is_lpar_in_server(current_server, self.lpar):
            self.cancel("%s not in %s" % (self.lpar, current_server))

        if 'vnic' in self.net_device_type:
            self.slot_num = str(self.params.get("slot_num", '*', default=3))
            if int(self.slot_num) < 3 or int(self.slot_num) > 2999:
                self.cancel("Slot invalid. Valid range: 3 - 2999")

            self.bandwidth = str(self.params.get("bandwidth", default=2))

            self.vios_name = self.params.get("vios_names", '*',
                                             default=None).split(' ')
            self.vios_id = []
            for vios_name in self.vios_name:
                self.vios_id.append(self.get_lpar_id(self.server, vios_name))
            self.remote_vios_name = self.params.get("remote_vios_names", '*',
                                                    default=None).split(' ')
            self.remote_vios_id = []
            for vios_name in self.remote_vios_name:
                self.remote_vios_id.append(self.get_lpar_id(self.remote_server,
                                                            vios_name))

            for vios in self.vios_id:
                self.set_msp(self.server, vios)
            for vios in self.remote_vios_id:
                self.set_msp(self.remote_server, vios)

            self.adapters = self.params.get("sriov_adapters",
                                            default='').split(' ')
            self.remote_adapters = self.params.get("remote_sriov_adapters",
                                                   default='').split(' ')
            self.ports = self.params.get("sriov_ports",
                                         default='').split(' ')
            self.remote_ports = self.params.get("remote_sriov_ports",
                                                default='').split(' ')

            self.adapter_id = []
            for adapter in self.adapters:
                self.adapter_id.append(
                    self.get_adapter_id(self.server, adapter))
            self.remote_adapter_id = []
            for adapter in self.remote_adapters:
                self.remote_adapter_id.append(
                    self.get_adapter_id(self.remote_server, adapter))
        dmesg.clear_dmesg()

    @staticmethod
    def get_mcp_component(component):
        '''
        probes IBM.MCP class for mentioned component and returns it.
        '''
        for line in process.system_output('lsrsrc IBM.MCP %s' % component,
                                          ignore_status=True, shell=True,
                                          sudo=True).decode("utf-8") \
                                                    .splitlines():
            if component in line:
                return line.split()[-1].strip('{}\"')
        return ''

    @staticmethod
    def get_partition_name(component):
        '''
        get partition name from lparstat -i
        '''

        for line in process.system_output('lparstat -i', ignore_status=True,
                                          shell=True,
                                          sudo=True).decode("utf-8") \
                                                    .splitlines():
            if component in line:
                return line.split(':')[-1].strip()
        return ''

    def rsct_service_start(self):
        '''
        Running rsct services which is necessary for Network
        virtualization tests
        '''
        try:
            for svc in ["rsct", "rsct_rm"]:
                cmd = 'startsrc -g %s' % svc
                if self.using_peer:
                    self.peer_session.cmd(cmd)
                else:
                    process.run(cmd, shell=True, sudo=True)
        except CmdError as details:
            self.log.debug(str(details))
            self.fail("Starting service %s failed", svc)

        try:
            cmd = "lssrc -a"
            output = ""
            if self.using_peer:
                output = self.peer_session.cmd(cmd).stdout_text
            else:
                output = process.system_output(cmd, ignore_status=True,
                                               shell=True, sudo=True).decode("utf-8")
            if "inoperative" in output:
                self.fail("Failed to start the rsct and rsct_rm services")
        except CmdError as details:
            self.log.debug(str(details))
            self.fail("Command lssrc -a failed")

    def is_RMC_active(self, server):
        '''
        Get the state of the RMC connection for the given parition
        '''
        cmd = "diagrmc -m %s --ip %s -p %s --autocorrect" % (
            server, self.lpar_ip, self.lpar)
        output = self.session.cmd(cmd)
        for line in output.stdout_text.splitlines():
            if "%s has RMC connection." % self.lpar_ip in line:
                return True
        return False

    def rmc_service_start(self, server):
        '''
        Start RMC services which is needed for LPM migration
        '''
        try:
            for svc in ["-z", "-A", "-p"]:
                cmd = '/opt/rsct/bin/rmcctrl %s' % svc
                if self.using_peer:
                    self.peer_session.cmd(cmd)
                else:
                    process.run(cmd, shell=True, sudo=True)
        except CmdError as details:
            self.log.debug(str(details))
            self.fail("Starting service %s failed", svc)

        if not wait.wait_for(self.is_RMC_active(server), timeout=60):
            try:
                cmd1 = '/usr/sbin/rsct/install/bin/recfgct'
                cmd2 = '/opt/rsct/bin/rmcctrl -p'
                if self.using_peer:
                    self.peer_session.cmd(cmd1)
                    self.peer_session.cmd(cmd2)
                else:
                    process.run(cmd1, shell=True, sudo=True)
                    process.run(cmd2, shell=True, sudo=True)
            except CmdError as details:
                self.log.debug(str(details))
                self.fail("Command recfgct or rmcctrl has failed", svc)
            if not wait.wait_for(self.is_RMC_active(server), timeout=300):
                self.fail("ERROR : RMC connection is down !!")

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
        self.session.cmd(cmd)

    def do_migrate(self, server, remote_server, lpar, params):
        '''
        Migrate the LPAR from server to remote server, with additional
        params specified.
        '''
        if not self.is_RMC_active(server):
            self.warn("RMC service is inactive..!")
            self.rmc_service_start(server)
        cmd = "migrlpar -o m -m %s -t %s -p %s %s" % (server,
                                                      remote_server,
                                                      lpar, params)
        if self.options:
            cmd = "%s %s" % (cmd, self.options)
        self.log.debug(self.session.cmd(cmd).stdout_text)
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
        output = self.session.cmd(cmd).stdout_text
        if "%s," % lpar in output:
            return True
        return False

    def get_adapter_id(self, server, loc_code):
        '''
        Gets the adapter id of given location code on the server.
        '''
        cmd = 'lshwres -m %s -r sriov --rsubtype adapter -F \
              phys_loc:adapter_id' % server
        adapter_id_output = self.session.cmd(cmd)
        for line in adapter_id_output.stdout_text.splitlines():
            if str(loc_code) in line:
                return line.split(':')[1]
        return ''

    def get_lpar_id(self, server, lpar_name):
        '''
        Gets the lpar id of given lpar on the server.
        '''
        cmd = "lssyscfg -m %s -r lpar --filter lpar_names=%s \
              -F lpar_id" % (server, lpar_name)
        return self.session.cmd(cmd).stdout_text

    def form_virt_net_options(self, remote=''):
        '''
        Form the vnic_mappings param based on the adapters' details
        provided.
        '''
        if remote:
            cmd = []
            for index in range(0, len(self.adapters)):
                l_cmd = []
                for param in [self.slot_num, 'ded', self.vios_name[index],
                              self.vios_id[index], self.adapter_id[index],
                              self.ports[index], self.bandwidth,
                              self.remote_adapter_id[index],
                              self.remote_ports[index]]:
                    l_cmd.append(param)
                cmd.append("/".join(l_cmd))
        else:
            cmd = []
            for index in range(0, len(self.adapters)):
                l_cmd = []
                for param in [self.slot_num, 'ded',
                              self.remote_vios_name[index],
                              self.remote_vios_id[index],
                              self.remote_adapter_id[index],
                              self.remote_ports[index], self.bandwidth,
                              self.adapter_id[index], self.ports[index]]:
                    l_cmd.append(param)
                cmd.append("/".join(l_cmd))

        return " -i \"vnic_mappings=\\\"%s\\\"\" " % ",".join(cmd)

    def check_dmesg_error(self):
        """
        check for dmesg error
        """
        self.log.info("Gathering kernel errors if any")
        try:
            dmesg.collect_errors_by_level()
        except Exception as exc:
            self.log.info(exc)
            self.fail("test failed,check dmesg log in debug log")

    def test_migrate(self):
        '''
        Migrate the LPAR from given server to remote server.
        '''
        cmd = ''
        if 'vnic' in self.net_device_type:
            cmd = self.form_virt_net_options()
        self.do_migrate(self.server, self.remote_server, self.lpar, cmd)
        self.check_dmesg_error()

    def test_migrate_back(self):
        '''
        Migrate the LPAR from given remote server back to server.
        '''
        cmd = ''
        if 'vnic' in self.net_device_type:
            cmd = self.form_virt_net_options('remote')
        self.do_migrate(self.remote_server, self.server, self.lpar, cmd)
        self.check_dmesg_error()

    def tearDown(self):
        self.session.quit()
        if self.using_peer:
            self.peer_session.quit()
