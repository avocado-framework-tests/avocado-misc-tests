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
from avocado import main
from avocado import Test
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import distro
from avocado.utils import process
from avocado.utils import linux_modules
from avocado.utils import genio


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
        interfaces = netifaces.interfaces()
        self.user = self.params.get("user_name", default="root")
        self.host_interfaces = self.params.get("host_interfaces",
                                               default="").split(",")
        if not self.host_interfaces:
            self.cancel("user should specify host interfaces")
        self.peer_interfaces = self.params.get("peer_interfaces",
                                               default="").split(",")
        for self.host_interface in self.host_interfaces:
            if self.host_interface not in interfaces:
                self.cancel("interface is not available")
        self.peer_first_ipinterface = self.params.get("peer_ip", default="")
        if not self.peer_interfaces or self.peer_first_ipinterface == "":
            self.cancel("peer machine should available")
        msg = "ip addr show  | grep %s | grep -oE '[^ ]+$'"\
              % self.peer_first_ipinterface
        cmd = "ssh %s@%s %s" % (self.user, self.peer_first_ipinterface, msg)
        self.peer_first_interface = process.system_output(cmd,
                                                          shell=True).strip()
        if self.peer_first_interface == "":
            self.fail("test failed because peer interface can not retrieved")
        self.mode = self.params.get("bonding_mode", default="")
        if self.mode == "":
            self.cancel("test skipped because mode not specified")
        self.host_ips = []
        self.peer_ips = [self.peer_first_ipinterface]
        for val in self.host_interfaces:
            cmd = "ip -f inet -o addr show %s | awk '{print $4}' | cut -d /\
                  -f1" % val
            local_ip = process.system_output(cmd, shell=True).strip()
            if local_ip == "" and val == self.host_interfaces[0]:
                self.fail("test failed because local ip can not retrieved")
            self.host_ips.append(local_ip)
        for val in self.peer_interfaces:
            msg = "ip -f inet -o addr show %s | awk '{print $4}' | cut -d /\
                  -f1" % val
            cmd = "ssh %s@%s \"%s\""\
                  % (self.user, self.peer_first_ipinterface, msg)
            peer_ip = process.system_output(cmd, shell=True).strip()
            cmd = 'echo %s | cut -d " " -f4' % peer_ip
            peer_ip = process.system_output(cmd, shell=True).strip()
            if peer_ip == "" and val == self.peer_first_interface:
                self.fail("test failed because peer ip can not retrieved")
            self.peer_ips.append(peer_ip)
        self.peer_interfaces.insert(0, self.peer_first_interface)
        self.net_mask = []
        stf = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        for val1, val2 in map(None, self.host_interfaces, self.host_ips):
            mask = ""
            if val2:
                tmp = fcntl.ioctl(stf.fileno(), 0x891b, struct.pack('256s',
                                                                    val1))
                mask = socket.inet_ntoa(tmp[20:24]).strip('\n')
            self.net_mask.append(mask)
        self.bond_name = self.params.get("bond_name", default="tempbond")
        self.net_path = "/sys/class/net/"
        self.bond_status = "/proc/net/bonding/%s" % self.bond_name
        self.bond_dir = os.path.join(self.net_path, self.bond_name)
        self.bonding_slave_file = "%s/bonding/slaves" % self.bond_dir
        self.bonding_masters_file = "%s/bonding_masters" % self.net_path
        self.peer_bond_needed = self.params.get("peer_bond_needed",
                                                default=False)
        self.peer_wait_time = self.params.get("peer_wait_time", default=5)
        self.sleep_time = int(self.params.get("sleep_time", default=5))
        cmd = "route -n | grep %s | grep -w UG | awk "\
              "'{ print $2 }'" % self.host_interfaces[0]
        self.gateway = process.system_output(
            '%s' % cmd, shell=True)
        self.err = []

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
                cmd += 'echo "-%s" > %s;' % (val, self.bonding_slave_file)
            cmd += 'echo "-%s" > %s;' % (self.bond_name,
                                         self.bonding_masters_file)
            cmd += 'rmmod bonding;'
            cmd += 'ip addr add %s/%s dev %s;ip link set %s up;sleep 5;'\
                   % (self.peer_first_ipinterface, self.net_mask[0],
                      self.peer_first_interface, self.peer_first_interface)
            peer_cmd = "ssh %s@%s \"%s\""\
                       % (self.user, self.peer_first_ipinterface, cmd)
            if process.system(peer_cmd, shell=True, ignore_status=True) != 0:
                self.log.info("bond removing command failed in peer machine")

    def ping_check(self):
        '''
        ping check
        '''
        cmd = "ping -I %s %s -c 5"\
              % (self.bond_name, self.peer_first_ipinterface)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            return False
        return True

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
            genio.write_file("%s/bonding/miimon" % self.bond_dir, "100")
            genio.write_file("%s/bonding/fail_over_mac" % self.bond_dir, "2")
            for val in self.host_interfaces:
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
                  % (self.host_ips[0], self.net_mask[0],
                     self.bond_name, self.bond_name)
            process.system(cmd, shell=True, ignore_status=True)
            for _ in range(0, 600, 60):
                if 'state UP' in process.system_output("ip link \
                     show %s" % self.bond_name, shell=True):
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
                cmd += 'echo "+%s" > %s;' % (val, self.bonding_slave_file)
            for val in self.peer_interfaces:
                cmd += 'ip link set %s up;' % val
            cmd += 'ip addr add %s/%s dev %s;ip link set %s up;sleep 5;'\
                   % (self.peer_first_ipinterface, self.net_mask[0],
                      self.bond_name, self.bond_name)
            peer_cmd = "timeout %s ssh %s@%s \"%s\""\
                       % (self.peer_wait_time, self.user,
                          self.peer_first_ipinterface, cmd)
            if process.system(peer_cmd, shell=True, ignore_status=True) != 0:
                self.fail("bond setup command failed in peer machine")

    def test_bonding(self):
        '''
        bonding the interfaces
        work for multiple interfaces on both host and peer
        '''
        self.log.info("Bonding")
        msg = "[ -d %s ]" % self.bond_dir
        cmd = "ssh %s@%s %s" % (self.user, self.peer_first_ipinterface, msg)
        if process.system(cmd, shell=True, ignore_status=True) == 0:
            self.fail("bond name already exists on peer machine")
        if os.path.isdir(self.bond_dir):
            self.fail("bond name already exists on local machine")
        self.log.info("TESTING FOR MODE %s", self.mode)
        self.log.info("-------------------------------------------------")
        if self.peer_bond_needed:
            self.bond_setup("peer", "")
        self.bond_setup("local", self.mode)
        self.log.info(genio.read_file(self.bond_status))
        self.ping_check()
        self.bond_fail(self.mode)
        self.log.info("Mode %s OK", self.mode)
        if self.err:
            self.fail("Tests failed. Details:\n%s" % "\n".join(self.err))

    def tearDown(self):
        '''
        set the initial state
        '''
        self.bond_remove("local")
        for val1, val2, val3 in map(None, self.host_interfaces,
                                    self.host_ips, self.net_mask):
            cmd = "ip addr flush dev %s" % val1
            process.system(cmd, shell=True, ignore_status=True)
            cmd = "ip link set %s up" % val1
            process.system(cmd, shell=True, ignore_status=True)
            if val2:
                cmd = "ip addr add %s/%s dev %s" % (val2, val3, val1)
                process.system(cmd, shell=True, ignore_status=True)
            for _ in range(0, 600, 60):
                if 'state UP' in process.system_output("ip link \
                     show %s" % val1, shell=True):
                    self.log.info("Interface %s is up", val1)
                    break
                time.sleep(60)
            else:
                self.log.info("Interface %s in not up\
                                   in the host machine", val1)
        if self.gateway:
            cmd = 'ip route add default via %s' % \
                (self.gateway)
            process.system(cmd, shell=True, ignore_status=True)

        if self.peer_bond_needed:
            self.bond_remove("peer")
            for val1, val2, val3 in map(None, self.peer_interfaces,
                                        self.peer_ips, self.net_mask):
                msg = "ip addr add %s/%s dev %s;ip link set %s up;sleep %s"\
                      % (val2, val3, val1, val1, self.peer_wait_time)
                cmd = "ssh %s@%s \"%s\""\
                      % (self.user, self.peer_first_ipinterface, msg)
                if process.system(cmd, shell=True, ignore_status=True) != 0:
                    self.log.info("unable to bring to original state in host")
                time.sleep(self.sleep_time)


if __name__ == "__main__":
    main()
