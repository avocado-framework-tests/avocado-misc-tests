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
import netifaces
from avocado import Test
from avocado.utils import process
from avocado.utils import distro
from avocado.utils import dmesg
from avocado.utils.software_manager import SoftwareManager
from avocado.utils.process import CmdError
from avocado import skipIf, skipUnless
from avocado.utils import genio
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.network.hosts import LocalHost
from avocado.utils.ssh import Session
from avocado.utils import wait

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
        self.hmc_ip = self.get_mcp_component("HMCIPAddr")
        if not self.hmc_ip:
            self.cancel("HMC IP not got")
        self.hmc_pwd = self.params.get("hmc_pwd", '*', default=None)
        self.hmc_username = self.params.get("hmc_username", '*', default=None)
        self.lpar = self.get_partition_name("Partition Name")
        if not self.lpar:
            self.cancel("LPAR Name not got from lparstat command")
        for root, dirct, files in os.walk("/root/.ssh"):
            for file in files:
                if file.startswith("avocado-master-root"):
                    path = os.path.join(root, file)
                    os.remove(path)
        self.session_hmc = Session(self.hmc_ip, user=self.hmc_username,
                                   password=self.hmc_pwd)
        if not self.session_hmc.connect():
            self.cancel("failed connecting to HMC")
        cmd = 'lssyscfg -r sys  -F name'
        output = self.session_hmc.cmd(cmd)
        self.server = self.params.get("server", "*", default=None)
        if not self.server:
            for line in output.stdout_text.splitlines():
                if line in self.lpar:
                    self.server = line
                    break
        if not self.server:
            self.cancel("Managed System not got")
        self.slot_num = self.params.get("slot_num", '*', default=None)
        self.slot_num = self.slot_num.split(' ')
        for slot in self.slot_num:
            if int(slot) < 3 or int(slot) > 2999:
                self.cancel("Slot invalid. Valid range: 3 - 2999")
        self.vios_name = self.params.get("vios_names", '*',
                                         default=None).split(' ')
        self.sriov_port = self.params.get("sriov_ports", '*',
                                          default=None).split(' ')
        self.backing_adapter = self.params.get("sriov_adapters", '*',
                                               default=None).split(' ')
        if len(self.sriov_port) != len(self.backing_adapter):
            self.cancel('Backing Device counts and port counts differ')
        if len(self.vios_name) != len(self.backing_adapter):
            self.cancel('Backing Device counts and vios name counts differ')
        self.backingdev_count = len(self.backing_adapter)
        self.bandwidth = self.params.get("bandwidth", '*', default=None)
        self.vnic_priority = self.params.get(
            "priority", '*', default=None)
        if not self.vnic_priority:
            self.vnic_priority = [50] * len(self.backing_adapter)
        else:
            self.vnic_priority = self.vnic_priority.split(' ')
        if len(self.vnic_priority) != len(self.backing_adapter):
            self.cancel('Backing Device counts and priority counts differ')
        self.auto_failover = self.params.get(
            "auto_failover", '*', default=None)
        if self.auto_failover not in ['0', '1']:
            self.auto_failover = '1'
        self.vios_ip = self.params.get('vios_ip', '*', default=None)
        self.vios_user = self.params.get('vios_username', '*', default=None)
        self.vios_pwd = self.params.get('vios_pwd', '*', default=None)
        self.count = int(self.params.get('vnic_test_count', default="1"))
        self.num_of_dlpar = int(self.params.get("num_of_dlpar", default='1'))
        self.device_ip = self.params.get('device_ip', '*',
                                         default=None).split(' ')
        self.mac_id = self.params.get('mac_id',
                                      default="02:03:03:03:03:01").split(' ')
        self.mac_id = [mac.replace(':', '') for mac in self.mac_id]
        self.netmask = self.params.get('netmasks', '*', default=None).split(' ')
        self.peer_ip = self.params.get('peer_ip', default=None).split(' ')
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
            self.vios_id.append(self.session_hmc.cmd(cmd).stdout_text.split()[0])
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
        cmd = "echo 'module ibmvnic +pt; func send_subcrq -pt' > /sys/kernel/debug/dynamic_debug/control"
        result = process.run(cmd, shell=True, ignore_status=True)
        if result.exit_status:
            self.fail("failed to enable debug mode")

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
        :return: True if slot available, False otherwise.
        '''
        cmd = 'lshwres -r virtualio -m %s --rsubtype vnic --filter \
           "lpar_names=%s" -F slot_num' % (self.server, self.lpar)
        for slot in self.session_hmc.cmd(cmd).stdout_text.splitlines():
            if 'No results were found' in slot:
                return True
            if slot_num == slot:
                self.log.debug("Slot %s already exists" % slot_num)
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
                    'rsct.core', 'DynamicRM', 'powerpc-utils']
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

    def test_add(self):
        '''
        Network virtualized device add operation
        '''
        for slot, mac, sriov_port, adapter_id, device_ip, netmask in zip(self.slot_num, self.mac_id,
                                                                         self.sriov_port,
                                                                         self.backing_adapter_id,
                                                                         self.device_ip, self.netmask):
            if not self.check_slot_availability(slot):
                self.fail("Slot does not exist")
            self.device_add_remove(slot, mac, sriov_port, adapter_id, 'add')
            self.interface_naming(mac, slot)
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
        self.check_dmesg_error()

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
            if networkinterface.ping_check(self.peer_ip[0], count=5) is not None:
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
                    if networkinterface.ping_check(self.peer_ip[0], count=5, options="-w50") is not None:
                        self.fail("Ping test failed. Network virtualized \
                                   failover has affected Network connectivity")
        except CmdError as details:
            self.log.debug(str(details))
            self.fail("Client initiated Failover for Network virtualized \
                      device has failed")
        self.check_dmesg_error()

    def test_vnic_auto_failover(self):
        '''
        Set the priority for vNIC active and backing devices and check if autofailover works
        '''
        if len(self.backing_adapter) >= 2:
            for _ in range(self.count):
                self.update_backing_devices(self.slot_num[0])
                backing_logport = self.get_backing_device_logport(self.slot_num[0])
                active_logport = self.get_active_device_logport(self.slot_num[0])
                if self.enable_auto_failover():
                    if not self.change_failover_priority(backing_logport, '1'):
                        self.fail("Fail to change the priority for backing device %s", backing_logport)
                    if not self.change_failover_priority(active_logport, '100'):
                        self.fail("Fail to change the priority for active device %s", active_logport)
                    time.sleep(60)
                    if backing_logport != self.get_active_device_logport(self.slot_num[0]):
                        self.fail("Auto failover of backing device failed")
                    device = self.find_device(self.mac_id[0])
                    networkinterface = NetworkInterface(device, self.local)
                    if networkinterface.ping_check(self.peer_ip[0], count=5) is not None:
                        self.fail("Auto failover has effected connectivity")
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
        if not self.session.connect():
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
            self.validate_vios_command('rmdev -l %s' % vnic_backing_device, 'Defined')

        after = self.get_active_device_logport(self.slot_num[0])
        self.log.debug("Active backing device after: %s", after)

        if before == after:
            self.fail("failover not occur")
        time.sleep(60)

        if vnic_backing_device:
            self.validate_vios_command('mkdev -l %s' % vnic_backing_device, 'Available')
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

    def test_backingdevremove(self):
        '''
        Removing Backing device for Network virtualized device
        '''
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
            cmd = 'chhwres -r virtualio --rsubtype vnic -o s -m %s -s %s \
                   --id %s -a \"auto_priority_failover=%s,backing_devices+=%s\"' % (self.server,
                                                                                    self.slot_num[0],
                                                                                    self.lpar_id,
                                                                                    self.auto_failover,
                                                                                    add_backing_device)
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

    def get_backing_devices(self):
        '''
        Lists the Backing devices for a Network virtualized
        device
        '''
        cmd = 'lshwres -r virtualio -m %s --rsubtype vnic --level lpar \
               --filter lpar_names=%s -F backing_devices' \
               % (self.server, self.lpar)
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
        for entry in self.get_backing_devices()[-1].split(','):
            if logport in entry:
                adapter_id = entry.split('/')[3]
                port = entry.split('/')[4]
        if not adapter_id:
            return
        for i in range(0, len(self.backing_adapter_id)):
            if adapter_id == self.backing_adapter_id[i]:
                if port == self.sriov_port[i]:
                    index = i
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
               % (self.server, self.slot_num[0], self.lpar_id, logport, priority)
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
                                           grep %s | cut -d '/' -f \
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
        for backing_dev in self.backing_dev_list().splitlines():
            if backing_dev.startswith('%s,' % slot):
                backing_dev = backing_dev.strip('%s,"' % slot)
                for entry in backing_dev.split(','):
                    entry = entry.split('/')
                    if '1' in entry[2]:
                        logport = entry[1]
                        break
        return logport

    def is_backing_device_active(self, slot):
        '''
        TO check the status of the backing device
        after failover
        '''
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
        file = "/etc/udev/rules.d/70-persistent-net.rules-%s" % slot
        with open(file, "w") as interface_conf:
            interface_conf.write("SUBSYSTEM==net \n")
            interface_conf.write("ACTION==add \n")
            interface_conf.write("DRIVERS==? \n")
            interface_conf.write("ATTR{address}==%s \n" % mac_addrs)
            interface_conf.write("ATTR{dev_id}==0x0 \n")
            interface_conf.write("ATTR{type}==1 \n")
            interface_conf.write("KERNEL==vnic \n")
            interface_conf.write("NAME=vnic%s \n" % slot)

    def wait_intrerface(self, device_name):
        """
        Wait till interface come up
        """
        for _ in range(0, 120, 10):
            for interface in netifaces.interfaces():
                if device_name == interface:
                    self.log.info("Network virtualized device %s is up", device_name)
                    return True
                time.sleep(5)
        return False

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

    def tearDown(self):
        self.session_hmc.quit()
        if 'vios' in str(self.name.name):
            self.session.quit()
        cmd = "echo 'module ibmvnic -pt; func send_subcrq -pt' > /sys/kernel/debug/dynamic_debug/control"
        result = process.run(cmd, shell=True, ignore_status=True)
        if result.exit_status:
            self.log.debug("failed to disable debug mode")
