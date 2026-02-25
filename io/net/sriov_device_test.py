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
import time
from avocado import Test
from avocado.utils import process
from avocado.utils.ssh import Session
from avocado.utils import genio
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.network.hosts import LocalHost


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
        packages = ['src', 'rsct.basic', 'rsct.core.utils', 'NetworkManager',
                    'rsct.core', 'DynamicRM', 'powerpc-utils']
        for pkg in packages:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel('%s is needed for the test to be run' % pkg)
        self.hmc_ip = self.get_mcp_component("HMCIPAddr")
        if not self.hmc_ip:
            self.cancel("HMC IP not got")
        self.hmc_pwd = self.params.get("hmc_pwd", default=None)
        self.hmc_username = self.params.get("hmc_username", default=None)
        self.lpar = self.get_partition_name("Partition Name")
        if not self.lpar:
            self.cancel("LPAR Name not got from lparstat command")
        self.session = Session(self.hmc_ip, user=self.hmc_username,
                               password=self.hmc_pwd)
        if not self.session.connect():
            self.cancel("failed connection to HMC")
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
                                             default=None).split(' ')
        self.sriov_port = self.params.get('sriov_port',
                                          default=None).split(' ')
        self.sriov_roce = self.params.get('sriov_roce', default=False)
        self.max_sriov_port = self.params.get('max_sriov_ports')
        self.ipaddr = self.params.get('ipaddr', default='').split(' ')
        self.netmask = self.params.get('netmasks', default="").split(' ')

        if self.params.get('netmasks'):
            self.prefix = self.netmask_to_cidr(self.netmask[0])
        self.peer_ip = self.params.get(
            'peer_ips', default="").split(' ')
        self.mac_id = self.params.get('mac_id',
                                      default="02:03:03:03:03:01").split(' ')
        self.mac_id = [mac.replace(':', '') for mac in self.mac_id]
        self.migratable = self.params.get('migratable', default=False)
        # Convert boolean to integer for HMC command compatibility
        # HMC requires integer values (0 or 1), not boolean (True/False)
        if isinstance(self.migratable, bool):
            self.migratable = 1 if self.migratable else 0

        self.backup_veth_vnetwork = self.params.get(
            'backup_veth_vnetwork', default="")
        self.vnic_sriov_adapter = self.params.get(
            'vnic_sriov_adapter', default="")

        if (not self.backup_veth_vnetwork and
                not self.vnic_sriov_adapter and self.sriov_adapter):
            self.local = LocalHost()
        else:
            self.backup_device_type = "veth"
            if not self.backup_veth_vnetwork:
                self.backup_device_type = "vnic"
                if not self.vnic_sriov_adapter:
                    self.cancel("Please provide veth or vnic inputs")
            if 'vnic' in self.backup_device_type:
                self.vnic_port_id = self.params.get(
                    'vnic_port_id', default=None)
                self.vnic_adapter_id = self.get_adapter_id(
                    self.vnic_sriov_adapter)
                self.priority = self.params.get(
                    'failover_priority', default='50')
                self.max_capacity = self.params.get(
                    'max_capacity', default='10')
                self.capacity = self.params.get('capacity', default='2')
                self.vios_name = self.params.get('vios_name', default=None)
                cmd = ('lssyscfg -m %s -r lpar --filter '
                       'lpar_names=%s -F lpar_id' % (
                           self.server, self.vios_name))
                self.vios_id = self.session.cmd(cmd).stdout_text.split()[0]
                self.backup_vnic_backing_device = (
                    'sriov/%s/%s/%s/%s/%s/%s/%s' % (
                        self.vios_name, self.vios_id,
                        self.vnic_adapter_id, self.vnic_port_id,
                        self.capacity, self.priority, self.max_capacity))
        self.local = LocalHost()

    @staticmethod
    def netmask_to_cidr(netmask):
        return sum([bin(int(bits)).count("1")
                    for bits in netmask.split(".")])

    def get_adapter_id(self, slot):
        cmd = ("lshwres -m %s -r sriov --rsubtype adapter "
               "-F phys_loc:adapter_id" % (self.server))
        output = self.session.cmd(cmd)
        for line in output.stdout_text.splitlines():
            if slot in line:
                return line.split(':')[-1]
        self.cancel("adapter not found at slot %s", slot)

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
        if self.migratable:
            self.cancel("Test unsupported")
        if self.max_sriov_port:
            self.cancel("Test unsupported")
        for slot, port, mac, ipaddr, netmask, peer_ip in zip(
                self.sriov_adapter, self.sriov_port, self.mac_id,
                self.ipaddr, self.netmask, self.peer_ip):
            self.device_add_remove(slot, port, mac, '', 'add')
            if not self.list_device(mac):
                self.fail("failed to list logical device after add operation")
            device = self.find_device(mac)
            if not device:
                self.fail("MAC address differs in linux")
            networkinterface = NetworkInterface(device, self.local)
            networkinterface.add_ipaddr(ipaddr, netmask)
            networkinterface.bring_up()
            if networkinterface.ping_check(peer_ip, count=5) is not None:
                self.fail("ping check failed")

    def test_add_migratable_sriov(self):
        '''
        test to create Migratable sriov device
        '''
        if not self.migratable:
            self.cancel("Test unsupported")

        for slot, port, mac, ipaddr, netmask, peer_ip in zip(
                self.sriov_adapter, self.sriov_port, self.mac_id,
                self.ipaddr, self.netmask, self.peer_ip):
            self.device_add_remove(slot, port, mac, '', 'add')
            if not self.list_device(mac):
                self.fail("failed to list Migratable logical device "
                          "after add operation")
            try:
                bond_device = self.get_hnv_bond(mac)
                if not bond_device:
                    self.fail("failed to create hnv bond device")

                ret = process.run(
                    'nmcli c mod id %s ipv4.method manual '
                    'ipv4.address %s/%s' % (
                        bond_device, ipaddr, self.prefix),
                    ignore_status=True)
                if ret.exit_status:
                    self.fail(
                        "nmcli ip configuration for hnv bond fail "
                        "with %s" % (ret.exit_status))
                ret = process.run('nmcli c up %s' %
                                  bond_device, ignore_status=True)
                if ret.exit_status:
                    self.fail("hnv bond ip bring up fail with %s"
                              % (ret.exit_status))
                time.sleep(10)
                networkinterface = NetworkInterface(bond_device, self.local)
                if networkinterface.ping_check(
                        peer_ip, count=5) is not None:
                    self.fail("ping check failed for hnv bond device")
            except Exception:
                # Cleanup: Remove the created SR-IOV device before
                # failing
                try:
                    logical_port_id = self.get_logical_port_id(mac)
                    self.device_add_remove(
                        slot, '', '', logical_port_id, 'remove')
                except Exception as cleanup_error:
                    self.log.warning(
                        "Failed to cleanup device during exception: %s",
                        cleanup_error)
                raise

    def test_remove_migratable_sriov(self):
        '''
        test to remove Migratable sriov device
        '''
        if not self.migratable:
            self.cancel("Test unsupported")
        for mac, slot in zip(self.mac_id, self.sriov_adapter):
            bond_device = self.get_hnv_bond(mac)
            if not bond_device:
                self.fail(
                    "failed to find hnv bond device for MAC %s" % mac)
            ret = process.run('nmcli c down %s' %
                              bond_device, ignore_status=True)
            if ret.exit_status:
                self.fail("hnv bond ip bring down fail with %s"
                          % (ret.exit_status))
            ret = process.run('nmcli c del %s' %
                              bond_device, ignore_status=True)
            if ret.exit_status:
                self.fail("hnv bond delete fail with %s"
                          % (ret.exit_status))
            logical_port_id = self.get_logical_port_id(mac)
            self.device_add_remove(slot, '', '', logical_port_id, 'remove')
            if self.list_device(mac):
                self.fail("fail to remove migratable logical device")

    def test_remove_logical_device(self):
        """
        test to remove logical device
        """
        if self.migratable:
            self.cancel("Test unsupported")

        if self.max_sriov_port:
            self.cancel("Test unsupported")

        for mac, slot in zip(self.mac_id, self.sriov_adapter):
            logical_port_id = self.get_logical_port_id(mac)
            self.device_add_remove(slot, '', '', logical_port_id, 'remove')
            if self.list_device(mac):
                self.fail(
                    "still list logical device after remove operation")

    def device_add_remove(self, slot, port, mac, logical_id, operation):
        """
        Add and remove operation of logical devices (SR-IOV and HNV)

        For HNV (Hybrid Network Virtualization):
        - Requires migratable=True
        - Requires backup device (veth or vnic)
        - Creates bonded interface automatically

        Args:
            slot: Physical slot location of SR-IOV adapter
            port: Physical port ID on the adapter
            mac: MAC address for the logical port
            logical_id: Logical port ID (for remove operation)
            operation: 'add' or 'remove'
        """

        adapter_id = self.get_adapter_id(slot)
        backup_device = ''

        # Non-migratable SR-IOV (standard SR-IOV without backup)
        if (not self.backup_veth_vnetwork and
                not self.vnic_sriov_adapter and self.sriov_adapter):
            if operation == 'add':
                if mac is None:
                    cmd = 'chhwres -r sriov -m %s --rsubtype logport \
                    -o a -p %s -a \"adapter_id=%s,phys_port_id=%s, \
                    logical_port_type=eth,migratable=%s%s\" ' \
                    % (self.server, self.lpar, adapter_id,
                       port, self.migratable, backup_device)
                else:
                    if not self.sriov_roce:
                        cmd = 'chhwres -r sriov -m %s --rsubtype logport \
                        -o a -p %s -a \"adapter_id=%s,phys_port_id=%s, \
                        logical_port_type=eth,mac_addr=%s,migratable=%s%s\" ' \
                        % (self.server, self.lpar, adapter_id,
                           port, mac, self.migratable, backup_device)
                    else:
                        cmd = 'chhwres -r sriov -m %s --rsubtype logport \
                        -o a -p %s -a \"adapter_id=%s,phys_port_id=%s, \
                        logical_port_type=roce,mac_addr=%s,migratable=%s%s\" ' \
                        % (self.server, self.lpar, adapter_id,
                           port, mac, self.migratable, backup_device)
            else:
                cmd = 'chhwres -r sriov -m %s --rsubtype logport \
                      -o r -p %s -a \"adapter_id=%s,logical_port_id=%s\" ' \
                      % (self.server, self.lpar, adapter_id, logical_id)

        # Migratable SR-IOV / HNV (with veth or vnic backup)
        else:
            if not self.migratable:
                self.fail("Migratable must be set to True for HNV "
                          "configuration")

            if self.backup_device_type:
                if 'veth' in self.backup_device_type:
                    if not self.backup_veth_vnetwork:
                        self.fail("backup_veth_vnetwork required for "
                                  "veth backup device")
                    backup_device = (
                        ',backup_device_type=%s,backup_veth_vnetwork=%s' % (
                            self.backup_device_type,
                            self.backup_veth_vnetwork))
                    self.log.info(
                        "Configuring HNV with veth backup on network: %s",
                        self.backup_veth_vnetwork)
                else:
                    if not self.backup_vnic_backing_device:
                        self.fail("backup_vnic_backing_device required "
                                  "for vnic backup device")
                    backup_device = (
                        ',backup_device_type=%s,'
                        'backup_vnic_backing_device=%s' % (
                            self.backup_device_type,
                            self.backup_vnic_backing_device))
                    self.log.info(
                        "Configuring HNV with vnic backup: %s",
                        self.backup_vnic_backing_device)

            if operation == 'add':
                if not mac:
                    self.fail("MAC address required for HNV add operation")
                cmd = 'chhwres -r sriov -m %s --rsubtype logport \
                      -o a -p %s -a \"adapter_id=%s,phys_port_id=%s, \
                      logical_port_type=eth,mac_addr=%s,migratable=%s%s\" ' \
                      % (self.server, self.lpar, adapter_id,
                         port, mac, self.migratable, backup_device)
            else:
                cmd = 'chhwres -r sriov -m %s --rsubtype logport \
                      -o r -p %s -a \"adapter_id=%s,logical_port_id=%s\" ' \
                      % (self.server, self.lpar, adapter_id, logical_id)

        # Execute command
        self.log.info("Executing HMC command for %s operation",
                      operation)
        self.log.debug("Command: %s", cmd)
        result = self.session.cmd(cmd)

        if result.exit_status != 0:
            self.log.error("HMC command failed with exit status: %s",
                           result.exit_status)
            self.log.error("stderr: %s", result.stderr)
            self.log.error("stdout: %s", result.stdout_text)
            self.fail(
                f"SR-IOV logical device {operation} operation failed "
                f"with error: {result.stdout_text}")

        self.log.info("SR-IOV logical device %s operation completed "
                      "successfully", operation)

    def get_logical_port_id(self, mac):
        """
        find out logical device port id
        """
        if not self.sriov_roce:
            cmd = ("lshwres -r sriov --rsubtype logport -m  %s "
                   "--level eth | grep %s | grep %s" % (
                       self.server, self.lpar, mac))
        else:
            cmd = ("lshwres -r sriov --rsubtype logport -m  %s "
                   "--level roce | grep %s | grep %s" % (
                       self.server, self.lpar, mac))
        output = self.session.cmd(cmd)
        logical_port_id = output.stdout_text.split(',')[6].split('=')[-1]
        return logical_port_id

    def get_hnv_bond(self, mac):
        """
        Get the newly created hnv bond interface name
        """
        output = genio.read_one_line("/sys/class/net/bonding_masters").split()
        for bond in output:
            if mac in netifaces.ifaddresses(
                    bond)[17][0]['addr'].replace(':', ''):
                return bond
        self.fail("Test fail due to mac address mismatch")

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
        if not self.sriov_roce:
            cmd = ('lshwres -r sriov --rsubtype logport -m %s '
                   '--level eth --filter \"lpar_names=%s\" ' % (
                       self.server, self.lpar))
        else:
            cmd = ('lshwres -r sriov --rsubtype logport -m %s '
                   '--level roce --filter \"lpar_names=%s\" ' % (
                       self.server, self.lpar))
        output = self.session.cmd(cmd)
        if mac in output.stdout_text:
            return True
        return False

    def test_add_max_logical_devices(self):
        '''
        test to create logical sriov devices
        '''
        if self.migratable:
            self.cancel("Test unsupported")

        if not self.max_sriov_port:
            self.cancel("Test unsupported")

        if self.max_sriov_port:
            for i in range(self.max_sriov_port):
                for slot, port in zip(self.sriov_adapter, self.sriov_port):
                    self.device_add_remove(slot, port, mac=None,
                                           logical_id='',
                                           operation='add')
                if not self.list_device(mac=''):
                    self.fail(
                        "failed to list logical device after add operation")

    def test_remove_max_logical_devices(self):
        '''
        test to remove logical sriov devices
        '''
        if self.migratable:
            self.cancel("Test unsupported")

        if not self.max_sriov_port:
            self.cancel("Test unsupported")

        if self.max_sriov_port:
            for i in range(self.max_sriov_port):
                for slot, port in zip(self.sriov_adapter,
                                      self.sriov_port):
                    logical_port_id = self.get_logical_port_id(mac='mac')
                    self.device_add_remove(slot, port, '',
                                           logical_port_id, 'remove')
                if self.list_device(logical_port_id):
                    self.fail(
                        "still list logical device after remove operation")

    def tearDown(self):
        if hasattr(self, 'session'):
            self.session.quit()
