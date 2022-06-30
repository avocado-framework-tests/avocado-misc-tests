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
# Copyright: 2016 IBM
# Author: Prudhvi Miryala<mprudhvi@linux.vnet.ibm.com>
# Author Narasimhan V <sim@linux.vnet.ibm.com>

"""
Bonding test
Channel bonding enables two or more network interfaces to act as one,
simultaneously increasing the bandwidth and providing redundancy.
"""


import time
import os
import socket
import fcntl
import struct
import netifaces
from avocado import Test
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils import distro
from avocado.utils import process
from avocado.utils import linux_modules
from avocado.utils import genio
from avocado.utils.ssh import Session
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.network.hosts import LocalHost, RemoteHost


class Bonding(Test):
    '''
    Channel bonding enables two or more network interfaces to act as one,
    simultaneously increasing the bandwidth and providing redundancy.
    '''

    def setUp(self):
        '''
        To check and install dependencies for the test
        '''
        detected_distro = distro.detect()
        smm = SoftwareManager()
        depends = []
        # FIXME: "redhat" as the distro name for RHEL is deprecated
        # on Avocado versions >= 50.0.  This is a temporary compatibility
        # enabler for older runners, but should be removed soon
        if detected_distro.name == "Ubuntu":
            depends.extend(["openssh-client", "iputils-ping"])
        elif detected_distro.name in ["rhel", "fedora", "centos", "redhat"]:
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
        self.peer_first_ipinterface = self.params.get("peer_ips", default="").split(" ")
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
                try:
                    networkinterface.flush_ipaddr()
                    networkinterface.add_ipaddr(ipaddr, self.netmask)
                    networkinterface.save(ipaddr, self.netmask)
                except Exception:
                    networkinterface.save(ipaddr, self.netmask)
                networkinterface.bring_up()
            for ipaddr, interface in zip(self.peer_first_ipinterface,
                                         self.peer_interfaces):
                if self.peer_bond_needed:
                    self.remotehost = RemoteHost(
                                    self.peer_public_ip,
                                    self.user, password=self.password)
                    peer_networkinterface = NetworkInterface(interface,
                                                             self.remotehost)
                    try:
                        peer_networkinterface.flush_ipaddr()
                        peer_networkinterface.add_ipaddr(ipaddr, self.netmask)
                        peer_networkinterface.save(ipaddr, self.netmask)
                    except Exception:
                        peer_networkinterface.save(ipaddr, self.netmask)
                    networkinterface.bring_up()
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
        self.sleep_time = int(self.params.get("sleep_time", default=5))
        self.mtu = self.params.get("mtu", default=1500)
        for root, dirct, files in os.walk("/root/.ssh"):
            for file in files:
                if file.startswith("avocado-master-"):
                    path = os.path.join(root, file)
                    os.remove(path)
        self.ib = False
        if self.host_interface[0:2] == 'ib':
            self.ib = True
        self.log.info("Bond Test on IB Interface? = %s", self.ib)

        '''
        An individual interface, that has a LACP PF, cannot communicate without
        being bonded. So the test uses the public ip address to create an SSH
        session instead of the private one when setting up a bonding interface.
        '''
        if self.mode == "4" and "setup" in str(self.name.name):
            self.session = Session(self.peer_public_ip, user=self.user,
                                   password=self.password)
        else:
            self.session = Session(self.peer_first_ipinterface, user=self.user,
                                   password=self.password)

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
        self.setup_ip()
        self.err = []
        if self.mode == "4" and "setup" in str(self.name.name):
            self.remotehost = RemoteHost(self.peer_public_ip, self.user,
                                         password=self.password)
        else:
            self.remotehost = RemoteHost(self.peer_first_ipinterface, self.user,
                                         password=self.password)

        if 'setup' in str(self.name.name):
            for interface in self.peer_interfaces:
                peer_networkinterface = NetworkInterface(interface, self.remotehost)
                if peer_networkinterface.set_mtu(self.mtu) is not None:
                    self.cancel("Failed to set mtu in peer")
            for host_interface in self.host_interfaces:
                self.networkinterface = NetworkInterface(host_interface, self.localhost)
                if self.networkinterface.set_mtu(self.mtu) is not None:
                    self.cancel("Failed to set mtu in host")

    def bond_ib_conf(self, bond_name, arg1, arg2):
        '''
        configure slaves for IB cards
        '''
        cmd = 'ip link set %s up;' % (bond_name)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("unable to bring Bond interface %s up" % bond_name)
        if arg2 == "ATTACH":
            cmd = 'ifenslave %s %s -f;' % (bond_name, arg1)
        else:
            cmd = 'ifenslave %s -d %s ;' % (bond_name, arg1)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("unable to %s IB interface " % arg2)

    def setup_ip(self):
        '''
        set up the IP config
        '''
        if 'setup' in str(self.name):
            interface = self.host_interfaces[0]
        else:
            interface = self.bond_name
        cmd = "ip addr show  | grep %s" % self.peer_first_ipinterface
        output = self.session.cmd(cmd)
        result = ""
        result = result.join(output.stdout.decode("utf-8"))
        self.peer_first_interface = result.split()[-1]
        if self.peer_first_interface == "":
            self.fail("test failed because peer interface can not retrieved")
        self.peer_ips = [self.peer_first_ipinterface]
        self.local_ip = netifaces.ifaddresses(interface)[2][0]['addr']
        self.net_mask = []
        stf = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        for val1, val2 in zip([interface], [self.local_ip]):
            mask = ""
            if val2:
                tmp = fcntl.ioctl(stf.fileno(), 0x891b,
                                  struct.pack('256s', val1.encode()))
                mask = socket.inet_ntoa(tmp[20:24]).strip('\n')
            self.net_mask.append(mask)
        cmd = "route -n | grep %s | grep -w UG | awk "\
              "'{ print $2 }'" % interface
        self.gateway = process.system_output(
            '%s' % cmd, shell=True)

    def bond_remove(self, arg1):
        '''
        bond_remove
        '''
        if arg1 == "local":
            self.log.info("Removing Bonding configuration on local machine")
            self.log.info("------------------------------------------------")
            for ifs in self.host_interfaces:
                cmd = "ip link set %s down" % ifs
                if process.system(cmd, shell=True, ignore_status=True) != 0:
                    self.log.info("unable to bring down the interface")
                if self.ib:
                    self.bond_ib_conf(self.bond_name, ifs, "REMOVE")
                else:
                    genio.write_file(self.bonding_slave_file, "-%s" % ifs)
            genio.write_file(self.bonding_masters_file, "-%s" % self.bond_name)
            self.log.info("Removing bonding module")
            linux_modules.unload_module("bonding")
            time.sleep(self.sleep_time)
        else:
            self.log.info("Removing Bonding configuration on Peer machine")
            self.log.info("------------------------------------------------")
            cmd = ''
            cmd += 'ip link set %s down;' % self.bond_name
            for val in self.peer_interfaces:
                cmd += 'ip link set %s down;' % val
            for val in self.peer_interfaces:
                cmd += 'ip addr flush dev %s;' % val
            for val in self.peer_interfaces:
                if self.ib:
                    self.bond_ib_conf(self.bond_name, val, "REMOVE")
                else:
                    cmd += 'echo "-%s" > %s;' % (val, self.bonding_slave_file)
            cmd += 'echo "-%s" > %s;' % (self.bond_name,
                                         self.bonding_masters_file)
            cmd += 'rmmod bonding;'
            cmd += 'ip addr add %s/%s dev %s;ip link set %s up;sleep 5;'\
                   % (self.peer_first_ipinterface, self.net_mask[0],
                      self.peer_interfaces[0], self.peer_interfaces[0])
            output = self.session.cmd(cmd)
            if not output.exit_status == 0:
                self.log.info("bond removing command failed in peer machine")

    def ping_check(self):
        '''
        ping check
        '''
        # need some time for specific interface before ping
        time.sleep(10)
        cmd = "ping -I %s %s -c 5"\
              % (self.bond_name, self.peer_first_ipinterface)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            return False
        return True

    def is_vnic(self):
        '''
        check if slave interface is vnic
        '''
        for interface in self.host_interfaces:
            cmd = "lsdevinfo -q name=%s" % interface
            if 'type="IBM,vnic"' in process.system_output(cmd, shell=True).decode("utf-8"):
                return True
        return False

    def bond_fail(self, arg1):
        '''
        bond fail
        '''
        if len(self.host_interfaces) > 1:
            for interface in self.host_interfaces:
                self.log.info("Failing interface %s for mode %s",
                              interface, arg1)
                cmd = "ip link set %s down" % interface
                if process.system(cmd, shell=True, ignore_status=True) != 0:
                    self.fail("bonding not working when trying to down the\
                               interface %s " % interface)
                time.sleep(self.sleep_time)
                if self.ping_check():
                    self.log.info("Ping passed for Mode %s", arg1)
                else:
                    error_str = "Ping fail in Mode %s when interface %s down"\
                        % (arg1, interface)
                    self.log.debug(error_str)
                    self.err.append(error_str)
                self.log.info(genio.read_file(self.bond_status))
                cmd = "ip link set %s up" % interface
                time.sleep(self.sleep_time)
                if process.system(cmd, shell=True, ignore_status=True) != 0:
                    self.fail("Not able to bring up the slave\
                                    interface %s" % interface)
                time.sleep(self.sleep_time)
        else:
            self.log.debug("Need a min of 2 host interfaces to test\
                         slave failover in Bonding")

        self.log.info("\n----------------------------------------")
        self.log.info("Failing all interfaces for mode %s", arg1)
        self.log.info("----------------------------------------")
        for interface in self.host_interfaces:
            cmd = "ip link set %s down" % interface
            if process.system(cmd, shell=True, ignore_status=True) != 0:
                self.fail("Could not bring down the interface %s " % interface)
            time.sleep(self.sleep_time)
        if not self.ping_check():
            self.log.info("Ping to Bond interface failed. This is expected")
        self.log.info(genio.read_file(self.bond_status))
        for interface in self.host_interfaces:
            cmd = "ip link set %s up" % interface
            time.sleep(self.sleep_time)
            if process.system(cmd, shell=True, ignore_status=True) != 0:
                self.fail("Not able to bring up the slave\
                                interface %s" % interface)
            time.sleep(self.sleep_time)
        bond_mtu = ['2000', '3000', '4000', '5000', '6000', '7000',
                    '8000', '9000']
        if self.is_vnic():
            bond_mtu = ['9000']
        for mtu in bond_mtu:
            self.bond_networkinterface = NetworkInterface(self.bond_name,
                                                          self.localhost)
            if self.bond_networkinterface.set_mtu(mtu) is not None:
                self.cancel("Failed to set mtu in host")
            for interface in self.peer_interfaces:
                peer_networkinterface = NetworkInterface(interface,
                                                         self.remotehost)
                if peer_networkinterface.set_mtu(mtu) is not None:
                    self.cancel("Failed to set mtu in peer")
            if not self.ping_check():
                self.fail("Ping fail in mode %s after MTU change to %s" % (self.mode, mtu))
            else:
                self.log.info("Ping success for mode %s bond with  MTU %s" % (self.mode, mtu))
            if self.bond_networkinterface.set_mtu('1500'):
                self.cancel("Failed to set mtu back to 1500 in host")
            for interface in self.peer_interfaces:
                peer_networkinterface = NetworkInterface(interface,
                                                         self.remotehost)
                if peer_networkinterface.set_mtu('1500') is not None:
                    self.cancel("Failed to set mtu back to 1500 in peer")

    def bond_setup(self, arg1, arg2):
        '''
        bond setup
        '''
        if arg1 == "local":
            self.log.info("Configuring Bonding on Local machine")
            self.log.info("--------------------------------------")
            for ifs in self.host_interfaces:
                cmd = "ip addr flush dev %s" % ifs
                process.system(cmd, shell=True, ignore_status=True)
            for ifs in self.host_interfaces:
                cmd = "ip link set %s down" % ifs
                process.system(cmd, shell=True, ignore_status=True)
            linux_modules.load_module("bonding")
            genio.write_file(self.bonding_masters_file, "+%s" % self.bond_name)
            genio.write_file("%s/bonding/mode" % self.bond_dir, arg2)
            genio.write_file("%s/bonding/miimon" % self.bond_dir,
                             self.miimon)
            genio.write_file("%s/bonding/fail_over_mac" % self.bond_dir,
                             self.fail_over_mac)
            genio.write_file("%s/bonding/downdelay" % self.bond_dir,
                             self.downdelay)
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
                        genio.write_file("%s/bonding/%s"
                                         % (self.bond_dir, param), param_value)
            for val in self.host_interfaces:
                if self.ib:
                    self.bond_ib_conf(self.bond_name, val, "ATTACH")
                else:
                    genio.write_file(self.bonding_slave_file, "+%s" % val)
                time.sleep(2)
            bond_name_val = ''
            for line in genio.read_file(self.bond_status).splitlines():
                if 'Bonding Mode' in line:
                    bond_name_val = line.split(':')[1]
            self.log.info("Trying bond mode %s [ %s ]", arg2, bond_name_val)
            for ifs in self.host_interfaces:
                cmd = "ip link set %s up" % ifs
                if process.system(cmd, shell=True, ignore_status=True) != 0:
                    self.fail("unable to interface up")
            cmd = "ip addr add %s/%s dev %s;ip link set %s up"\
                  % (self.local_ip, self.net_mask[0],
                     self.bond_name, self.bond_name)
            process.system(cmd, shell=True, ignore_status=True)
            for _ in range(0, 600, 60):
                if 'state UP' in process.system_output("ip link \
                     show %s" % self.bond_name, shell=True).decode("utf-8"):
                    self.log.info("Bonding setup is successful on\
                                  local machine")
                    break
                time.sleep(60)
            else:
                self.fail("Bonding setup on local machine has failed")
            if self.gateway:
                cmd = 'ip route add default via %s dev %s' % \
                    (self.gateway, self.bond_name)
                process.system(cmd, shell=True, ignore_status=True)

        else:
            self.log.info("Configuring Bonding on Peer machine")
            self.log.info("------------------------------------------")
            cmd = ''
            for val in self.peer_interfaces:
                cmd += 'ip addr flush dev %s;' % val
            for val in self.peer_interfaces:
                cmd += 'ip link set %s down;' % val
            cmd += 'modprobe bonding;'
            cmd += 'echo +%s > %s;'\
                   % (self.bond_name, self.bonding_masters_file)
            cmd += 'echo 0 > %s/bonding/mode;'\
                   % self.bond_dir
            cmd += 'echo 100 > %s/bonding/miimon;'\
                   % self.bond_dir
            cmd += 'echo 2 > %s/bonding/fail_over_mac;'\
                   % self.bond_dir
            for val in self.peer_interfaces:
                if self.ib:
                    self.bond_ib_conf(self.bond_name, val, "ATTACH")
                else:
                    cmd += 'echo "+%s" > %s;' % (val, self.bonding_slave_file)
            for val in self.peer_interfaces:
                cmd += 'ip link set %s up;' % val
            cmd += 'ip addr add %s/%s dev %s;ip link set %s up;sleep 5;'\
                   % (self.peer_first_ipinterface, self.net_mask[0],
                      self.bond_name, self.bond_name)
            output = self.session.cmd(cmd)
            if not output.exit_status == 0:
                self.fail("bond setup command failed in peer machine")

    def test_setup(self):
        '''
        bonding the interfaces
        work for multiple interfaces on both host and peer
        '''
        cmd = "[ -d %s ]" % self.bond_dir
        output = self.session.cmd(cmd)
        if output.exit_status == 0:
            self.fail("bond name already exists on peer machine")
        if os.path.isdir(self.bond_dir):
            self.fail("bond name already exists on local machine")
        if self.peer_bond_needed:
            self.bond_setup("peer", "")
        self.bond_setup("local", self.mode)
        self.log.info(genio.read_file(self.bond_status))
        self.ping_check()
        self.error_check()

    def test_run(self):
        self.bond_fail(self.mode)
        self.log.info("Mode %s OK", self.mode)
        self.error_check()
        # need few sec for interface to not lost the connection to peer
        time.sleep(5)

    def test_cleanup(self):
        '''
        clean up the interface config
        '''
        self.bond_remove("local")

        if self.gateway:
            cmd = 'ip route add default via %s' % \
                (self.gateway)
            process.system(cmd, shell=True, ignore_status=True)

        for ipaddr, host_interface in zip(self.ipaddr, self.host_interfaces):
            networkinterface = NetworkInterface(host_interface, self.localhost)
            try:
                networkinterface.flush_ipaddr()
                networkinterface.add_ipaddr(ipaddr, self.netmask)
                networkinterface.bring_up()
            except Exception:
                self.fail("Interface is taking long time to link up")
            if networkinterface.set_mtu("1500") is not None:
                self.cancel("Failed to set mtu in host")
            try:
                networkinterface.restore_from_backup()
            except Exception:
                self.log.info("backup file not availbale, could not restore file.")

        detected_distro = distro.detect()
        if detected_distro.name == "rhel":
            cmd = "systemctl restart NetworkManager.service"
        elif detected_distro.name == "Ubuntu":
            cmd = "systemctl restart networking"
        else:
            cmd = "systemctl restart network"
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("Failed to restart the network service on host")

        try:
            for interface in self.peer_interfaces:
                peer_networkinterface = NetworkInterface(interface, self.remotehost)
                peer_networkinterface.set_mtu("1500")
            self.remotehost.remote_session.quit()
        except Exception:
            self.log.debug("Could not revert peer interface MTU to 1500")

    def error_check(self):
        if self.err:
            self.fail("Tests failed. Details:\n%s" % "\n".join(self.err))

    def tearDown(self):
        self.session.quit()
