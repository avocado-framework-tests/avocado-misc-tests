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
# Author: Narasimhan V <sim@linux.vnet.ibm.com>

'''
Tests for Network virtualized device
'''

import os
import time
import shutil
import netifaces  # pylint: disable=import-error
from avocado import Test
from avocado.utils import process
from avocado.utils import distro
from avocado.utils import dmesg
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils.process import CmdError
from avocado.utils.network.exceptions import NWException
from avocado import skipIf, skipUnless
from avocado.utils import genio
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.network.hosts import LocalHost
from avocado.utils.ssh import Session
from avocado.utils import wait
from avocado.utils import linux
from pexpect import pxssh  # pylint: disable=import-error
import re
from avocado.utils.network.hosts import RemoteHost

IS_POWER_NV = 'PowerNV' in open('/proc/cpuinfo', 'r').read()
IS_KVM_GUEST = 'qemu' in open('/proc/cpuinfo', 'r').read()


class NetworkVirtualization(Test):

    '''
    Adding and deleting Network Virtualized devices from the vios
    Performs adding and deleting of Backing devices
    Performs HMC failover for Network Virtualized device
    Performs driver unbind and bind for Network virtualized device
    Performs Client initiated failover for Network Virtualized device
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
        self.hmc_ip = wait.wait_for(
            lambda: self.get_mcp_component("HMCIPAddr"), timeout=30)
        if not self.hmc_ip:
            self.cancel("HMC IP not got")
        self.hmc_pwd = self.params.get("hmc_pwd", default=None)
        self.hmc_username = self.params.get("hmc_username", default=None)
        self.lpar = self.get_partition_name("Partition Name")
        if not self.lpar:
            self.cancel("LPAR Name not got from lparstat command")
        self.session_hmc = Session(self.hmc_ip, user=self.hmc_username,
                                   password=self.hmc_pwd)
        self.session_hmc.cleanup_master()
        if not self.session_hmc.connect():
            self.cancel("failed connecting to HMC")
        cmd = 'lssyscfg -r sys  -F name'
        output = self.session_hmc.cmd(cmd)
        self.server = self.params.get("manageSystem", default=None)
        if not self.server:
            self.cancel("Managed System not got")
        self.slot_num = str(self.params.get(
            "slot_num", default=None)).split(' ')
        for slot in self.slot_num:
            if int(slot) < 3 or int(slot) > 2999:
                self.cancel("Slot invalid. Valid range: 3 - 2999")
        try:
            self.original_logport = self.get_active_device_logport(
                self.slot_num[0])
        except Exception:
            self.log.info("Logport available only after interface add")
        self.vios_name = self.params.get("vios_names", default=None).split(' ')
        self.sriov_port = self.params.get(
            "sriov_ports", default=None).split(' ')
        self.backing_adapter = self.params.get(
            "sriov_adapters", default=None).split(' ')
        if len(self.sriov_port) != len(self.backing_adapter):
            self.cancel('Backing Device counts and port counts differ')
        if len(self.vios_name) != len(self.backing_adapter):
            self.cancel('Backing Device counts and vios name counts differ')
        self.backingdev_count = len(self.backing_adapter)
        self.bandwidth = self.params.get("bandwidth", default=None)
        self.vnic_priority = self.params.get("priority", default=None)
        if not self.vnic_priority:
            self.vnic_priority = [50] * len(self.backing_adapter)
        else:
            self.vnic_priority = self.vnic_priority.split(' ')
        if len(self.vnic_priority) != len(self.backing_adapter):
            self.cancel('Backing Device counts and priority counts differ')
        self.auto_failover = self.params.get("auto_failover", default=None)
        if self.auto_failover not in ['0', '1']:
            self.auto_failover = '1'
        self.vios_ip = self.params.get('vios_ip', default=None)
        self.vios_user = self.params.get('vios_username', default=None)
        self.vios_pwd = self.params.get('vios_pwd', default=None)
        self.count = int(self.params.get('count', default="1"))
        self.num_of_dlpar = int(self.params.get("num_of_dlpar", default='1'))
        self.device_ip = self.params.get('device_ip', default=None).split(' ')
        self.mac_id = self.params.get('mac_id',
                                      default="02:03:03:03:03:01").split(' ')
        self.mac_id = [mac.replace(':', '') for mac in self.mac_id]
        self.netmask = self.params.get('netmasks', default=None).split(' ')
        self.peer_ip = self.params.get('peer_ip', default=None).split(' ')
        self.peer_user = self.params.get('peer_user', default=None)
        self.peer_password = self.params.get('peer_password', default=None)
        self.host_public_ip = self.params.get('host_public_ip', default=None)
        self.host_user = self.params.get('user_name', default=None)
        self.host_password = self.params.get('host_password', default=None)
        self.is_mlx_driver = self.params.get('is_mlx_driver', default=True)
        self.tx_channel = self.params.get('tx_channel', default=10)
        self.rx_channel = self.params.get('rx_channel', default=10)
        dmesg.clear_dmesg()
        self.session_hmc.cmd("uname -a")
        cmd = 'lssyscfg -m ' + self.server + \
              ' -r lpar --filter lpar_names=' + self.lpar + \
              ' -F lpar_id'
        self.lpar_id = self.session_hmc.cmd(cmd).stdout_text.split()[0]
        self.vios_id = []
        for vios_name in self.vios_name:
            cmd = 'lssyscfg -m ' + self.server + \
                  ' -r lpar --filter lpar_names=' + vios_name + \
                  ' -F lpar_id'
            self.vios_id.append(self.session_hmc.cmd(
                cmd).stdout_text.split()[0])
        cmd = 'lshwres -m %s -r sriov --rsubtype adapter -F \
              phys_loc:adapter_id' % self.server
        adapter_id_output = self.session_hmc.cmd(cmd).stdout_text
        self.backing_adapter_id = []
        for backing_adapter in self.backing_adapter:
            for line in adapter_id_output.splitlines():
                if str(backing_adapter) in line:
                    self.backing_adapter_id.append(line.split(':')[1])
        if not self.backing_adapter_id:
            self.cancel("SRIOV adapter provided was not found.")
        self.rsct_service_start()
        if len(self.slot_num) > 1:
            if 'backing' in str(self.name.name) or \
               'failover' in str(self.name.name):
                self.cancel("this test is not needed")
        self.local = LocalHost()
        if not linux.is_os_secureboot_enabled():
            cmd = ("echo 'module ibmvnic +pt; func send_subcrq -pt'"
                   " > /sys/kernel/debug/dynamic_debug/control")
            result = process.run(cmd, shell=True, ignore_status=True)
            if result.exit_status:
                self.fail("failed to enable debug mode")
        else:
            self.log.info("Continue test with debug mode disabled")

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

    def check_slot_availability(self, slot_num):
        '''
        Checks if given slot is available(free) to be used.
        Queries all virtualio subtypes so that slots occupied by non-vNIC
        devices (vSCSI, vFC, etc.) are also detected.
        :return: True if slot available, False otherwise.
        '''
        occupied = set()
        for subtype in ('vnic', 'scsi', 'fc', 'eth'):
            cmd = 'lshwres -r virtualio -m %s --rsubtype %s --filter \
               "lpar_names=%s" -F slot_num' % (self.server, subtype,
                                               self.lpar)
            for slot in self.session_hmc.cmd(cmd).stdout_text.splitlines():
                if 'No results were found' in slot:
                    continue
                slot = slot.strip()
                if slot:
                    occupied.add(slot)
        if slot_num in occupied:
            self.log.debug("Slot %s already in use", slot_num)
            return False
        return True

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
        if "inoperative" in output.decode("utf-8"):
            self.cancel("Failed to start the rsct and rsct_rm services")

    def install_packages(self):
        '''
        Install necessary packages
        '''
        smm = SoftwareManager()
        packages = ['ksh', 'src', 'rsct.basic', 'rsct.core.utils',
                    'rsct.core', 'DynamicRM', 'powerpc-utils', 'irqbalance']
        detected_distro = distro.detect()
        if detected_distro.name == "Ubuntu":
            packages.extend(['python-paramiko'])
        self.log.info("Test is running on: %s", detected_distro.name)
        for pkg in packages:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel('%s is needed for the test to be run' % pkg)
        if detected_distro.name == "Ubuntu":
            ubuntu_url = self.params.get('ubuntu_url', default=None)
            debs = self.params.get('debs', default=None)
            for deb in debs:
                deb_url = os.path.join(ubuntu_url, deb)
                deb_install = self.fetch_asset(deb_url, expire='7d')
                shutil.copy(deb_install, self.workdir)
                process.system("dpkg -i %s/%s" % (self.workdir, deb),
                               ignore_status=True, sudo=True)

    def tune_rxtx_queue(self):
        """
        Increase rx/tx queues to 16 for test interface
        """
        self.remotehost = RemoteHost(self.peer_ip[0], self.peer_user,
                                     password=self.peer_password)
        peer_interface = self.remotehost.get_interface_by_ipaddr(
            self.peer_ip[0]).name
        cmd = ("ethtool -L %s rx %s tx %s"
               % (peer_interface, self.rx_channel, self.tx_channel))
        output = self.session_peer.cmd(cmd)
        if not output:
            self.cancel("Unable to tune RX and TX queue in peer")
        device = self.find_device(self.mac_id[0])
        cmd = ("ethtool -L %s rx %s tx %s"
               % (device, self.rx_channel, self.tx_channel))
        result = process.run(cmd)
        if result.exit_status:
            self.cancel("Unable to tune RX and TX queue in host")

    def enable_irqbalance(self):
        """
        Enable irqbalance service on host and peer
        """
        cmd_start = "systemctl start irqbalance"
        self.session_peer.cmd(cmd_start)
        cmd_status = "systemctl status irqbalance"
        output = self.session_peer.cmd(cmd_status).stdout_text.splitlines()
        for line in output:
            if re.search("Active: active (running)", line):
                self.log.info("irqbalance service is active in peer")
        process.system(cmd_start)
        for line in process.system_output(
                cmd_status).decode("utf-8").splitlines():
            if re.search("Active: active (running)", line):
                self.log.info("irqbalance service is active in host")

    def test_add(self):
        '''
        Network virtualized device add operation
        '''
        for slot, mac, sriov_port, adapter_id, device_ip, netmask in zip(
                self.slot_num, self.mac_id, self.sriov_port,
                self.backing_adapter_id, self.device_ip, self.netmask):
            if not self.check_slot_availability(slot):
                self.fail("Slot does not exist")
            self.device_add_remove(slot, mac, sriov_port, adapter_id, 'add')
            # Call interface_naming() if required
            # self.interface_naming(mac, slot)
            output = self.list_device(slot)
            if 'slot_num=%s' % slot not in str(output):
                self.log.debug(output)
                self.fail("lshwres fails to list Network virtualized device \
                           after add operation")
            if mac not in str(output):
                self.log.debug(output)
                self.fail("MAC address in HMC differs")
            if not self.find_device(mac):
                self.fail("MAC address differs in linux")
            device = self.find_device(mac)
            networkinterface = NetworkInterface(device, self.local)
            try:
                networkinterface.add_ipaddr(device_ip, netmask)
                networkinterface.save(device_ip, netmask)
            except Exception:
                networkinterface.save(device_ip, netmask)
            networkinterface.bring_up()
            if not wait.wait_for(networkinterface.is_link_up, timeout=120):
                self.fail("Unable to bring up the link on the Network \
                       virtualized device")
            if networkinterface.ping_check(self.peer_ip[0],
                                           count=5) is not None:
                self.fail("Ping failed with active vnic device")
        self.session_peer = Session(self.peer_ip[0], user=self.peer_user,
                                    password=self.peer_password)
        if not wait.wait_for(self.session_peer.connect, timeout=30):
            self.fail("Failed connecting to peer lpar")
        self.enable_irqbalance()
        self.tune_rxtx_queue()
        self.check_dmesg_error()

    def test_backingdevadd(self):
        '''
        Adding Backing device for Network virtualized device
        '''
        for slot in self.slot_num:
            if self.check_slot_availability(slot):
                self.fail("Slot does not exist")
        pre_add = self.backing_dev_count()
        for count in range(1, self.backingdev_count):
            self.backing_dev_add_remove('add', count)
        post_add = self.backing_dev_count()
        post_add_count = post_add - pre_add + 1
        if post_add_count != self.backingdev_count:
            self.log.debug("Actual backing dev count: %d", post_add_count)
            self.log.debug("Expected backing dev count: %d",
                           self.backingdev_count)
            self.fail("Failed to add backing device")
        device = self.find_device(self.mac_id[0])
        networkinterface = NetworkInterface(device, self.local)
        if networkinterface.ping_check(self.peer_ip[0], count=5) is not None:
            self.fail("Backing device add has affected network connectivity")
        self.check_dmesg_error()

    def test_disable_enable_dev(self):
        '''
        Test if disabling and enabling of an adapter works
        '''
        device = self.find_device(self.mac_id[0])
        networkinterface = NetworkInterface(device, self.local)
        for _ in range(self.count):
            self.disable_enable_dev('d')
            self.is_disabled_enabled_dev('1')
            self.disable_enable_dev('e')
            self.is_disabled_enabled_dev('0')
            device = self.find_device(self.mac_id[0])
            if not device:
                self.fail("Interface is not available")
            wait.wait_for(networkinterface.is_link_up, timeout=60)
            if networkinterface.ping_check(self.peer_ip[0],
                                           count=5) is not None:
                self.fail("Enabling and disabling of the interface"
                          " has affected network connectivity")
        self.check_dmesg_error()

    def disable_enable_dev(self, option):
        '''
        Disable or enable interface command
        '''
        cmd = ("chhwres -m %s -o %s -r virtualio --rsubtype vnic"
               " -p %s -s %s"
               % (self.server, option, self.lpar, self.slot_num[0]))
        output = self.session_hmc.cmd(cmd)
        if output.exit_status != 0:
            if option == 'd':
                self.fail("Could not disable interface: %s" %
                          output.stdout_text)
            elif option == 'e':
                self.fail("Could not enable interface: %s" %
                          output.stdout_text)
            else:
                self.fail("Invalid option sent to disable/enable interface.")

    def is_disabled_enabled_dev(self, expect):
        '''
        Check if the interface was disabled or enabled correctly
        '''
        operation = "enable" if expect == '0' else "disable"
        cmd = "lshwres -m %s -r virtualio --rsubtype vnic --filter \
        \"lpar_names=%s\" -F slot_num:is_disabled" % (self.server, self.lpar)
        output = self.session_hmc.cmd(cmd).stdout_text

        for entry in output.splitlines():
            if entry.startswith(self.slot_num[0]):
                if entry.endswith(expect):
                    self.log.info("vNIC interface successfully %s" % operation)
                else:
                    self.fail("Could not %s vNIC interface" % operation)

    def change_active_device(self, slot):
        '''
        Change active device to original
        '''
        current_logport = self.get_active_device_logport(slot)
        if not self.original_logport == current_logport:
            self.trigger_failover(current_logport)
        else:
            self.log.info("Active device same before and after")

    def test_hmcfailover(self):
        '''
        Triggers Failover for the Network virtualized
        device
        '''
        original = self.get_active_device_logport(self.slot_num[0])
        for _ in range(self.count):
            before = self.get_active_device_logport(self.slot_num[0])
            self.trigger_failover(self.get_backing_device_logport
                                  (self.slot_num[0]))
            time.sleep(60)
            after = self.get_active_device_logport(self.slot_num[0])
            self.log.debug("Active backing device: %s", after)
            if before == after:
                self.fail("No failover happened")
            device = self.find_device(self.mac_id[0])
            networkinterface = NetworkInterface(device, self.local)
            if networkinterface.ping_check(self.peer_ip[0],
                                           count=5) is not None:
                self.fail("Failover has affected Network connectivity")
        if original != self.get_active_device_logport(self.slot_num[0]):
            self.trigger_failover(original)
        if original != self.get_active_device_logport(self.slot_num[0]):
            self.log.warn("Fail: Activating Initial backing dev %s" % original)
        self.check_dmesg_error()

    def test_clientfailover(self):
        '''
        Performs Client initiated failover for Network virtualized
        device
        '''
        device_id = self.find_device_id(self.mac_id[0])
        try:
            for _ in range(self.count):
                for val in range(int(self.backing_dev_count())):
                    self.log.info("Performing Client initiated\
                                  failover - Attempt %s", int(val + 1))
                    genio.write_file_or_fail("/sys/devices/vio/%s/failover"
                                             % device_id, "1")
                    time.sleep(60)
                    self.log.info("Running a ping test to check if failover \
                                    affected Network connectivity")
                    device = self.find_device(self.mac_id[0])
                    networkinterface = NetworkInterface(device, self.local)
                    if networkinterface.ping_check(
                            self.peer_ip[0], count=5,
                            options="-w50") is not None:
                        self.fail("Ping test failed. Network virtualized \
                                   failover has affected Network connectivity")
        except CmdError as details:
            self.log.debug(str(details))
            self.fail("Client initiated Failover for Network virtualized \
                      device has failed")
        self.check_dmesg_error()

    def test_vnic_auto_failover(self):
        '''
        Set the priority for vNIC active and backing devices and check
        if autofailover works
        '''
        if len(self.backing_adapter) >= 2:
            for _ in range(self.count):
                self.update_backing_devices(self.slot_num[0])
                backing_logport = self.get_backing_device_logport(
                    self.slot_num[0])
                active_logport = self.get_active_device_logport(
                    self.slot_num[0])
                backing_dev_priority = self.get_backing_device_priority(
                    self.slot_num[0])
                if self.enable_auto_failover():
                    if not self.change_failover_priority(
                            backing_logport, '1'):
                        self.fail(
                            "Fail to change the priority for"
                            " backing device %s", backing_logport)
                    if not self.change_failover_priority(
                            active_logport, '100'):
                        self.fail(
                            "Fail to change the priority for"
                            " active device %s", active_logport)
                    time.sleep(60)
                    if backing_logport != self.get_active_device_logport(
                            self.slot_num[0]):
                        self.fail("Auto failover of backing device failed")
                    device = self.find_device(self.mac_id[0])
                    networkinterface = NetworkInterface(device, self.local)
                    if networkinterface.ping_check(self.peer_ip[0],
                                                   count=5) is not None:
                        self.fail("Auto failover has effected connectivity")
                    # set back the priority
                    if not self.change_failover_priority(
                            active_logport, self.vnic_priority[0]):
                        self.fail(
                            "Auto failover tested successfully but fail"
                            " to set back original priority")
                    if not self.change_failover_priority(
                            backing_logport, backing_dev_priority):
                        self.fail(
                            "Auto failover tested successfully but fail"
                            " to set back original priority")
                else:
                    self.fail("Could not enable auto failover")
        else:
            self.cancel("Provide more backing device, only 1 given")
        self.check_dmesg_error()

    def test_rmdev_viosfailover(self):
        '''
        using mrdev and mkdev command to check vios failover works
        '''

        self.session = Session(self.vios_ip, user=self.vios_user,
                               password=self.vios_pwd)
        self.session.cleanup_master()
        if not wait.wait_for(self.session.connect, timeout=30):
            self.fail("Failed connecting to VIOS")

        cmd = "ioscli lsmap -all -vnic -cpid %s" % self.lpar_id
        vnic_servers = self.session.cmd(cmd).stdout_text.splitlines()
        device = self.find_device(self.mac_id[0])
        temp_idx = vnic_servers.index("Client device name:" + device)
        vnic_server = vnic_servers[temp_idx - 5].split()[0]

        cmd = "ioscli lsmap -vnic -vadapter %s" % vnic_server
        output = self.session.cmd(cmd)

        vnic_backing_device = None
        for line in output.stdout_text.splitlines():
            if 'Backing device' in line:
                vnic_backing_device = line.split(':')[-1]

        before = self.get_active_device_logport(self.slot_num[0])
        self.log.debug("Active backing device before : %s", before)

        self.validate_vios_command('rmdev -l %s' % vnic_server, 'Defined')
        if vnic_backing_device:
            self.validate_vios_command(
                'rmdev -l %s' % vnic_backing_device, 'Defined')

        time.sleep(10)

        for backing_dev in self.backing_dev_list().splitlines():
            if backing_dev.startswith('%s,' % self.slot_num[0]):
                backing_dev = backing_dev.strip('%s,"' % self.slot_num[0])
                if 'Powered Off' not in backing_dev:
                    self.fail("Failover did not occur")

        time.sleep(60)

        if vnic_backing_device:
            self.validate_vios_command(
                'mkdev -l %s' % vnic_backing_device, 'Available')
        self.validate_vios_command('mkdev -l %s' % vnic_server, 'Available')

        networkinterface = NetworkInterface(device, self.local)
        if networkinterface.ping_check(self.peer_ip[0], count=5) is not None:
            self.fail("Ping test failed. Network virtualized \
                      vios failover has affected Network connectivity")
        self.check_dmesg_error()

    def test_vnic_dlpar(self):
        '''
        Perform vNIC device hot add and hot remove using drmgr command
        '''
        for slot_no, device_ip, netmask, mac, peer_ip in zip(self.slot_num,
                                                             self.device_ip,
                                                             self.netmask,
                                                             self.mac_id,
                                                             self.peer_ip):
            self.update_backing_devices(slot_no)
            dev_id = self.find_device_id(mac)
            device_name = self.find_device(mac)
            slot = self.find_virtual_slot(dev_id)
            if slot:
                try:
                    for _ in range(self.num_of_dlpar):
                        self.drmgr_vnic_dlpar('-r', slot)
                        self.drmgr_vnic_dlpar('-a', slot)
                        self.wait_intrerface(device_name)
                except CmdError as details:
                    self.log.debug(str(details))
                    self.fail("dlpar operation did not complete")
                device = self.find_device(mac)
                networkinterface = NetworkInterface(device, self.local)
                try:
                    networkinterface.add_ipaddr(device_ip, netmask)
                except Exception:
                    networkinterface.save(device_ip, netmask)
                if not wait.wait_for(networkinterface.is_link_up, timeout=120):
                    self.fail("Unable to bring up the link on the Network \
                              virtualized device")
                if networkinterface.ping_check(peer_ip, count=5) is not None:
                    self.fail("dlpar has affected Network connectivity")
            else:
                self.fail("slot not found")
        self.check_dmesg_error()

    def test_vnic_hmc_dlpar(self):
        """
        Perform vNIC device hot add and hot remove
        """
        for slot_no, device_ip, netmask, mac, peer_ip, sriov_port, \
                adapter_id in zip(self.slot_num, self.device_ip,
                                  self.netmask, self.mac_id,
                                  self.peer_ip, self.sriov_port,
                                  self.backing_adapter_id):
            self.update_backing_devices(slot_no)
            device_name = self.find_device(mac)
            networkinterface = NetworkInterface(device_name, self.local)
            count = 0
            self.log.info("Performing DLPAR on %s" % device_name)
            for _ in range(self.num_of_dlpar):
                self.log.info("DLPAR iteration #%d" % count)
                num_backingdevs = self.backing_dev_count_w_slot_num(slot_no)

                self.device_add_remove(slot_no, '', '', '', 'remove')
                if networkinterface.is_available():
                    self.fail("DLPAR remove did not remove interface")

                self.device_add_remove(
                    slot_no, mac, sriov_port, adapter_id, 'add')
                for c in range(1, num_backingdevs):
                    self.backing_dev_add_remove('add', c)
                    self.wait_interface(device_name)

                try:
                    networkinterface.add_ipaddr(device_ip, netmask)
                except Exception:
                    networkinterface.save(device_ip, netmask)
                networkinterface.bring_up()

                if not wait.wait_for(networkinterface.is_link_up, timeout=120):
                    self.fail(
                        "Unable to bring up the link on the"
                        " Network virtualized device")

                time.sleep(5)

                if networkinterface.ping_check(peer_ip, count=5) is not None:
                    self.fail("dlpar has affected Network connectivity")
                count += 1
        self.check_dmesg_error()

    def test_vnic_eeh(self):
        """
        Perform EEH on vnic interface from vios
        """
        if self.backing_dev_count() == 1:
            self.cancel("EEH cannot be tested as the interface"
                        " has single backing device")
        current_logport = self.get_active_device_logport(self.slot_num[0])
        if not self.original_logport == current_logport:
            self.trigger_failover(self.original_logport)
        else:
            self.log.info("Unable to set the logport to original one")
        time.sleep(5)
        self.session = Session(self.vios_ip, user=self.vios_user,
                               password=self.vios_pwd)
        self.session.cleanup_master()
        if not wait.wait_for(self.session.connect, timeout=30):
            self.fail("Failed connecting to VIOS")
        cmd = "ioscli lsmap -all -vnic -cpid %s" % self.lpar_id
        vnic_servers = self.session.cmd(cmd).stdout_text.splitlines()
        device = self.find_device(self.mac_id[0])
        temp_idx = vnic_servers.index("Client device name:" + device)
        vnic_backingdevice = vnic_servers[temp_idx - 3].split(":")[1]
        vios = pxssh.pxssh()
        try:
            vios.login(self.vios_ip, self.vios_user, self.vios_pwd)
        except Exception:
            self.warn("Unable to login to vios")
        time.sleep(2)
        vios.sendline("oem_setup_env")
        time.sleep(5)
        eeh_tool_64 = self.params.get('eeh_tool', default='eeh_tool_64')
        eeh_tool_64 = self.get_data(eeh_tool_64)
        cmd = ("scp %s@%s:%s ."
               % (self.host_user, self.host_public_ip, eeh_tool_64))
        vios.sendline(cmd)
        time.sleep(3)
        vios.sendline(self.host_password)
        time.sleep(5)
        vios.sendline("kdb")
        time.sleep(5)
        vios.sendline("set scroll false")
        time.sleep(5)
        if self.is_mlx_driver:
            cmd = "mlxcent setacs %s" % vnic_backingdevice
            vios.sendline(cmd)
            time.sleep(2)
            vios.sendline("mlxcent pollq 0")
            vios.prompt()
            map_start_value = None
            mapstart = vios.before.decode("utf-8").split("\r\n ")
            for i in mapstart:
                if re.search("map_start", i):
                    map_start_value = i.split("=")[1]
            if not map_start_value:
                self.fail("map_start value not found in kdb output")
            vios.sendline("quit")
            cmd = ("./eeh_tool_64 %s 3 15 -w 64 -a %s"
                   " -m 0xFFFFFFFFFFFFF000"
                   % (vnic_backingdevice, map_start_value))
            vios.sendline(cmd)
            time.sleep(5)
        else:
            cmd = "lnc2ent setacs %s" % vnic_backingdevice
            vios.sendline(cmd)
            time.sleep(2)
            cmd = "lnc2ent hw pollq 0"
            vios.sendline(cmd)
            vios.prompt()
            tce_start_value = None
            tcestart = vios.before.decode("utf-8").split("\r\n ")
            for i in tcestart:
                if re.search("tce_start", i):
                    tce_start_value = i.split("=")[1]
            if not tce_start_value:
                self.fail("tce_start value not found in kdb output")
            vios.sendline("quit")
            cmd = ("./eeh_tool_64 %s 3 15 -w 64 -a %s"
                   " -m 0xFFFFFFFFFFFFF000"
                   % (vnic_backingdevice, tce_start_value))
            vios.sendline(cmd)
            time.sleep(5)
        active_logport = self.get_active_device_logport(self.slot_num[0])
        if current_logport == active_logport:
            self.fail("EEH unsuccessful as there is no failover"
                      " triggered on the OS")
        device = self.find_device(self.mac_id[0])
        networkinterface = NetworkInterface(device, self.local)
        if networkinterface.ping_check(self.peer_ip[0],
                                       count=5) is not None:
            self.fail("Ping to peer failed. EEH has affected"
                      " Network connectivity")

    def backing_dev_count_w_slot_num(self, slot):
        """
        Lists the count of backing devices
        :param slot: vnic slot
        :type slot: str

        :returns: backing device count
        :rtype: int
        """
        count = 0
        output = self.backing_dev_list()
        for i in output.splitlines():
            if i.startswith('%s,' % slot):
                count = len(i.split(',')[1:])
        return count

    def wait_interface(self, device_name):
        """
        Wait till interface comes up
        :param device_name: vnic device that is tested
        :type device_name: str

        :returns: if the device is up or down
        :rtype: bool
        """
        for _ in range(0, 120, 10):
            for interface in netifaces.interfaces():
                if device_name == interface:
                    self.log.info(
                        "Network virtualized device %s is up", device_name)
                    return True
                time.sleep(5)
        return False

    def test_backingdevremove(self):
        """
        Removing Backing device for Network virtualized device
        """
        for slot in self.slot_num:
            if self.check_slot_availability(slot):
                self.fail("Slot does not exist")
            self.update_backing_devices(slot)
            pre_remove = self.backing_dev_count()
            for count in range(1, self.backingdev_count):
                self.backing_dev_add_remove('remove', count)
            post_remove = self.backing_dev_count()
            post_remove_count = pre_remove - post_remove + 1
            if post_remove_count != self.backingdev_count:
                self.log.debug("Actual backing dev count: %d",
                               post_remove_count)
                self.log.debug("Expected backing dev count: %d",
                               self.backingdev_count)
                self.fail("Failed to remove backing device")
        self.check_dmesg_error()

    def test_remove(self):
        '''
        Network virtualized device remove operation
        '''
        for slot in self.slot_num:
            if self.check_slot_availability(slot):
                self.fail("Slot does not exist")
            self.update_backing_devices(slot)
            self.device_add_remove(slot, '', '', '', 'remove')
            output = self.list_device(slot)
            if 'slot_num=%s' % slot in str(output):
                self.log.debug(output)
                self.fail("lshwres still lists the Network virtualized device \
                           after remove operation")
        self.check_dmesg_error()

    def validate_vios_command(self, cmd, validate_string):
        '''
        checking for vnicserver and backing device
        '''
        l_cmd = "echo \"%s\" | ioscli oem_setup_env" % cmd
        output = self.session.cmd(l_cmd)
        if validate_string not in output.stdout_text:
            self.fail("command fail in vios")

    def device_add_remove(self, slot, mac, sriov_port, adapter_id, operation):
        '''
        Adds and removes a Network virtualized device based
        on the operation
        '''
        backing_device = "backing_devices=sriov/%s/%s/%s/%s/%s/%s"\
                         % (self.vios_name[0], self.vios_id[0],
                            adapter_id, sriov_port,
                            self.bandwidth, self.vnic_priority[0])
        if operation == 'add':
            cmd = 'chhwres -m %s --id %s -r virtualio --rsubtype vnic \
                   -o a -s %s -a \"auto_priority_failover=%s,mac_addr=%s,%s\" '\
                   % (self.server, self.lpar_id, slot,
                      self.auto_failover, mac, backing_device)
        else:
            cmd = 'chhwres -m %s --id %s -r virtualio --rsubtype vnic \
                   -o r -s %s'\
                   % (self.server, self.lpar_id, slot)
        output = self.session_hmc.cmd(cmd)
        if output.exit_status != 0:
            self.log.debug(output.stderr)
            self.fail("Network virtualization %s device operation \
                       failed" % operation)

    def list_device(self, slot):
        '''
        Lists the Network vritualized devices
        '''
        cmd = 'lshwres -r virtualio -m %s --rsubtype vnic --filter \
              \"lpar_names=%s,slots=%s\"' % (self.server, self.lpar,
                                             slot)
        try:
            output = self.session_hmc.cmd(cmd)
        except CmdError as details:
            self.log.debug(str(details))
            self.fail("lshwres operation failed ")
        return output.stdout_text

    def backing_dev_add_remove(self, operation, i):
        '''
        Adds and removes a backing device based on the operation
        '''
        add_backing_device = "sriov/%s/%s/%s/%s/%s/%s" \
                             % (self.vios_name[i], self.vios_id[i],
                                self.backing_adapter_id[i],
                                self.sriov_port[i],
                                self.bandwidth,
                                self.vnic_priority[i])
        if operation == 'add':
            cmd = ('chhwres -r virtualio --rsubtype vnic -o s -m %s'
                   ' -s %s --id %s -a'
                   ' "auto_priority_failover=%s,backing_devices+=%s"'
                   % (self.server, self.slot_num[0], self.lpar_id,
                      self.auto_failover, add_backing_device))
        else:
            cmd = 'chhwres -r virtualio --rsubtype vnic -o s -m %s -s %s \
                   --id %s -a backing_devices-=%s' % (self.server,
                                                      self.slot_num[0],
                                                      self.lpar_id,
                                                      add_backing_device)
        output = self.session_hmc.cmd(cmd)
        if output.exit_status != 0:
            self.log.debug(output.stderr)
            self.fail("Network virtualization Backing device %s \
                       operation failed" % operation)

    def backing_dev_list(self):
        '''
        Lists the Backing devices for a Network virtualized
        device
        '''
        cmd = 'lshwres -r virtualio -m %s --rsubtype vnic --level lpar \
               --filter lpar_names=%s -F slot_num,backing_device_states' \
               % (self.server, self.lpar)
        try:
            output = self.session_hmc.cmd(cmd)
        except CmdError as details:
            self.log.debug(str(details))
            self.fail("lshwres operation failed ")
        return output.stdout_text

    def get_backing_devices(self, slot):
        '''
        Lists the Backing devices for a Network virtualized
        device
        '''
        cmd = 'lshwres -r virtualio -m %s --rsubtype vnic --level lpar \
               --filter lpar_names=%s,slots=%s -F backing_devices' \
               % (self.server, self.lpar, slot)
        try:
            output = self.session_hmc.cmd(cmd)
        except CmdError as details:
            self.log.debug(str(details))
            self.fail("lshwres operation failed ")
        return output.stdout_text

    def update_backing_devices(self, slot):
        '''
        Updates the lists of backing devices, ports, vioses.
        Makes sure the active device's details are on index 0.
        '''
        logport = self.get_active_device_logport(slot)
        adapter_id = ''
        port = ''
        index = None
        for entry in self.get_backing_devices(slot).split(','):
            if logport in entry:
                adapter_id = entry.split('/')[3]
                port = entry.split('/')[4]
                self.vnic_priority[0] = entry.split('/')[8]
        if not adapter_id:
            return
        for i in range(0, len(self.backing_adapter_id)):
            if adapter_id == self.backing_adapter_id[i]:
                if port == self.sriov_port[i]:
                    index = i
        if index is None:
            self.log.debug("Active backing device not found in adapter list")
            return
        vios_id = self.vios_id.pop(index)
        self.vios_id.insert(0, vios_id)
        self.sriov_port.pop(index)
        self.sriov_port.insert(0, port)
        self.backing_adapter_id.pop(index)
        self.backing_adapter_id.insert(0, adapter_id)

    def backing_dev_count(self):
        '''
        Lists the count of backing devices
        '''
        count = 0
        for slot in self.slot_num:
            output = self.backing_dev_list()
            for i in output.splitlines():
                if i.startswith('%s,' % slot):
                    count = len(i.split(',')[1:])
            return count

    @staticmethod
    def find_device(mac_addrs):
        """
        Finds out the latest added network virtualized device
        """
        mac = ':'.join(mac_addrs[i:i+2] for i in range(0, 12, 2))
        devices = netifaces.interfaces()
        for device in devices:
            if mac in netifaces.ifaddresses(device)[17][0]['addr']:
                return device
        return ''

    @staticmethod
    def purge_nmcli_connections(ifname):
        """
        Delete all NetworkManager connection profiles whose con-name or bound
        device matches *ifname*.  Stale profiles from a previous test run may
        be unconnected (DEVICE column shows '--') but still share the same
        con-name, causing 'nmcli connection up <ifname>' to activate the wrong
        profile and fail with "IP configuration could not be reserved".

        Also removes the backing .nmconnection file on disk so NM cannot
        reload the stale profile when the device reappears.
        """
        nm_conn_dir = '/etc/NetworkManager/system-connections'
        out = process.system_output(
            'nmcli -t -f UUID,NAME,DEVICE connection show',
            ignore_status=True, shell=True).decode('utf-8', errors='replace')
        for line in out.splitlines():
            parts = line.strip().split(':')
            if len(parts) < 3:
                continue
            uuid, name, device = parts[0], parts[1], parts[2]
            if name == ifname or device == ifname:
                process.run('nmcli connection delete %s' % uuid,
                            ignore_status=True, shell=True)
        # Also scrub any leftover .nmconnection file that NM may reload
        # on next device appearance (e.g. after nmcli delete races with NM).
        stale = os.path.join(nm_conn_dir, '%s.nmconnection' % ifname)
        if os.path.exists(stale):
            process.run('rm -f %s' % stale, ignore_status=True, shell=True)
            process.run('nmcli connection reload',
                        ignore_status=True, shell=True)

    def drmgr_vnic_dlpar(self, operation, slot):
        """
        Perform add / remove operation
        """
        cmd = 'drmgr %s -c slot -s %s -w 5 -d 1' % (operation, slot)
        if process.system(cmd, shell=True, sudo=True, ignore_status=True):
            self.fail("drmgr operation %s fails for vNIC device %s" %
                      (operation, slot))

    def is_auto_failover_enabled(self):
        """
        Check if auto failover is enabled for the vNIC device
        """
        cmd = 'lshwres -r virtualio -m %s --rsubtype vnic \
               --filter lpar_names=%s,slots=%s' \
               % (self.server, self.lpar, self.slot_num[0])
        output = self.session_hmc.cmd(cmd)
        if output.exit_status != 0:
            self.log.debug(output.stderr)
        if 'auto_priority_failover=1' in output.stdout_text:
            return True
        return False

    def enable_auto_failover(self):
        """
        Function to enable auto failover option
        """
        cmd = 'chhwres -r virtualio -m %s --rsubtype vnic \
               -o s --id %s -s %s -a auto_priority_failover=1' \
               % (self.server, self.lpar_id, self.slot_num[0])
        output = self.session_hmc.cmd(cmd)
        if output.exit_status != 0:
            self.log.debug(output.stderr)
        if not self.is_auto_failover_enabled():
            return False
        return True

    def get_failover_priority(self, logport):
        """
        get the priority value for the given backing device
        """
        priority = None
        cmd = 'lshwres -r virtualio -m %s --rsubtype vnic --level lpar \
               --filter slots=%s,lpar_names=%s -F slot_num,backing_devices' \
               % (self.server, self.slot_num[0], self.lpar)
        output = self.session_hmc.cmd(cmd)
        if output.exit_status != 0:
            self.log.debug(output.stderr)
        if output.stdout_text.startswith('%s,' % self.slot_num[0]):
            backing_dev = output.stdout_text.strip('%s,"' % self.slot_num[0])
            for entry in backing_dev.split(','):
                entry = entry.split('/')
                if logport in entry:
                    priority = entry[8]
                    break
        return priority

    def change_failover_priority(self, logport, priority):
        """
        Change the fail over priroity for given backing device
        """
        cmd = 'chhwres -r virtualio --rsubtype vnicbkdev -o s -m %s \
               -s %s --id %s --logport %s -a failover_priority=%s' \
               % (self.server, self.slot_num[0],
                  self.lpar_id, logport, priority)
        output = self.session_hmc.cmd(cmd)
        if output.exit_status != 0:
            self.log.debug(output.stderr)
        if priority != self.get_failover_priority(logport):
            return False
        return True

    def find_device_id(self, mac):
        """
        Finds the device id needed to trigger failover
        """
        device = self.find_device(mac)
        device_id = process.system_output("ls -l /sys/class/net/ | \
                                           grep -w %s | cut -d '/' -f \
                                           5" % device,
                                          shell=True).decode("utf-8").strip()
        return device_id

    def find_virtual_slot(self, dev_id):
        """
        finds the virtual slot for the given virtual ID
        """
        output = process.system_output("lsslot", ignore_status=True,
                                       shell=True, sudo=True)
        for slot in output.decode("utf-8").split('\n'):
            if dev_id in slot:
                return slot.split(' ')[0]
        return False

    def trigger_failover(self, logport):
        '''
        Triggers failover from HMC
        '''
        cmd = 'chhwres -r virtualio --rsubtype vnicbkdev -o act -m %s \
               -s %s --id %s \
               --logport %s' % (self.server, self.slot_num[0],
                                self.lpar_id, logport)
        output = self.session_hmc.cmd(cmd)
        if output.exit_status != 0:
            self.log.debug(output.stderr)
            self.fail("Command to set %s as Active has failed" % logport)

    def get_backing_device_logport(self, slot):
        '''
        Get the logical port id of the
        backing device
        '''
        for backing_dev in self.backing_dev_list().splitlines():
            if backing_dev.startswith('%s,' % slot):
                backing_dev = backing_dev.strip('%s,"' % slot)
                for entry in backing_dev.split(','):
                    entry = entry.split('/')
                    if '0' in entry[2] and 'Operational' in entry[3]:
                        logport = entry[1]
                        break
        return logport

    def get_active_device_logport(self, slot):
        '''
        Get the logical port id of the Network
        virtualized device
        '''
        logport = None
        for backing_dev in self.backing_dev_list().splitlines():
            if backing_dev.startswith('%s,' % slot):
                backing_dev = backing_dev.strip('%s,"' % slot)
                for entry in backing_dev.split(','):
                    entry = entry.split('/')
                    if '1' in entry[2]:
                        logport = entry[1]
                        break
        return logport

    def get_backing_device_priority(self, slot):
        '''
        Get the backing device proiority of the vnic interface
        '''
        for entry in self.get_backing_devices(slot).split(','):
            logport = self.get_backing_device_logport(slot)
            if logport in entry:
                backing_dev_prio = entry.split('/')[8]
                break
        return backing_dev_prio

    def is_backing_device_active(self, slot):
        '''
        TO check the status of the backing device
        after failover
        '''
        val = 0
        for backing_dev in self.backing_dev_list().splitlines():
            if backing_dev.startswith('%s,' % slot):
                val = int(backing_dev.split(',')[1:][1].split('/')[2])
        if val:
            return True
        return False

    def interface_naming(self, mac, slot):
        '''
        naming to vnic interface
        '''
        mac_addrs = ':'.join(mac[i:i+2] for i in range(0, 12, 2))
        file = "/etc/udev/rules.d/70-persistent-net.rules"
        with open(file, "a+") as interface_conf:
            interface_conf.write("SUBSYSTEM==\"net\", ")
            interface_conf.write("ACTION==\"add\", ")
            interface_conf.write("DRIVERS==\"?*\", ")
            interface_conf.write("ATTR{address}==\"%s\", " % mac_addrs)

    def wait_intrerface(self, device_name):
        """
        Wait till interface come up
        """
        for _ in range(0, 120, 10):
            for interface in netifaces.interfaces():
                if device_name == interface:
                    self.log.info(
                        "Network virtualized device %s is up", device_name)
                    return True
                time.sleep(5)
        return False

    def check_dmesg_error(self):
        """
        check for dmesg error
        """
        error = ['uevent: failed to send synthetic uevent',
                 'Invalid request detected while CRQ is inactive',
                 'failed to send uevent', 'registration failed',
                 'CRQ-init failed, -11']
        error_list = ["Virtual Adapter failed", "Failed to set link state"]
        if 'test_remove' not in str(self.name.name):
            device = self.find_device(self.mac_id[0])
            networkinterface = NetworkInterface(device, self.local)
            for err in error_list:
                if networkinterface.ping_check(self.peer_ip[0],
                                               count=5) is None:
                    error.append(err)
        self.log.info("Gathering kernel errors if any")
        try:
            dmesg.collect_errors_by_level(level_check=4, skip_errors=error)
        except Exception as exc:
            self.log.info(exc)
            self.fail("test failed,check dmesg log in debug log")

    def sriov_logport_add_remove(self, adapter_id, phys_port_id,
                                 mac, operation):
        '''
        Add or remove a direct SR-IOV logical port via HMC chhwres.
        operation: 'add' or 'remove'
        Returns logical_port_id on add (parsed from lshwres), None on remove.
        '''
        if operation == 'add':
            cmd = ('chhwres -r sriov -m %s --rsubtype logport -o a -p %s '
                   '-a "adapter_id=%s,phys_port_id=%s,'
                   'logical_port_type=eth,mac_addr=%s,migratable=0"'
                   % (self.server, self.lpar, adapter_id, phys_port_id, mac))
            output = self.session_hmc.cmd(cmd)
            if output.exit_status != 0:
                self.log.debug(output.stderr)
                self.fail('SR-IOV logical port add failed: %s'
                          % output.stdout_text)
            # Retrieve the logical_port_id that HMC assigned
            cmd = ('lshwres -r sriov --rsubtype logport -m %s --level eth '
                   '--filter "lpar_names=%s" | grep %s'
                   % (self.server, self.lpar, mac))
            output = self.session_hmc.cmd(cmd)
            if output.exit_status != 0 or not output.stdout_text.strip():
                self.fail('Could not find SR-IOV logical port'
                          ' for MAC %s' % mac)
            return output.stdout_text.split(',')[6].split('=')[-1].strip()
        else:
            cmd = ('chhwres -r sriov -m %s --rsubtype logport -o r -p %s '
                   '-a "adapter_id=%s,logical_port_id=%s"'
                   % (self.server, self.lpar, adapter_id, mac))
            output = self.session_hmc.cmd(cmd)
            if output.exit_status != 0:
                self.log.debug(output.stderr)
                self.fail('SR-IOV logical port remove failed: %s'
                          % output.stdout_text)
            return None

    def test_sriov_vnic_same_port(self):
        '''
        Add one direct SR-IOV logical port and one vNIC interface from the
        same physical adapter and the same physical port.  Verify both
        interfaces come up and can ping the peer, then remove both.

        YAML keys specific to this test:
          sriov_mac_id   - MAC address for the SR-IOV direct logical port
          sriov_device_ip - IP to assign to the SR-IOV interface
          sriov_peer_ip   - peer IP for the SR-IOV ping check

        Shared YAML keys (index 0 used for the vNIC):
          slot_num[0], mac_id[0], device_ip[0], netmasks[0], peer_ip[0],
          sriov_adapters[0], sriov_ports[0]

        :avocado: tags=net,vnic,sriov,dlpar,privileged,power
        '''
        sriov_mac = self.params.get(
            'sriov_mac_id',
            default='02:03:02:00:00:01').replace(':', '')
        sriov_ip = self.params.get('sriov_device_ip', default=None)
        sriov_peer = self.params.get('sriov_peer_ip', default=None)
        if not sriov_ip or not sriov_peer:
            self.cancel('sriov_device_ip and sriov_peer_ip are required')

        adapter_id = self.backing_adapter_id[0]
        phys_port = self.sriov_port[0]
        vnic_slot = self.slot_num[0]
        vnic_mac = self.mac_id[0]
        vnic_ip = self.device_ip[0]
        vnic_netmask = self.netmask[0]
        vnic_peer = self.peer_ip[0]

        self.log.info('Adding SR-IOV direct logical port:'
                      ' adapter=%s port=%s mac=%s',
                      adapter_id, phys_port, sriov_mac)
        sriov_logport_id = self.sriov_logport_add_remove(
            adapter_id, phys_port, sriov_mac, 'add')

        self.log.info('Adding vNIC on same adapter=%s port=%s slot=%s mac=%s',
                      adapter_id, phys_port, vnic_slot, vnic_mac)
        if not self.check_slot_availability(vnic_slot):
            # SR-IOV port was already added; clean it up before bailing
            self.sriov_logport_add_remove(adapter_id, phys_port,
                                          sriov_logport_id, 'remove')
            self.fail('vNIC slot %s is already in use' % vnic_slot)
        self.device_add_remove(vnic_slot, vnic_mac, phys_port,
                               adapter_id, 'add')
        if 'slot_num=%s' % vnic_slot not in str(
                self.list_device(vnic_slot)):
            self.fail('lshwres fails to list vNIC after add')

        # Both interfaces have been added; use try/finally so cleanup always
        # runs even when a ping check (or link-up wait) raises/fails.
        ping_failures = []
        try:
            # Configure and verify SR-IOV direct interface
            sriov_dev = self.find_device(sriov_mac)
            if not sriov_dev:
                self.fail('SR-IOV interface with MAC %s not found in OS'
                          % sriov_mac)
            sriov_ni = NetworkInterface(sriov_dev, self.local)
            time.sleep(5)
            self.purge_nmcli_connections(sriov_dev)
            try:
                sriov_ni.add_ipaddr(sriov_ip, self.netmask[0])
                sriov_ni.save(sriov_ip, self.netmask[0])
            except NWException:
                self.fail('Failed to configure IP %s on %s'
                          % (sriov_ip, sriov_dev))
            sriov_ni.bring_up()
            if not wait.wait_for(sriov_ni.is_link_up, timeout=120):
                self.fail('SR-IOV interface %s did not come up' % sriov_dev)
            try:
                sriov_ni.ping_check(sriov_peer, count=5)
                self.log.info('SR-IOV interface %s up and pinging', sriov_dev)
            except NWException:
                msg = ('Failed to ping: ping -I %s %s -c 5'
                       % (sriov_dev, sriov_peer))
                self.log.error(msg)
                ping_failures.append(msg)

            # Configure and verify vNIC interface
            vnic_dev = self.find_device(vnic_mac)
            if not vnic_dev:
                self.fail('vNIC interface with MAC %s not found in OS'
                          % vnic_mac)
            vnic_ni = NetworkInterface(vnic_dev, self.local)
            time.sleep(5)
            self.purge_nmcli_connections(vnic_dev)
            try:
                vnic_ni.add_ipaddr(vnic_ip, vnic_netmask)
                vnic_ni.save(vnic_ip, vnic_netmask)
            except NWException:
                self.fail('Failed to configure IP %s on %s'
                          % (vnic_ip, vnic_dev))
            vnic_ni.bring_up()
            if not wait.wait_for(vnic_ni.is_link_up, timeout=120):
                self.fail('vNIC interface %s did not come up' % vnic_dev)
            try:
                vnic_ni.ping_check(vnic_peer, count=5)
                self.log.info('vNIC interface %s up and pinging', vnic_dev)
            except NWException:
                msg = ('Failed to ping: ping -I %s %s -c 5'
                       % (vnic_dev, vnic_peer))
                self.log.error(msg)
                ping_failures.append(msg)
        finally:
            # Cleanup always runs: remove vNIC first, then SR-IOV logical port
            self.log.info('Removing vNIC slot %s', vnic_slot)
            self.device_add_remove(vnic_slot, '', '', '', 'remove')
            if 'slot_num=%s' % vnic_slot in str(self.list_device(vnic_slot)):
                self.log.error('lshwres still lists vNIC after remove')
            if vnic_dev:
                self.purge_nmcli_connections(vnic_dev)
                self.log.info('nmcli profiles purged for %s', vnic_dev)

            self.log.info('Removing SR-IOV logical port id %s',
                          sriov_logport_id)
            self.sriov_logport_add_remove(adapter_id, phys_port,
                                          sriov_logport_id, 'remove')
            if sriov_dev:
                self.purge_nmcli_connections(sriov_dev)
                self.log.info('nmcli profiles purged for %s', sriov_dev)

        if ping_failures:
            self.fail('Ping failures detected (all interfaces have been'
                      ' removed):\n' + '\n'.join(ping_failures))
        self.check_dmesg_error()

    def _vnic_add_ping_remove(self, slots, macs, adapter_ids, ports,
                              device_ips, netmasks, peer_ips):
        '''
        Shared helper: add all N vNICs first, then verify all with ping
        while all are simultaneously active, then remove all one by one.

        Phase 1 - Add all: each vNIC is added via HMC, IP assigned, link
                  brought up.  No ping yet — all interfaces must be live
                  together before any connectivity check runs.
        Phase 2 - Ping all: with every vNIC active at the same time, ping
                  each peer to confirm coexistence and network isolation.
                  Failures are recorded but do NOT stop execution — cleanup
                  in Phase 3 always runs regardless of ping results.
        Phase 3 - Remove all: tear down each vNIC one by one via HMC.
                  Runs unconditionally so no interfaces are left stranded.
        '''
        added = []        # list of (slot, device_name, NetworkInterface)
        ping_failures = []  # accumulated ping failure messages

        # ── Phase 1: add all vNICs ────────────────────────────────────────
        self.log.info('Phase 1: adding all %d vNICs', len(slots))
        for slot, mac, adapter_id, port, ip, netmask in zip(
                slots, macs, adapter_ids, ports, device_ips, netmasks):
            self.log.info('Adding vNIC slot=%s mac=%s adapter=%s port=%s',
                          slot, mac, adapter_id, port)
            if not self.check_slot_availability(slot):
                self.fail('vNIC slot %s is already in use' % slot)
            self.device_add_remove(slot, mac, port, adapter_id, 'add')
            output = self.list_device(slot)
            if 'slot_num=%s' % slot not in str(output):
                self.fail('lshwres fails to list vNIC after add'
                          ' for slot %s' % slot)
            if mac not in str(output):
                self.fail('MAC %s not listed in HMC after add'
                          ' for slot %s' % (mac, slot))
            device = self.find_device(mac)
            if not device:
                self.fail('Interface with MAC %s not found in OS' % mac)
            ni = NetworkInterface(device, self.local)
            # Wait for NM to finish auto-creating a profile for the new
            # device, then purge it so add_ipaddr starts from a clean slate.
            time.sleep(5)
            self.purge_nmcli_connections(device)
            try:
                ni.add_ipaddr(ip, netmask)
                ni.save(ip, netmask)
            except NWException:
                self.fail('Failed to configure IP %s on %s (slot %s)'
                          % (ip, device, slot))
            ni.bring_up()
            if not wait.wait_for(ni.is_link_up, timeout=120):
                self.fail('Interface %s did not come up (slot %s)'
                          % (device, slot))
            self.log.info('slot=%s interface=%s up', slot, device)
            added.append((slot, device, ni))

        # ── Phase 2: ping all — every vNIC is live simultaneously ─────────
        self.log.info('Phase 2: all %d vNICs active — running ping checks',
                      len(added))
        for (slot, device, ni), peer in zip(added, peer_ips):
            self.log.info('Pinging %s from interface %s (slot %s)',
                          peer, device, slot)
            try:
                ni.ping_check(peer, count=5)
                self.log.info('slot=%s interface=%s successfully pinged %s',
                              slot, device, peer)
            except NWException:
                msg = ('Failed to ping: ping -I %s %s -c 5'
                       % (device, peer))
                self.log.error(msg)
                ping_failures.append(msg)

        # ── Phase 3: remove all vNICs one by one (always runs) ───────────
        self.log.info('Phase 3: removing all %d vNICs', len(added))
        for slot, device, _ in added:
            self.update_backing_devices(slot)
            self.device_add_remove(slot, '', '', '', 'remove')
            if 'slot_num=%s' % slot in str(self.list_device(slot)):
                self.log.error('lshwres still lists vNIC after remove'
                               ' for slot %s', slot)
            else:
                self.log.info('slot=%s removed successfully', slot)
            self.purge_nmcli_connections(device)
            self.log.info('slot=%s nmcli profiles purged for %s', slot, device)

        # ── Report any ping failures now that cleanup is complete ─────────
        if ping_failures:
            self.fail('Ping failures detected (all vNICs have been removed):'
                      '\n' + '\n'.join(ping_failures))

    def test_vnic_6x_single_card(self):
        '''
        DLPAR add 6 vNIC interfaces backed by a single SR-IOV card.
        All 6 vNICs share the same physical adapter; ports are distributed
        across the available ports in round-robin order (0,1,0,1,0,1 for a
        dual-port card, or 0,0,0,0,0,0 for single-port).
        Each interface is verified with a ping check, then all 6 are removed.

        YAML: vnic_6x_single_card.yaml
        Required keys: slot_num (6 entries), sriov_adapters (1 loc-code x6),
          sriov_ports (6 port values), vios_names (1 vios x6), mac_id (6),
          device_ip (6), netmasks (6), peer_ip (6), bandwidth, priority (6),
          auto_failover

        :avocado: tags=net,vnic,dlpar,privileged,power
        '''
        if len(self.slot_num) != 6:
            self.cancel('vnic_6x_single_card requires exactly'
                        ' 6 slot_num entries')
        if len(set(self.backing_adapter)) != 1:
            self.cancel('vnic_6x_single_card requires all sriov_adapters'
                        ' to be the same card')
        self._vnic_add_ping_remove(
            self.slot_num, self.mac_id, self.backing_adapter_id,
            self.sriov_port, self.device_ip, self.netmask, self.peer_ip)
        self.check_dmesg_error()

    def test_vnic_6x_multi_card(self):
        '''
        DLPAR add 6 vNIC interfaces spread across multiple SR-IOV cards.
        Requires at least 2 distinct adapters in sriov_adapters; the 6 vNICs
        are distributed across whatever distinct cards are provided.
        Each interface is verified with a ping check, then all 6 are removed.

        YAML: vnic_6x_multi_card.yaml
        Required keys: slot_num (6 entries), sriov_adapters (>=2 distinct
          loc-codes, repeated as needed to cover all 6 slots),
          sriov_ports (6), vios_names (6), mac_id (6), device_ip (6),
          netmasks (6), peer_ip (6), bandwidth, priority (6), auto_failover

        :avocado: tags=net,vnic,dlpar,privileged,power
        '''
        if len(self.slot_num) != 6:
            self.cancel('vnic_6x_multi_card requires exactly'
                        ' 6 slot_num entries')
        if len(set(self.backing_adapter)) < 2:
            self.cancel('vnic_6x_multi_card requires at least 2 distinct'
                        ' sriov_adapters entries')
        self._vnic_add_ping_remove(
            self.slot_num, self.mac_id, self.backing_adapter_id,
            self.sriov_port, self.device_ip, self.netmask, self.peer_ip)
        self.check_dmesg_error()

    def tearDown(self):
        if 'vios' in str(self.name.name):
            self.session.quit()
        try:
            self.change_active_device(self.slot_num[0])
        except Exception:
            self.log.debug("Unable to set back the original active device")
        self.session_hmc.quit()
        if not linux.is_os_secureboot_enabled():
            cmd = ("echo 'module ibmvnic -pt; func send_subcrq -pt'"
                   " > /sys/kernel/debug/dynamic_debug/control")
            result = process.run(cmd, shell=True, ignore_status=True)
            if result.exit_status:
                self.log.debug("failed to disable debug mode")
        if 'test_add' in str(self.name.name):
            self.session_peer.quit()
