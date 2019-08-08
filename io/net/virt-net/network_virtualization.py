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
from avocado.utils import genio

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
        self.lpar = self.get_mcp_component("NodeNameList").split('.')[0]
        if not self.lpar:
            self.cancel("LPAR Name not got from lsrsrc command")
        self.login(self.hmc_ip, self.hmc_username, self.hmc_pwd)
        cmd = 'lssyscfg -r sys  -F name'
        output = self.run_command(cmd)
        self.server = ''
        for line in output:
            if line in self.lpar:
                self.server = line
                break
        if not self.server:
            self.cancel("Managed System not got")
        cmd = 'lssyscfg -r lpar -F name -m %s' % self.server
        output = self.run_command(cmd)
        for line in output:
            if "%s-" % self.lpar in line:
                self.lpar = line
                break
        self.slot_num = self.params.get("slot_num", '*', default=None)
        if int(self.slot_num) < 3 or int(self.slot_num) > 2999:
            self.cancel("Slot invalid. Valid range: 3 - 2999")
        self.vios_name = self.params.get("vios_names", '*',
                                         default=None).split(',')
        self.sriov_port = self.params.get("sriov_ports", '*',
                                          default=None).split(',')
        self.backing_adapter = self.params.get("sriov_adapters", '*',
                                               default=None).split(',')
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
            self.vnic_priority = self.vnic_priority.split(',')
        if len(self.vnic_priority) != len(self.backing_adapter):
            self.cancel('Backing Device counts and priority counts differ')
        self.auto_failover = self.params.get(
            "auto_failover", '*', default=None)
        if self.auto_failover not in ['0', '1']:
            self.auto_failover = '1'
        self.count = int(self.params.get('vnic_test_count', default="1"))
        self.num_of_dlpar = int(self.params.get("num_of_dlpar", default='1'))
        self.device_ip = self.params.get('device_ip', '*', default=None)
        self.mac_id = self.params.get('mac_id', default="02:03:03:03:03:01")
        self.mac_id = self.mac_id.replace(':', '')
        self.netmask = self.params.get('netmask', '*', default=None)
        self.peer_ip = self.params.get('peer_ip', default=None)
        self.login(self.hmc_ip, self.hmc_username, self.hmc_pwd)
        self.run_command("uname -a")
        cmd = 'lssyscfg -m ' + self.server + \
              ' -r lpar --filter lpar_names=' + self.lpar + \
              ' -F lpar_id'
        self.lpar_id = self.run_command(cmd)[-1]
        self.vios_id = []
        for vios_name in self.vios_name:
            cmd = 'lssyscfg -m ' + self.server + \
                  ' -r lpar --filter lpar_names=' + vios_name + \
                  ' -F lpar_id'
            self.vios_id.append(self.run_command(cmd)[-1])
        cmd = 'lshwres -m %s -r sriov --rsubtype adapter -F \
              phys_loc:adapter_id' % self.server
        adapter_id_output = self.run_command(cmd)
        self.backing_adapter_id = []
        for backing_adapter in self.backing_adapter:
            for line in adapter_id_output:
                if str(backing_adapter) in line:
                    self.backing_adapter_id.append(line.split(':')[1])
        self.rsct_service_start()

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

    def run_command(self, command, timeout=300):
        '''
        SSH Run command method for running commands on remote server
        '''
        self.log.info("Running the command on hmc %s", command)
        con = self.pxssh
        con.sendline(command)
        con.expect("\n")  # from us
        con.expect(con.PROMPT, timeout=timeout)
        output = con.before.splitlines()
        con.sendline("echo $?")
        con.prompt(timeout)
        return output

    def check_slot_availability(self):
        '''
        Checks if given slot is available(free) to be used.
        :return: True if slot available, False otherwise.
        '''
        cmd = 'lshwres -r virtualio -m %s --rsubtype vnic --filter \
           "lpar_names=%s" -F slot_num' % (self.server, self.lpar)
        for slot in self.run_command(cmd):
            if 'No results were found' in slot:
                return True
            if int(self.slot_num) == int(slot):
                self.log.debug("Slot already exists")
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
        if "inoperative" in output:
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
        if not self.check_slot_availability():
            self.fail("Slot already exists")
        self.device_add_remove('add')
        output = self.list_device()
        if 'slot_num=%s' % self.slot_num not in str(output):
            self.log.debug(output)
            self.fail("lshwres fails to list Network virtualized device \
                       after add operation")

    def test_backingdevadd(self):
        '''
        Adding Backing device for Network virtualized device
        '''
        if self.check_slot_availability():
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

    def test_hmcfailover(self):
        '''
        Triggers Failover for the Network virtualized
        device
        '''
        original = self.get_active_device_logport()
        for _ in range(self.count):
            before = self.get_active_device_logport()
            self.trigger_failover(self.get_backing_device_logport())
            time.sleep(10)
            after = self.get_active_device_logport()
            self.log.debug("Active backing device: %s", after)
            if before == after:
                self.fail("No failover happened")
            if not self.ping_check():
                self.fail("Failover has affected Network connectivity")
        if original != self.get_active_device_logport():
            self.trigger_failover(original)
        if original != self.get_active_device_logport():
            self.log.warn("Fail: Activating Initial backing dev %s" % original)

    def test_unbindbind(self):
        """
        Performs driver unbind and bind for the Network virtualized device
        """
        device_id = self.find_device_id()
        try:
            for _ in range(self.count):
                for operation in ["unbind", "bind"]:
                    self.log.info("Running %s operation for Network \
                                   virtualized device", operation)
                    genio.write_file(os.path.join
                                     ("/sys/bus/vio/drivers/ibmvnic",
                                      operation), "%s" % device_id)
                    time.sleep(10)
                self.log.info("Running a ping test to check if unbind/bind \
                                    affected newtwork connectivity")
                if not self.ping_check():
                    self.fail("Ping test failed. Network virtualized \
                           unbind/bind has affected Network connectivity")
        except CmdError as details:
            self.log.debug(str(details))
            self.fail("Driver %s operation failed" % operation)

    def test_clientfailover(self):
        '''
        Performs Client initiated failover for Network virtualized
        device
        '''
        device_id = self.find_device_id()
        try:
            for _ in range(self.count):
                for val in range(int(self.backing_dev_count())):
                    self.log.info("Performing Client initiated\
                                  failover - Attempt %s", int(val + 1))
                    genio.write_file("/sys/devices/vio/%s/failover"
                                     % device_id, "1")
                    time.sleep(10)
                    self.log.info("Running a ping test to check if failover \
                                    affected Network connectivity")
                    if not self.ping_check():
                        self.fail("Ping test failed. Network virtualized \
                                   failover has affected Network connectivity")
        except CmdError as details:
            self.log.debug(str(details))
            self.fail("Client initiated Failover for Network virtualized \
                      device has failed")

    def test_vnic_auto_failover(self):
        '''
        Set the priority for vNIC active and backing devices and check if autofailover works
        '''
        if len(self.backing_adapter) >= 2:
            for _ in range(self.count):
                self.update_backing_devices()
                backing_logport = self.get_backing_device_logport()
                active_logport = self.get_active_device_logport()
                if self.enable_auto_failover():
                    if not self.change_failover_priority(backing_logport, '1'):
                        self.fail("Fail to change the priority for backing device %s", backing_logport)
                    if not self.change_failover_priority(active_logport, '100'):
                        self.fail("Fail to change the priority for active device %s", active_logport)
                    if backing_logport != self.get_active_device_logport():
                        self.fail("Auto failover of backing device failed")
                    if not self.ping_check():
                        self.fail("Auto failover has effected connectivity")
                else:
                    self.fail("Could not enable auto failover")
        else:
            self.cancel("Provide more backing device, only 1 given")

    def test_vnic_dlpar(self):
        '''
        Perform vNIC device hot add and hot remove using drmgr command
        '''
        self.update_backing_devices()
        dev_id = self.find_device_id()
        slot = self.find_virtual_slot(dev_id)
        if slot:
            try:
                for _ in range(self.num_of_dlpar):
                    self.drmgr_vnic_dlpar('-r', slot)
                    self.drmgr_vnic_dlpar('-a', slot)
            except CmdError as details:
                self.log.debug(str(details))
                self.fail("dlpar operation did not complete")
            if not self.ping_check():
                self.fail("dlpar has affected Network connectivity")
        else:
            self.fail("slot not found")

    def test_backingdevremove(self):
        '''
        Removing Backing device for Network virtualized device
        '''
        if self.check_slot_availability():
            self.fail("Slot does not exist")
        self.update_backing_devices()
        pre_remove = self.backing_dev_count()
        for count in range(1, self.backingdev_count):
            self.backing_dev_add_remove('remove', count)
        post_remove = self.backing_dev_count()
        post_remove_count = pre_remove - post_remove + 1
        if post_remove_count != self.backingdev_count:
            self.log.debug("Actual backing dev count: %d", post_remove_count)
            self.log.debug("Expected backing dev count: %d",
                           self.backingdev_count)
            self.fail("Failed to remove backing device")

    def test_remove(self):
        '''
        Network virtualized device remove operation
        '''
        if self.check_slot_availability():
            self.fail("Slot does not exist")
        self.update_backing_devices()
        self.device_add_remove('remove')
        output = self.list_device()
        if 'slot_num=%s' % self.slot_num in str(output):
            self.log.debug(output)
            self.fail("lshwres still lists the Network virtualized device \
                       after remove operation")

    def device_add_remove(self, operation):
        '''
        Adds and removes a Network virtualized device based
        on the operation
        '''
        backing_device = "backing_devices=sriov/%s/%s/%s/%s/%s/%s"\
                         % (self.vios_name[0], self.vios_id[0],
                            self.backing_adapter_id[0], self.sriov_port[0],
                            self.bandwidth, self.vnic_priority[0])
        if operation == 'add':
            cmd = 'chhwres -m %s --id %s -r virtualio --rsubtype vnic \
                   -o a -s %s -a \"auto_priority_failover=%s,mac_addr=%s,%s\" '\
                   % (self.server, self.lpar_id, self.slot_num,
                      self.auto_failover, self.mac_id, backing_device)
        else:
            cmd = 'chhwres -m %s --id %s -r virtualio --rsubtype vnic \
                   -o r -s %s'\
                   % (self.server, self.lpar_id, self.slot_num)
        try:
            self.run_command(cmd)
        except CommandFailed as cmdfail:
            self.log.debug(str(cmdfail))
            self.fail("Network virtualization %s device operation \
                       failed" % operation)

    def list_device(self):
        '''
        Lists the Network vritualized devices
        '''
        cmd = 'lshwres -r virtualio -m %s --rsubtype vnic --filter \
              \"lpar_names=%s,slots=%s\"' % (self.server, self.lpar,
                                             self.slot_num)
        try:
            output = self.run_command(cmd)
        except CommandFailed as cmdfail:
            self.log.debug(str(cmdfail))
            self.fail("lshwres operation failed ")
        return output

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
                                                                                    self.slot_num,
                                                                                    self.lpar_id,
                                                                                    self.auto_failover,
                                                                                    add_backing_device)
        else:
            cmd = 'chhwres -r virtualio --rsubtype vnic -o s -m %s -s %s \
                   --id %s -a backing_devices-=%s' % (self.server,
                                                      self.slot_num,
                                                      self.lpar_id,
                                                      add_backing_device)
        try:
            self.run_command(cmd)
        except CommandFailed as cmdfail:
            self.log.debug(str(cmdfail))
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
            output = self.run_command(cmd)
        except CommandFailed as cmdfail:
            self.log.debug(str(cmdfail))
            self.fail("lshwres operation failed ")
        return output

    def get_backing_devices(self):
        '''
        Lists the Backing devices for a Network virtualized
        device
        '''
        cmd = 'lshwres -r virtualio -m %s --rsubtype vnic --level lpar \
               --filter lpar_names=%s -F backing_devices' \
               % (self.server, self.lpar)
        try:
            output = self.run_command(cmd)
        except CommandFailed as cmdfail:
            self.log.debug(str(cmdfail))
            self.fail("lshwres operation failed ")
        return output

    def update_backing_devices(self):
        '''
        Updates the lists of backing devices, ports, vioses.
        Makes sure the active device's details are on index 0.
        '''
        logport = self.get_active_device_logport()
        for entry in self.get_backing_devices()[-1].split(','):
            if logport in entry:
                adapter_id = entry.split('/')[3]
                port = entry.split('/')[4]
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
        output = self.backing_dev_list()
        for i in output:
            if i.startswith('%s,' % self.slot_num):
                count = len(i.split(',')[1:])
        return count

    @staticmethod
    def find_device():
        """
        Finds out the latest added network virtualized device
        """
        device = netifaces.interfaces()[-1]
        return device

    def interfacewait(self):
        """
        Waits for the interface link to be UP
        """
        device = self.find_device()
        for _ in range(0, 600, 5):
            if 'UP' or 'yes' in \
                    process.system_output("ip link show %s | head -1"
                                          % device, shell=True,
                                          ignore_status=True):
                self.log.info("Network virtualized device %s is up", device)
                return True
            time.sleep(5)
        return False

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
               % (self.server, self.lpar, self.slot_num)
        try:
            output = self.run_command(cmd)
        except CommandFailed as cmdfail:
            self.log.debug(str(cmdfail))
        for entry in output:
            if 'auto_priority_failover=1' in entry:
                return True
        return False

    def enable_auto_failover(self):
        """
        Function to enable auto failover option
        """
        cmd = 'chhwres -r virtualio -m %s --rsubtype vnic \
               -o s --id %s -s %s -a auto_priority_failover=1' \
               % (self.server, self.lpar_id, self.slot_num)
        try:
            self.run_command(cmd)
        except CommandFailed as cmdfail:
            self.log.debug(str(cmdfail))
        if not self.is_auto_failover_enabled():
            return False
        return True

    def get_failover_priority(self, logport):
        """
        get the priority value for the given backing device
        """
        priority = None
        cmd = 'lshwres -r virtualio -m %s --rsubtype vnic --level lpar \
               --filter lpar_names=%s -F slot_num,backing_devices' \
               % (self.server, self.lpar)
        try:
            output = self.run_command(cmd)
        except CommandFailed as cmdfail:
            self.log.debug(str(cmdfail))
        for backing_dev in output:
            if backing_dev.startswith('%s,' % self.slot_num):
                backing_dev = backing_dev.strip('%s,"' % self.slot_num)
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
               % (self.server, self.slot_num, self.lpar_id, logport, priority)
        try:
            self.run_command(cmd)
        except CommandFailed as cmdfail:
            self.log.debug(str(cmdfail))
        if priority != self.get_failover_priority(logport):
            return False
        return True

    def configure_device(self):
        """
        Configures the Network virtualized device
        """
        device = self.find_device()
        cmd = "ip addr add %s/%s dev %s;ip link set %s up" % (self.device_ip,
                                                              self.netmask,
                                                              device,
                                                              device)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("Failed to configure Network \
                              Virtualized device")
        if not self.interfacewait():
            self.fail("Unable to bring up the link on the Network \
                       virtualized device")
        self.log.info("Successfully configured the Network \
                              Virtualized device")
        return device

    def find_device_id(self):
        """
        Finds the device id needed to trigger failover
        """
        device = self.find_device()
        device_id = process.system_output("ls -l /sys/class/net/ | \
                                           grep %s | cut -d '/' -f \
                                           5" % device,
                                          shell=True).strip()
        return device_id

    def find_virtual_slot(self, dev_id):
        """
        finds the virtual slot for the given virtual ID
        """
        output = process.system_output("lsslot", ignore_status=True,
                                       shell=True, sudo=True)
        for slot in output.split('\n'):
            if dev_id in slot:
                return slot.split(' ')[0]
        return False

    def ping_check(self):
        """
        ping check
        """
        device = self.configure_device()
        cmd = "ping -I %s %s -c 5"\
              % (device, self.peer_ip)
        output = process.system_output(cmd)
        for log in output.split('\n'):
            if ' 0% packet loss' in log.split(','):
                return True
        return False

    def trigger_failover(self, logport):
        '''
        Triggers failover from HMC
        '''
        cmd = 'chhwres -r virtualio --rsubtype vnicbkdev -o act -m %s \
               -s %s --id %s \
               --logport %s' % (self.server, self.slot_num,
                                self.lpar_id, logport)
        try:
            self.run_command(cmd)
        except CommandFailed as cmdfail:
            self.log.debug(str(cmdfail))
            self.fail("Command to set %s as Active has failed" % logport)

    def get_backing_device_logport(self):
        '''
        Get the logical port id of the
        backing device
        '''
        for backing_dev in self.backing_dev_list():
            if backing_dev.startswith('%s,' % self.slot_num):
                backing_dev = backing_dev.strip('%s,"' % self.slot_num)
                for entry in backing_dev.split(','):
                    entry = entry.split('/')
                    if '0' in entry[2] and 'Operational' in entry[3]:
                        logport = entry[1]
                        break
        return logport

    def get_active_device_logport(self):
        '''
        Get the logical port id of the Network
        virtualized device
        '''
        for backing_dev in self.backing_dev_list():
            if backing_dev.startswith('%s,' % self.slot_num):
                backing_dev = backing_dev.strip('%s,"' % self.slot_num)
                for entry in backing_dev.split(','):
                    entry = entry.split('/')
                    if '1' in entry[2]:
                        logport = entry[1]
                        break
        return logport

    def is_backing_device_active(self):
        '''
        TO check the status of the backing device
        after failover
        '''
        for backing_dev in self.backing_dev_list():
            if backing_dev.startswith('%s,' % self.slot_num):
                val = int(backing_dev.split(',')[1:][1].split('/')[2])
        if val:
            return True
        return False

    def tearDown(self):
        if self.pxssh.isalive():
            self.pxssh.terminate()


if __name__ == "__main__":
    main()
