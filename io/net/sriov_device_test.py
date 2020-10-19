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
# Author: Bismruti Bidhibrata Pattjoshi <bbidhibr@in.ibm.com>
# Authors: Abdul haleem <abdhalee@linux.vnet.ibm.com>

'''
Tests for Sriov logical device
'''

import netifaces
from avocado import Test
from avocado.utils import process
from avocado.utils.network.hosts import LocalHost
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.software_manager import SoftwareManager
from avocado.utils.ssh import Session


class NetworkSriovDevice(Test):
    '''
    adding and deleting logical sriov device through
    HMC.
    '''
    def setUp(self):
        '''
        set up required packages and gather necessary test inputs
        '''
        smm = SoftwareManager()
        packages = ['src', 'rsct.basic', 'rsct.core.utils',
                    'rsct.core', 'DynamicRM', 'powerpc-utils']
        for pkg in packages:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel('%s is needed for the test to be run' % pkg)
        self.hmc_ip = self.get_mcp_component("HMCIPAddr")
        if not self.hmc_ip:
            self.cancel("HMC IP not got")
        self.hmc_pwd = self.params.get("hmc_pwd", '*', default=None)
        self.hmc_username = self.params.get("hmc_username", '*', default=None)
        self.lpar = self.get_partition_name("Partition Name")
        if not self.lpar:
            self.cancel("LPAR Name not got from lparstat command")
        self.session = Session(self.hmc_ip, user=self.hmc_username,
                               password=self.hmc_pwd)
        if not self.session.connect():
            self.cancel("failed connetion to HMC")
        cmd = 'lssyscfg -r sys  -F name'
        output = self.session.cmd(cmd)
        self.server = ''
        for line in output.stdout_text.splitlines():
            if line in self.lpar:
                self.server = line
                break
        if not self.server:
            self.cancel("Managed System not got")
        self.sriov_adapter = self.params.get('sriov_adapter',
                                             '*', default=None).split(' ')
        self.sriov_port = self.params.get('sriov_port', '*',
                                          default=None).split(' ')
        self.ipaddr = self.params.get('ipaddr', '*', default="").split(' ')
        self.netmask = self.params.get('netmasks', '*', default="").split(' ')
        self.peer_ip = self.params.get('peer_ip', '*', default="").split(' ')
        self.mac_id = self.params.get('mac_id',
                                      default="02:03:03:03:03:01").split(' ')
        self.mac_id = [mac.replace(':', '') for mac in self.mac_id]
        self.local = LocalHost()

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

    def test_add_logical_device(self):
        '''
        test to create logical sriov device
        '''
        for slot, port, mac, ipaddr, netmask, peer_ip in zip(self.sriov_adapter,
                                                             self.sriov_port,
                                                             self.mac_id, self.ipaddr,
                                                             self.netmask, self.peer_ip):
            self.device_add_remove(slot, port, mac, '', 'add')
            if not self.list_device(mac):
                self.fail("failed to list logical device after add operation")
            device = self.find_device(mac)
            networkinterface = NetworkInterface(device, self.local)
            networkinterface.add_ipaddr(ipaddr, netmask)
            networkinterface.bring_up()
            if networkinterface.ping_check(peer_ip, count=5) is not None:
                self.fail("ping check failed")

    def test_remove_logical_device(self):
        """
        test to remove logical device
        """
        for mac, slot in zip(self.mac_id, self.sriov_adapter):
            logical_port_id = self.get_logical_port_id(mac)
            self.device_add_remove(slot, '', '', logical_port_id, 'remove')
            if self.list_device(mac):
                self.fail("still list logical device after remove operation")

    def device_add_remove(self, slot, port, mac, logical_id, operation):
        """
        add and remove operation of logical devices
        """
        cmd = "lshwres -m %s -r sriov --rsubtype adapter -F phys_loc:adapter_id" \
              % (self.server)
        output = self.session.cmd(cmd)
        for line in output.stdout_text.splitlines():
            if slot in line:
                adapter_id = line.split(':')[-1]

        if operation == 'add':
            cmd = 'chhwres -r sriov -m %s --rsubtype logport \
                  -o a -p %s -a \"adapter_id=%s,phys_port_id=%s, \
                  logical_port_type=eth,mac_addr=%s\" ' \
                  % (self.server, self.lpar, adapter_id,
                     port, mac)
        else:
            cmd = 'chhwres -r sriov -m %s --rsubtype logport \
                  -o r -p %s -a \"adapter_id=%s,logical_port_id=%s\" ' \
                  % (self.server, self.lpar, adapter_id, logical_id)
        cmd = self.session.cmd(cmd)
        if cmd.exit_status != 0:
            self.log.debug(cmd.stderr)
            self.fail("sriov logical device %s operation \
                       failed" % operation)

    def get_logical_port_id(self, mac):
        """
        findout logical device port id
        """
        cmd = "lshwres -r sriov --rsubtype logport -m  %s \
               --level eth | grep %s | grep %s" \
               % (self.server, self.lpar, mac)
        output = self.session.cmd(cmd)
        logical_port_id = output.stdout_text.split(',')[6].split('=')[-1]
        return logical_port_id

    @staticmethod
    def find_device(mac_addrs):
        """
        Finds out the latest added sriov logical device
        """
        mac = ':'.join(mac_addrs[i:i+2] for i in range(0, 12, 2))
        devices = netifaces.interfaces()
        for device in devices:
            if mac in netifaces.ifaddresses(device)[17][0]['addr']:
                return device
        return ''

    def list_device(self, mac):
        """
        list the sriov logical device
        """
        cmd = 'lshwres -r sriov --rsubtype logport -m  ltcfleet2 \
              --level eth --filter \"lpar_names=%s\" ' % self.lpar
        output = self.session.cmd(cmd)
        if mac in output.stdout_text:
            return True
        return False

    def tearDown(self):
        self.session.quit()
