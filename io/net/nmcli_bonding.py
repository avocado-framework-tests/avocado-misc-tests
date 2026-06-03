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
import netifaces
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
        # Track bond creation state for tearDown cleanup
        self.bond_created = False
        self.peer_bond_created = False
        self.test_passed = False
        self.err = []

        # Verify NetworkManager is the active network service
        nm_check = process.system(
            "systemctl is-active NetworkManager",
            shell=True, ignore_status=True)
        if nm_check != 0:
            self.cancel(
                "NetworkManager is not active. This test requires "
                "NetworkManager (nmcli). Please enable it with: "
                "systemctl enable --now NetworkManager")

        self.ipaddr = self.params.get("host_ips", default="").split(" ")
        self.netmask = self.params.get("netmask", default="")
        self.localhost = LocalHost()
        self.host_interfaces = self.params.get(
            "bond_interfaces", default="").split(" ")
        self.bond_name = self.params.get("bond_name", default="tempbond")
        if not self.host_interfaces or self.host_interfaces == ['']:
            self.cancel("user should specify host interfaces")
        if not self.netmask:
            self.cancel("netmask parameter is required")
        if 'setup' in str(self.name):
            interface = self.host_interfaces[0]
        else:
            interface = self.bond_name
        if 'setup' in str(self.name.name):
            for ipaddr, ifc in zip(self.ipaddr, self.host_interfaces):
                networkinterface = NetworkInterface(ifc, self.localhost)
                try:
                    networkinterface.add_ipaddr(ipaddr, self.netmask)
                except Exception as e:
                    self.log.info("IP address already configured: %s", e)
        self.detected_distro = distro.detect()
        smm = SoftwareManager()
        depends = []
        distro_name = self.detected_distro.name.lower()
        if distro_name == "ubuntu":
            depends.extend(
                ["openssh-client", "iputils-ping", "network-manager"])
        elif distro_name in ["rhel", "fedora", "centos", "redhat"]:
            depends.extend(["openssh-clients", "iputils", "NetworkManager"])
        elif distro_name in ["sles", "suse", "opensuse"]:
            depends.extend(["openssh", "iputils", "NetworkManager"])
        else:
            depends.extend(["openssh", "iputils", "NetworkManager"])
        for pkg in depends:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel("%s package is needed to test" % pkg)
        self.mode = self.params.get("bonding_mode", default="")
        if 'setup' in str(self.name) or 'run' in str(self.name):
            if not self.mode:
                self.cancel("test skipped because mode not specified")
        interfaces = netifaces.interfaces()
        self.peer_public_ip = self.params.get("peer_public_ip", default="")
        self.user = self.params.get("user_name", default="root")
        self.password = self.params.get("peer_password", '*',
                                        default="None")
        self.peer_interfaces = self.params.get("peer_interfaces",
                                               default="").split(" ")
        for self.host_interface in self.host_interfaces:
            if self.host_interface not in interfaces:
                self.cancel("interface is not available")
        self.peer_first_ipinterface = self.params.get(
            "peer_ips", default="").split(" ")
        if not self.peer_interfaces or self.peer_interfaces == [''] \
                or not self.peer_first_ipinterface \
                or self.peer_first_ipinterface == ['']:
            self.cancel("peer machine should be available")
        self.peer_bond_needed = self.params.get("peer_bond_needed",
                                                default=False)
        if 'setup' in str(self.name.name):
            for ipaddr, ifc in zip(self.peer_first_ipinterface,
                                   self.peer_interfaces):
                if self.peer_bond_needed:
                    self.remotehost = RemoteHost(
                        self.peer_public_ip,
                        self.user, password=self.password)
                    peer_networkinterface = NetworkInterface(
                        ifc, self.remotehost)
                    try:
                        peer_networkinterface.add_ipaddr(
                            ipaddr, self.netmask)
                    except Exception as e:
                        self.log.info(
                            "IP address on peer already configured: %s", e)
        self.miimon = self.params.get("miimon", default="100")
        self.fail_over_mac = self.params.get("fail_over_mac", default="2")
        self.downdelay = self.params.get("downdelay", default="0")
        self.net_path = "/sys/class/net/"
        self.bond_status = "/proc/net/bonding/%s" % self.bond_name
        self.bond_dir = os.path.join(self.net_path, self.bond_name)
        self.bonding_slave_file = "%s/bonding/slaves" % self.bond_dir
        self.bonding_masters_file = "%s/bonding_masters" % self.net_path
        self.peer_wait_time = int(
            self.params.get("peer_wait_time", default=20))
        self.sleep_time = int(self.params.get("sleep_time", default=10))
        self.mtu = self.params.get("mtu", default=1500)
        self.ib = False
        if self.host_interfaces[0][0:2] == 'ib':
            self.ib = True
        self.log.info("Bond Test on IB Interface? = %s", self.ib)
        try:
            iface_addrs = netifaces.ifaddresses(interface)
            if (netifaces.AF_INET not in iface_addrs
                    or not iface_addrs[netifaces.AF_INET]):
                self.cancel(
                    "Interface %s does not have an IPv4 address "
                    "configured" % interface)
            self.local_ip = iface_addrs[netifaces.AF_INET][0]['addr']
        except (KeyError, ValueError, IndexError) as e:
            self.cancel(
                "Failed to get IP address for interface %s: %s"
                % (interface, e))

        self.session = Session(self.peer_public_ip, user=self.user,
                               password=self.password)
        self.session.cleanup_master()
        if not self.session.connect():
            # LACP bond interface takes some time to get it to ping peer
            # after it is setup. This code block tries at most 5 times
            # to get it to connect to the peer.
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
            self.remotehost = RemoteHost(
                self.peer_first_ipinterface[0], self.user,
                password=self.password)

    def nmcli_bond_setup(self, arg1, arg2):
        '''
        create a bond interface with the slave interfaces
        '''
        if arg1 == "local":
            self.log.info("Configuring Bonding on Local machine")
            self.log.info("--------------------------------------")
            linux_modules.load_module("bonding")
            bond_options_str = (
                "mode=%s,miimon=%s,downdelay=%s"
                % (self.mode, self.miimon, self.downdelay))
            # Select different bonding parameters based on mode
            bond_param = {
                '0': ['packets_per_slave', 'resend_igmp'],
                '1': ['num_unsol_na', 'primary', 'primary_reselect',
                      'resend_igmp'],
                '2': ['xmit_hash_policy'],
                '4': ['lacp_rate', 'xmit_hash_policy'],
                '5': ['tlb_dynamic_lb', 'primary', 'primary_reselect',
                      'resend_igmp', 'xmit_hash_policy', 'lp_interval'],
                '6': ['primary', 'primary_reselect', 'resend_igmp',
                      'lp_interval']}
            if self.mode in bond_param:
                additional_params = []
                for param in bond_param[self.mode]:
                    param_value = self.params.get(param, default='')
                    if param_value:
                        additional_params.append(
                            "%s=%s" % (param, param_value))
                if additional_params:
                    bond_options_str += "," + ",".join(additional_params)

            # Create bond interface
            cmd = ("nmcli con add type bond ifname %s con-name %s "
                   "bond.options \"%s\""
                   % (self.bond_name, self.bond_name, bond_options_str))
            try:
                process.system(cmd, shell=True, ignore_status=True)
            except Exception as e:
                self.log.error("Failed to create bond interface: %s", e)
                return

            # Add slave interface to the bond
            for interface in self.host_interfaces:
                try:
                    slave_down = (
                        "nmcli -t -f NAME,UUID con show | "
                        "awk -F: '/^%s/{print $2}' | "
                        "xargs -r -n1 nmcli con down uuid" % interface)
                    process.system(slave_down, shell=True,
                                   ignore_status=True)
                except Exception as e:
                    self.log.error(
                        "Failed to link down the interface %s: %s",
                        interface, e)
                time.sleep(10)
                try:
                    slave_cmd = (
                        "nmcli con add type ethernet ifname %s "
                        "con-name slave-%s master %s"
                        % (interface, interface, self.bond_name))
                    process.system(slave_cmd, shell=True,
                                   ignore_status=True)
                except Exception as e:
                    self.log.error(
                        "Failed to add %s as slave interface: %s",
                        interface, e)

            # Bring-up bond interface
            time.sleep(5)
            cmd = "nmcli con up %s" % self.bond_name
            try:
                process.system(cmd, shell=True, ignore_status=True)
            except Exception as e:
                self.log.error(
                    "Failed to bring up the bond interface: %s", e)
                return

            # Check for successful bond creation
            verify_bond = ("nmcli device status | grep -w %s"
                           % self.bond_name)
            if process.system(verify_bond, shell=True,
                              ignore_status=True) != 0:
                self.fail("Bond interface %s not found after creation."
                          % self.bond_name)

            # Configure bond interface with IP
            cidr = sum(
                [bin(int(b)).count("1") for b in self.netmask.split(".")])
            ip_with_mask = "%s/%s" % (self.local_ip, cidr)
            cmd_ip_set = (
                "nmcli con modify %s ipv4.addresses %s ipv4.method manual"
                % (self.bond_name, ip_with_mask))
            process.system(cmd_ip_set, shell=True, ignore_status=True)
            cmd_bond_up = "nmcli con up %s" % self.bond_name
            if process.system(cmd_bond_up, shell=True,
                              ignore_status=True) != 0:
                self.log.error(
                    "Failed to set IP address %s for bond %s",
                    ip_with_mask, self.bond_name)

            # Check for bond link-up
            cmd = "cat /proc/net/bonding/%s" % self.bond_name
            try:
                output = process.system_output(
                    cmd, shell=True).decode("utf-8")
                if ("Slave Interface" in output
                        and "MII Status: up" in output):
                    self.log.info(
                        "Bond %s is active and link is up.",
                        self.bond_name)
                else:
                    self.log.error(
                        "Bond %s exists but bond link is not up. "
                        "Check link of the slave interfaces.",
                        self.bond_name)
            except Exception as e:
                self.log.error(
                    "Bond creation on host machine has FAILED: %s", e)

            # Set networkinterface object to bond
            self.networkinterface = NetworkInterface(
                self.bond_name, self.localhost)
            self.bond_created = True

        else:
            self.log.info("Configuring Mode0 bond on Peer machine")
            self.log.info("------------------------------------------")
            cidr = sum(
                [bin(int(b)).count("1") for b in self.netmask.split(".")])
            bond_cmd = 'modprobe bonding; '
            bond_cmd += (
                "nmcli con add type bond ifname %s con-name %s "
                "mode %s miimon %s; "
                % (self.bond_name, self.bond_name,
                   self.mode, self.miimon))

            for interface in self.peer_interfaces:
                bond_cmd += "nmcli c down %s; " % interface
                bond_cmd += (
                    "nmcli con add type ethernet ifname %s "
                    "con-name slave-%s master %s; "
                    % (interface, interface, self.bond_name))

            ip_with_mask = "%s/%s" % (self.peer_first_ipinterface[0], cidr)
            bond_cmd += (
                "nmcli con modify %s ipv4.addresses %s "
                "ipv4.method manual; "
                % (self.bond_name, ip_with_mask))
            bond_cmd += "nmcli con up %s" % self.bond_name

            output = self.session.cmd(bond_cmd)
            if not output.exit_status == 0:
                self.fail("Bond setup failed in peer machine")
            else:
                self.peer_bond_created = True

    def test_bond_setup(self):
        '''
        Test to validate the bond setup on host / peer
        '''
        try:
            if self.peer_bond_needed:
                self.nmcli_bond_setup("peer", "")
            self.nmcli_bond_setup("local", self.mode)
            if self.networkinterface.ping_check(
                    self.peer_first_ipinterface[0], count=20) is not None:
                self.fail("Ping test from bond to peer FAILED")
            # Mark test as passed only if all steps succeed
            self.test_passed = True
        except Exception:
            # On any failure, cleanup will be triggered by tearDown
            # since test_passed remains False
            raise

    def get_bond_status(self):
        '''
        Get the status of the bond from /proc fs
        '''
        try:
            output = process.system_output(
                "cat /proc/net/bonding/%s" % self.bond_name,
                shell=True).decode("utf-8")
            if "MII Status: up" in output:
                self.log.info("Bond is UP")
            else:
                self.log.info("Bond is DOWN")
        except Exception as e:
            self.log.error("Failed to get Bond status: %s", e)

    def is_vnic(self):
        '''
        check if slave interface is vnic
        '''
        for interface in self.host_interfaces:
            cmd = "lsdevinfo -q name=%s" % interface
            try:
                output = process.system_output(
                    cmd, shell=True,
                    ignore_status=True).decode("utf-8")
                if 'type="IBM,vnic"' in output:
                    return True
            except Exception as e:
                self.log.debug(
                    "lsdevinfo check failed for %s: %s", interface, e)
        return False

    def ping_check(self):
        '''
        Ping the peer from the bond interface
        '''
        cmd = ("ping -I %s %s -c 5"
               % (self.bond_name, self.peer_first_ipinterface[0]))
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            return False
        return True

    def error_check(self):
        '''
        Report any accumulated non-fatal errors from failover tests
        '''
        if self.err:
            self.fail("Tests failed. Details:\n%s" % "\n".join(self.err))

    def test_bond_failover(self):
        '''
        Test scenarios for slave failover
        '''
        self.log.info("Starting bond failover test for %s", self.bond_name)
        if len(self.host_interfaces) > 1:
            for interface in self.host_interfaces:
                self.log.info(
                    "Bringing down slave interface: %s", interface)
                down_cmd = "ip link set %s down" % interface
                process.system(down_cmd, shell=True, ignore_status=True)
                time.sleep(self.sleep_time)  # Wait for failover to trigger
                self.networkinterface = NetworkInterface(
                    self.bond_name, self.localhost)
                self.get_bond_status()
                if self.ping_check():
                    self.log.info(
                        "Ping passed for mode %s", self.mode)
                else:
                    error_str = (
                        "Ping fail in mode %s when interface %s down"
                        % (self.mode, interface))
                    self.log.debug(error_str)
                    self.err.append(error_str)
                up_cmd = "ip link set %s up" % interface
                process.system(up_cmd, shell=True, ignore_status=True)
                time.sleep(self.sleep_time)
        else:
            self.log.debug(
                "Need a min of 2 host interfaces to test "
                "slave failover in Bonding")

        self.log.info("----------------------------------------")
        self.log.info(
            "Failing all interfaces for mode %s", self.mode)
        self.log.info("----------------------------------------")
        for interface in self.host_interfaces:
            down_cmd = "ip link set %s down" % interface
            process.system(down_cmd, shell=True, ignore_status=True)
            time.sleep(self.sleep_time)
        if not self.ping_check():
            self.log.info(
                "Ping to Bond interface failed when all slave "
                "interfaces are down. This is expected")
        self.get_bond_status()
        for interface in self.host_interfaces:
            up_cmd = "ip link set %s up" % interface
            process.system(up_cmd, shell=True, ignore_status=True)
            time.sleep(self.sleep_time)

        self.bond_mtu_test()
        self.error_check()
        # Mark test as passed - bond interface is kept regardless
        self.test_passed = True

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
            if not self.ping_check():
                self.fail("Ping fail in mode %s after MTU change to %s"
                          % (self.mode, mtu))
            else:
                self.log.info(
                    "Ping success for mode %s bond with MTU %s",
                    self.mode, mtu)
            if self.networkinterface.set_mtu('1500') is not None:
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
            self.log.info("Removing Bond interface %s on local machine",
                          self.bond_name)
            self.log.info("------------------------------------------------")
            for interface in self.host_interfaces:
                del_cmd = "nmcli con del slave-%s" % interface
                if process.system(del_cmd, shell=True,
                                  ignore_status=True) != 0:
                    self.log.error(
                        "Failed to delete slave connection %s", interface)
            del_cmd = "nmcli con delete %s" % self.bond_name
            if process.system(del_cmd, shell=True, ignore_status=True) != 0:
                self.log.error("Failed to delete bond interface %s",
                               self.bond_name)
            else:
                self.log.info("Bond interface %s removed successfully.",
                              self.bond_name)
            linux_modules.unload_module("bonding")
            time.sleep(self.sleep_time)
        else:
            self.log.info("Removing Bonding configuration on Peer machine")
            self.log.info("------------------------------------------------")
            del_cmd = "nmcli con delete %s; " % self.bond_name
            del_cmd += "rmmod bonding; "
            for interface in self.peer_interfaces:
                del_cmd += "nmcli con del slave-%s; " % interface

            output = self.session.cmd(del_cmd)
            if not output.exit_status == 0:
                self.log.info("bond removing command failed in peer machine")

    def test_bond_cleanup(self):
        '''
        Test to cleanup bond and its configuration.
        This test always performs cleanup regardless of pass/fail/error/cancel.
        '''
        try:
            self.nmcli_bond_cleanup("local")
            for ipaddr, host_interface in zip(self.ipaddr,
                                              self.host_interfaces):
                try:
                    networkinterface = NetworkInterface(host_interface,
                                                        self.localhost)
                    networkinterface.add_ipaddr(ipaddr, self.netmask)
                    networkinterface.bring_up()
                except Exception:
                    self.fail("Interface is taking long time to link up")
            if self.peer_bond_needed:
                self.nmcli_bond_cleanup("peer")
                for ipaddr, interface in zip(self.peer_first_ipinterface,
                                             self.peer_interfaces):
                    self.remotehost = RemoteHost(
                        self.peer_public_ip, self.user, password=self.password)
                    peer_networkinterface = NetworkInterface(interface,
                                                             self.remotehost)
                    try:
                        peer_networkinterface.add_ipaddr(ipaddr, self.netmask)
                        peer_networkinterface.bring_up()
                        time.sleep(self.sleep_time)
                        peer_networkinterface.set_mtu("1500")
                    except Exception:
                        self.fail(
                            "Peer interface fail to link up after bond test")
                    time.sleep(self.sleep_time)
                self.remotehost.remote_session.quit()
            # Mark test as passed - cleanup always succeeds if we reach here
            self.test_passed = True
        finally:
            # Ensure cleanup happens even if test fails
            # tearDown will handle any remaining cleanup
            pass

    def _cleanup_local_bond(self):
        '''
        Remove local bond interface and restore host interfaces.
        Called from tearDown to guarantee cleanup on any exit path.
        '''
        # Check if bond interface exists in the system before cleanup
        bond_exists = os.path.exists(
            "/proc/net/bonding/%s" % self.bond_name)
        if not bond_exists and not self.bond_created:
            return

        self.log.info(
            "tearDown: Removing local bond %s and restoring interfaces",
            self.bond_name)
        for interface in self.host_interfaces:
            del_cmd = "nmcli con del slave-%s" % interface
            if process.system(del_cmd, shell=True, ignore_status=True) != 0:
                self.log.warning(
                    "tearDown: Could not delete slave connection for %s",
                    interface)
        del_cmd = "nmcli con delete %s" % self.bond_name
        if process.system(del_cmd, shell=True, ignore_status=True) != 0:
            self.log.warning(
                "tearDown: Could not delete bond connection %s",
                self.bond_name)
        else:
            self.log.info("tearDown: Bond %s deleted.", self.bond_name)
        linux_modules.unload_module("bonding")

        # Restore original IP addresses on host interfaces
        for ipaddr, ifc in zip(self.ipaddr, self.host_interfaces):
            if not ipaddr:
                continue
            try:
                networkinterface = NetworkInterface(ifc, self.localhost)
                networkinterface.add_ipaddr(ipaddr, self.netmask)
                networkinterface.bring_up()
                self.log.info(
                    "tearDown: Restored %s with IP %s", ifc, ipaddr)
            except Exception as e:
                self.log.warning(
                    "tearDown: Could not restore %s with IP %s: %s",
                    ifc, ipaddr, e)

    def _cleanup_peer_bond(self):
        '''
        Remove peer bond interface and restore peer interfaces.
        Called from tearDown to guarantee cleanup on any exit path.
        '''
        if not self.peer_bond_created:
            return

        self.log.info(
            "tearDown: Removing peer bond and restoring peer interfaces")
        del_cmd = "nmcli con delete %s; " % self.bond_name
        del_cmd += "rmmod bonding; "
        for interface in self.peer_interfaces:
            del_cmd += "nmcli con del slave-%s; " % interface
        try:
            output = self.session.cmd(del_cmd)
            if output.exit_status != 0:
                self.log.warning(
                    "tearDown: Peer bond cleanup command returned non-zero")
        except Exception as e:
            self.log.warning(
                "tearDown: Peer bond cleanup failed: %s", e)

        # Restore original IP addresses on peer interfaces
        for ipaddr, interface in zip(self.peer_first_ipinterface,
                                     self.peer_interfaces):
            if not ipaddr:
                continue
            try:
                remotehost = RemoteHost(self.peer_public_ip, self.user,
                                        password=self.password)
                peer_networkinterface = NetworkInterface(interface,
                                                         remotehost)
                peer_networkinterface.add_ipaddr(ipaddr, self.netmask)
                peer_networkinterface.bring_up()
                peer_networkinterface.set_mtu("1500")
                self.log.info(
                    "tearDown: Restored peer %s with IP %s",
                    interface, ipaddr)
            except Exception as e:
                self.log.warning(
                    "tearDown: Could not restore peer %s with IP %s: %s",
                    interface, ipaddr, e)

    def tearDown(self):
        '''
        Conditional cleanup based on test type and outcome:
        - test_bond_setup: cleanup only on FAIL/ERROR/CANCEL
        - test_bond_failover: keep bond interface regardless of outcome
        - test_bond_cleanup: always cleanup regardless of outcome
        '''
        test_name = str(self.name.name) if hasattr(self, 'name') else ''

        # Determine if cleanup should run based on test type and outcome
        should_cleanup = False

        if 'cleanup' in test_name:
            # test_bond_cleanup: always cleanup
            should_cleanup = True
            self.log.info(
                "tearDown: test_bond_cleanup - performing cleanup "
                "regardless of outcome")
        elif 'setup' in test_name:
            # test_bond_setup: cleanup only if test failed
            if not self.test_passed:
                should_cleanup = True
                self.log.info(
                    "tearDown: test_bond_setup failed - cleaning up "
                    "stale bond interface")
            else:
                self.log.info(
                    "tearDown: test_bond_setup passed - keeping bond "
                    "interface for subsequent tests")
        elif 'failover' in test_name:
            # test_bond_failover: keep bond interface regardless of outcome
            should_cleanup = False
            self.log.info(
                "tearDown: test_bond_failover - keeping bond interface "
                "regardless of outcome")
        else:
            # For any other test, perform cleanup if bond was created
            if self.bond_created or self.peer_bond_created:
                should_cleanup = True
                self.log.info(
                    "tearDown: Unknown test type - performing cleanup")

        # Perform cleanup if needed
        if should_cleanup:
            self._cleanup_local_bond()
            if hasattr(self, 'peer_bond_needed') and self.peer_bond_needed:
                self._cleanup_peer_bond()

        # Always cleanup sessions
        if hasattr(self, 'remotehost'):
            try:
                self.remotehost.remote_session.quit()
            except Exception:
                pass
        if hasattr(self, 'session'):
            try:
                self.session.quit()
            except Exception:
                pass
