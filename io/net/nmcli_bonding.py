#!/usr/bin/env python

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
# Copyright: 2025 IBM
# Author: Vaishnavi Bhat<vaishnavi@linux.vnet.ibm.com>

"""
Bonding test
Channel bonding enables two or more network interfaces to act as one,
simultaneously increasing the bandwidth and providing redundancy.
"""


import time
import os
from avocado import Test
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils import distro
from avocado.utils import process
from avocado.utils import linux_modules
from avocado.utils.ssh import Session
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.network.hosts import LocalHost, RemoteHost

class Bonding(Test):
    '''
    Channel bonding enables two or more network interfaces to act as one,
    simultaneously increasing the bandwidth and providing redundancy.
    '''

    def setUp(self):
        self.detected_distro = distro.detect()
        smm = SoftwareManager()
        depends = []
        if self.detected_distro.name == "Ubuntu":
            depends.extend(["openssh-client", "iputils-ping"])
        elif self.detected_distro.name in ["rhel", "fedora", "centos", "redhat"]:
            depends.extend(["openssh-clients", "iputils"])
        else:
            depends.extend(["openssh", "iputils"])
        for pkg in depends:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel("%s package is need to test" % pkg)
        self.mode = self.params.get("bonding_mode", default="")
        if 'setup' in str(self.name) or 'run' in str(self.name):
            if not self.mode:
                self.cancel("test skipped because mode not specified")
        interfaces = netifaces.interfaces()
        self.peer_public_ip = self.params.get("peer_public_ip", default="")
        self.user = self.params.get("user_name", default="root")
        self.password = self.params.get("peer_password", '*',
                                        default="None")
        self.host_interfaces = self.params.get("bond_interfaces",
                                               default="").split(" ")
        if not self.host_interfaces:
            self.cancel("user should specify host interfaces")
        self.peer_interfaces = self.params.get("peer_interfaces",
                                               default="").split(" ")
        for self.host_interface in self.host_interfaces:
            if self.host_interface not in interfaces:
                self.cancel("interface is not available")
        self.peer_first_ipinterface = self.params.get(
            "peer_ips", default="").split(" ")
        if not self.peer_interfaces or self.peer_first_ipinterface == "":
            self.cancel("peer machine should available")
        self.ipaddr = self.params.get("host_ips", default="").split(" ")
        self.netmask = self.params.get("netmask", default="")
        self.peer_bond_needed = self.params.get("peer_bond_needed",
                                                default=False)
        self.localhost = LocalHost()
        if 'setup' in str(self.name.name):
            for ipaddr, interface in zip(self.ipaddr, self.host_interfaces):
                networkinterface = NetworkInterface(interface, self.localhost)
                networkinterface.save(ipaddr, self.netmask)
            for ipaddr, interface in zip(self.peer_first_ipinterface,
                                         self.peer_interfaces):
                if self.peer_bond_needed:
                    self.remotehost = RemoteHost(
                        self.peer_public_ip,
                        self.user, password=self.password)
                    peer_networkinterface = NetworkInterface(interface,
                                                             self.remotehost)
                    peer_networkinterface.save(ipaddr, self.netmask)
        self.miimon = self.params.get("miimon", default="100")
        self.fail_over_mac = self.params.get("fail_over_mac",
                                             default="2")
        self.downdelay = self.params.get("downdelay", default="0")
        self.bond_name = self.params.get("bond_name", default="tempbond")
        self.net_path = "/sys/class/net/"
        self.bond_status = "/proc/net/bonding/%s" % self.bond_name
        self.bond_dir = os.path.join(self.net_path, self.bond_name)
        self.bonding_slave_file = "%s/bonding/slaves" % self.bond_dir
        self.bonding_masters_file = "%s/bonding_masters" % self.net_path
        self.peer_bond_needed = self.params.get("peer_bond_needed",
                                                default=False)
        self.peer_wait_time = self.params.get("peer_wait_time", default=20)
        self.sleep_time = int(self.params.get("sleep_time", default=10))
        self.peer_wait_time = self.params.get("peer_wait_time", default=5)
        self.mtu = self.params.get("mtu", default=1500)
        self.ib = False
        if self.host_interface[0:2] == 'ib':
            self.ib = True
        self.log.info("Bond Test on IB Interface? = %s", self.ib)

        dir = os.listdir('/sys/class/net')

        '''
        An individual interface, that has a LACP PF, cannot communicate without
        being bonded. So the test uses the public ip address to create an SSH
        session instead of the private one when setting up a bonding interface.
        '''
        if self.mode == "4" and "setup" in str(self.name.name):
            self.session = Session(self.peer_public_ip, user=self.user,
                                   password=self.password)
        else:
            self.session = Session(self.peer_first_ipinterface[0], user=self.user,
                                   password=self.password)

        self.session.cleanup_master()
        if not self.session.connect():
            '''
            LACP bond interface takes some time to get it to ping peer after it
            is setup. This code block tries at most 5 times to get it to connect
            to the peer.
            '''
            if self.mode == "4":
                connect = False
                for _ in range(5):
                    if self.session.connect():
                        connect = True
                        self.log.info("Was able to connect to peer.")
                        break
                    time.sleep(5)
                if not connect:
                    self.cancel("failed connecting to peer")
            else:
                self.cancel("failed connecting to peer")
        if self.mode == "4" and "setup" in str(self.name.name):
            self.remotehost = RemoteHost(self.peer_public_ip, self.user,
                                         password=self.password)
        else:
            self.remotehost = RemoteHost(self.peer_first_ipinterface[0], self.user,
                                         password=self.password)

    def nmcli_bond_setup(self, arg1, arg2):
        '''
        create a bond interface with the slave interfaces
        '''
        if arg1 == "local":
            self.log.info("Configuring Bonding on Local machine")
            self.log.info("--------------------------------------")
            linux_modules.load_module("bonding")
        
        # Select different bonding parameters based on mode
            dict = {'0': ['packets_per_slave', 'resend_igmp'],
                    '1': ['num_unsol_na', 'primary', 'primary_reselect',
                          'resend_igmp'],
                    '2': ['xmit_hash_policy'],
                    '4': ['lacp_rate', 'xmit_hash_policy'],
                    '5': ['tlb_dynamic_lb', 'primary', 'primary_reselect',
                          'resend_igmp', 'xmit_hash_policy', 'lp_interval'],
                    '6': ['primary', 'primary_reselect', 'resend_igmp',
                          'lp_interval']}
            if self.mode in dict.keys():
                for param in dict[self.mode]:
                    param_value = self.params.get(param, default='')
                    if param_value:
                        bond_param.append(f"{param}={param_value}")
            bond_options_str = f"mode={self.mode},miimon={self.miimon},downdelay={self.downdelay}"
            if bond_param:
                bond_options_str += "," + ",".join(bond_param)
        #bond_options_str += 

        # Create bond interface
            cmd = f"nmcli con add type bond ifname {self.bond_name} bond.options {bond_options_str}'"
            try:
                process.system(cmd, shell=True, ignore_status=True)
            except Exception as e:
                self.log.error(f"Failed to create bond interface: {e}")
                return
    
        # Add slave interface to the bond
            for interface in self.host_interfaces:
                try:
                    slave_cmd = f"nmcli con add type ethernet ifname {interface} master {self.bond_name}"
                    process.system(slave_cmd, shell=True, ignore_status=True)
                except Exception as e:
                    self.log.error(f"Failed to add {interface} as slave interface: {e}")

        # Bring-up bond interface
            cmd = f"nmcli con up {self.bond_name}"
            try:
                process.system(cmd, shell=True, ignore_status=True)
            except Exception as e:
                self.log.error(f"Failed to bring up the bond interface: {e}")
                return
        
        # Bring-up slave interfaces
            for interface in self.host_interfaces:
                try:
                    slave_cmd = f"nmcli con up {interface}"
                    process.system(slave_cmd, shell=True, ignore_status=True) 
                except Exception as e:
                    self.log.error(f"Failed to bring-up the slave interface {interface}: {e}")

        # Check for successful bond creation
            verify_bond = f"nmcli device status | grep -w {self.bond_name}"
            if process.system(verify_bond, shell=True, ignore_status=True) != 0:
                self.log.error(f"Bond interface {self.bond_name} not found in list.")
        
    
        # Configure bond interface with IP
            ip_with_mask = f"{self.local_ip}/{self.net_mask[0]}"
            cmd_ip_set = f"nmcli con modify {self.bond_name} ipv4.addresses {ip_with_mask} ipv4.method manual"
            process.system(cmd_ip_set, shell=True, ignore_status=True)
            cmd_bond_uup = f"nmcli con up {self.bond_name}"
            if process.system(cmd_bond_up, shell=True, ignore_status=True) != 0:
                self.log.error(f"Failed to set IP address {ip_with_mask} for bond {self.bond_name}")

        # Check for bond link-up
            cmd = f"cat /proc/net/bonding/{self.bond_name}"
            try:
                output = process.system_output(cmd, shell=True).decode("utf-8")
                if "Slave Interface" in output and "MII Status: up" in output:
                    self.log.info(f"Bond {self.bond_name} is active and link is up.")
                else:
                    self.log.error(f"Bond {bondname} exists but bond link is not up. Check link of the slave interfaces.")
            except Exception as e:
                self.log.error(f"Bond creation on host machine has FAILED: {e}")

            if self.gateway:
                gw_cmd = f"nmcli con modify {self.bond_name} ipv4.gateway {self.gateway} ipv4.method"
                if process.system(gw_cmd, shell=True, ignore_status=True) !=0:
                    self.log.error(f"Failed to set gateway {self.gateway} for the bond interface")
                gw_up = f"nmcli con up {self.bond_name}"
                process.system(gw_up, shell=True, ignore_status=True)

        # Set networkinterface object to bond
            self.networkinterface = NetworkInterface(
                                self.bond_name, self.localhost)

        else:
            self.log.info("Configuring Mode0 bond on Peer machine")
            self.log.info("------------------------------------------")
            for ipaddr, interface in zip(self.peer_first_ipinterface,
                                     self.peer_interfaces):
                peer_networkinterface = NetworkInterface(interface,
                                                     self.remotehost)
        
            bond_cmd += 'modprobe bonding;'
            bond_cmd += f"nmcli con add type bond ifname {self.bond_name} bond.options 'mode=<self.mode>,miimon=<self.miimon>'"
        #bond_cmd += f"nmcli c up {self.bond_name}"

            for interface in self.peer_interfaces:
                bond_cmd += f"nmcli con add type ethernet ifname {interface} master {self.bond_name}"

            bond_cmd += f"nmcli con up {self.bond_name}"

            for interface in self.peer_interfaces:
                bond_cmd += f"nmcli con up {interface})"

            ip_with_mask = f"{self.peer_first_ipinterface[0]}/{self.net_mask[0]}"
            bond_cmd += f"nmcli con modify {self.bond_name} ipv4.addresses {ip_with_mask} ipv4.method"
            bond_cmd += f"nmcli con up {self.bond_name}"

            output = self.session.cmd(bond_cmd)
            if not output.exit_status == 0:
                self.fail("Bond setup failed in peer machine") 

    def test_bond_setup(self):
        '''
        Test to validate the bond setup on host / peer 
        '''
        self.nmcli_bond_setup("local", self.mode)
        if self.networkinterface.ping_check(self.peer_first_ipinterface[0], count=20) is not None: 
            self.fail("Ping test from bond to peer FAILED")
      
    def get_bond_status(self):
        '''
        Get the status of the bond from /proc fs
        '''
        try:
            output = process.system_output("cat /proc/net/bonding/{self.bond_name}",shell=True).decode("utf-8") 
            if "MII Status: up" in output:
                self.log.info("Bond is UP")
            else:
                self.log.info("Bond is DOWN")
        except Exception as e:
            self.log.error("Failed to get Bond status")

    def is_vnic(self):
        '''
        check if slave interface is vnic
        '''
        for interface in self.host_interfaces:
            cmd = "lsdevinfo -q name=%s" % interface
            if 'type="IBM,vnic"' in process.system_output(cmd, shell=True).decode("utf-8"):
                return True
        return False
                
    def test_bond_failover(self):
        '''
        Test scenarios for slave failover 
        '''
        self.log.info(f"Starting bond failover test for {bondname}")
        for interface in self.interfaces:
            self.log.info(f"Bringing down slave interface: {interface}")
            down_cmd = f"ip link set {interface} down"
            process.system(down_cmd, shell=True, ignore_status=True)
            time.sleep(5)  # Wait for failover to trigger
            self.get_bond_status()
            if self.networkinterface.ping_check(self.peer_first_ipinterface[0], count=20):
                self.log.info(f"Failover test passed when slave {interface} is down")
            else:
                self.fail(f"Ping test failed when slave {interface} is down.")
            up_cmd = f"ip link set {interface} up"
            process.system(up_cmd, shell=True, ignore_status=True) 
        for interface in self.interfaces:
            self.log.info(f"Bringing down both the slave interfaces")
            down_cmd = f"ip link set {interface} down"
            process.system(down_cmd, shell=True, ignore_status=True)
        if not self.networkinterface.ping_check(self.peer_first_ipinterface[0], count=20):
            self.get_bond_status()
            self.log.info("Ping to Bond interface failed when all slave interfaces\
                           are down. This is expected")
        for interface in self.interfaces:
            up_cmd = f"ip link set {interface} up"
            process.system(up_cmd, shell=True, ignore_status=True) 

        self.bond_mtu_test()

    def bond_mtu_test(self):
        '''
        Ping test for bond with varying mtu sizes
        '''
        bond_mtu = ['2000', '3000', '4000', '5000', '6000', '7000',
                    '8000', '9000']
        if self.is_vnic():
            bond_mtu = ['9000']
        for mtu in bond_mtu:
            self.networkinterface = NetworkInterface(self.bond_name,
                                                     self.localhost)
            if self.networkinterface.set_mtu(mtu) is not None:
                self.cancel("Failed to set mtu in host")
            for interface in self.peer_interfaces:
                peer_networkinterface = NetworkInterface(interface,
                                                         self.remotehost)
                if peer_networkinterface.set_mtu(mtu) is not None:
                    self.cancel("Failed to set mtu in peer")
            if not self.networkinterface.ping_check(self.peer_first_ipinterface[0], count=20):
                self.fail(f"Ping fail in mode {self.mode} after MTU change to {mtu}")
            else:
                self.log.info(
                    f"Ping success for mode {self.mode} bond with MTU {mtu}")
            if self.networkinterface.set_mtu('1500'):
                self.cancel("Failed to set mtu back to 1500 in host")
            for interface in self.peer_interfaces:
                peer_networkinterface = NetworkInterface(interface,
                                                         self.remotehost)
                if peer_networkinterface.set_mtu('1500') is not None:
                    self.cancel("Failed to set mtu back to 1500 in peer")

    def nmcli_bond_cleanup(self, arg1):
        '''
        Clear the bond interface and clean up the interface config
        '''
        if arg1 == "local":
            self.log.info(f"Removing Bond interface {self.bond_name} on local machine")
            self.log.info("------------------------------------------------")
            for interface in self.interfaces:
                del_cmd = f"nmcli con delete {interface}"
                if process.system(del_cmd, shell=True, ignore_status=True) != 0:
                    self.log.error(f"Failed to delete slave connection {interface}")
            del_cmd = f"nmcli con delete {self.bond_name}"
            if process.system(del_cmd, shell=True, ignore_status=True) != 0:
                self.log.error(f"Failed to delete bond interface {self.bond_name}")
            else:
                self.log.info(f"Bond interface {self_bond_name} removed successfully.")
            linux_modules.unload_module("bonding")
            time.sleep(self.sleep_time)
        else:
            self.log.info("Removing Bonding configuration on Peer machine")
            self.log.info("------------------------------------------------")
            for interface in self.peer_interfaces:
                del_cmd += f"nmcli con delete {interface}"
            del_cmd += f"nmcli con delete {self.bond_name}"
            del_cmd += "rmmod bonding"
            output = self.session.cmd(del_cmd)
            if not output.exit_status == 0:
                self.log.info("bond removing command failed in peer machine")

    def test_bond_cleanup(self):
        '''
        Test to cleanup bond and its configuration
        '''
        self.nmcli_bond_cleanup(local)
        for ipaddr, host_interface in zip(self.ipaddr, self.host_interfaces):
            networkinterface = NetworkInterface(host_interface, self.localhost)
            try:
                networkinterface.restore_from_backup()
                networkinterface.bring_up()
            except Exception:
                self.fail("Interface is taking long time to link up")
        if self.peer_bond_needed:
            self.nmcli_bond_cleanup("peer")
            for ipaddr, interface in zip(self.peer_first_ipinterface, \
                                            self.peer_interfaces):
                self.remotehost = RemoteHost(
                    self.peer_public_ip, self.user,
                                   password=self.password)
                peer_networkinterface = NetworkInterface(interface,
                                                          self.remotehost)
                try:
                    peer_networkinterface.restore_from_backup()
                    peer_networkinterface.bring_up()
                    time.sleep(self.sleep_time)
                    peer_networkinterface.set_mtu("1500")
                except Exception:
                    peer_networkinterface.save(ipaddr, self.netmask)
                time.sleep(self.sleep_time)
            self.remotehost.remote_session.quit()

    def tearDown(self):
        self.session.quit()
