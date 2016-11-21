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
# bonding test
# Channel bonding enables two or more network interfaces to act as one,
# simultaneously increasing the bandwidth and providing redundancy.


import time
import os
import socket
import fcntl
import struct
from avocado import main
import netifaces
from avocado import Test
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import distro
from avocado.utils import process


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
        sm = SoftwareManager()
        depends = []
        if detected_distro.name == "Ubuntu":
            depends.append("openssh-client")
        if detected_distro.name == "redhat":
            depends.append("openssh-clients")
        if detected_distro.name == "Suse":
            depends.append("openssh")
        for pkg in depends:
            if not sm.check_installed(pkg) and not sm.install(pkg):
                self.skip("%s package is need to test" % pkg)
        interfaces = netifaces.interfaces()
        self.user = self.params.get("username", default="root")
        self.host_if1 = self.params.get("Iface1", default="")
        self.host_if2 = self.params.get("Iface2", default="")
        self.peer_if2 = self.params.get("peerif2", default="")
        if self.host_if1 not in interfaces or self.host_if2 not in interfaces:
            self.skip("interface is not available")
        self.peer_ip1 = self.params.get("peerip", default="")
        if self.peer_ip1 == "" or self.peer_if2 == "":
            self.skip("peer machine should available")
        msg = "ip addr show  | grep %s | grep -oE '[^ ]+$'" % self.peer_ip1
        cmd = "ssh %s@%s %s" % (self.user, self.peer_ip1, msg)
        self.peer_if1 = process.system_output(cmd, shell=True).strip()
        if self.peer_if1 == "":
            self.fail("test failed because peer interface can not retrieved")
        self.bond_name = self.params.get("bondname", default="tempbond")
        self.mode = self.params.get("bonding_mode", default="")
        if self.mode == "":
            self.skip("test skipped because mode not specified")
        if self.host_if1 != "" and self.host_if2 != "" and self.peer_if2 != "":
            cmd = "ip -f inet -o addr show %s | awk '{print $4}' | cut -d /\
                  -f1" % self.host_if1
            self.local_ip1 = process.system_output(cmd, shell=True).strip()
            if self.local_ip1 == "":
                self.fail("test failed because local ip can not retrieved")
            cmd = "ip -f inet -o addr show %s | awk '{print $4}' | cut -d /\
                  -f1" % self.host_if2
            self.local_ip2 = process.system_output(cmd, shell=True).strip()
            if self.local_ip2 == "":
                self.fail("test failed because local ip can not retrieved")
            msg = "ip -f inet -o addr show %s | awk '{print $4}' | cut -d /\
                  -f1" % self.peer_if2
            cmd = "ssh %s@%s \"%s\"" % (self.user, self.peer_ip1, msg)
            self.peer_ip2 = process.system_output(cmd, shell=True).strip()
            cmd = 'echo %s | cut -d " " -f4' % self.peer_ip2
            self.peer_ip2 = process.system_output(cmd, shell=True).strip()
            if self.peer_ip2 == "":
                self.fail("test failed because peer ip can not retrieved")
        st = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.If1_mask = socket.inet_ntoa(fcntl.ioctl(st.fileno(), 0x891b,
                                         struct.pack('256s',
                                         self.host_if1))[20:24]).strip('\n')
        self.If2_mask = socket.inet_ntoa(fcntl.ioctl(st.fileno(), 0x891b,
                                         struct.pack('256s',
                                         self.host_if2))[20:24]).strip('\n')
        self.bonding_slave_file = "/sys/class/net/%s/bonding/slaves"\
                                  % self.bond_name

    def bond_remove(self, arg1):
        '''
        bond_remove
        '''
        if arg1 == "local":
            self.log.info("Bonding configuration removed on laocal")
            self.log.info("------------------------------------------------")
            for ifs in [self.host_if1, self.host_if2]:
                cmd = "ifconfig %s down" % ifs
                if process.system(cmd, shell=True, ignore_status=True) != 0:
                    self.log.info("unable to bring down the interface")
                cmd = "ifconfig %s down" % ifs
                if process.system(cmd, shell=True, ignore_status=True) != 0:
                    self.log.info("unable to bring down the interface")
                cmd = "echo -%s > %s" % (ifs, self.bonding_slave_file)
                if process.system(cmd, shell=True, ignore_status=True) != 0:
                    self.log.info("bond removing failed in local machine")
            cmd = "echo -%s > /sys/class/net/bonding_masters" % self.bond_name
            if process.system(cmd, shell=True, ignore_status=True) != 0:
                self.log.info("bond removing command failed in local machine")
            time.sleep(5)
        else:
            self.log.info("Bonding configuration removed on Peer machine")
            self.log.info("------------------------------------------------")
            cmd = "ifconfig %s down;\
                  ifconfig %s down;\
                  ifconfig %s down;\
                  ip addr flush dev %s;\
                  ip addr flush dev %s;\
                  echo '-%s' > %s;\
                  echo '-%s' > %s;\
                  echo '-%s' > /sys/class/net/bonding_masters;\
                  ifconfig %s up;\
                  ifconfig %s %s netmask %s up;\
                  sleep 5;"\
                  % (self.bond_name, self.peer_if1, self.peer_if2,
                     self.peer_if1, self.peer_if2, self.peer_if1,
                     self.bonding_slave_file, self.peer_if2,
                     self.bonding_slave_file, self.bond_name,
                     self.peer_if2, self.peer_if1, self.peer_ip1,
                     self.If1_mask)
            peer_cmd = "ssh %s@%s \"%s\"" % (self.user, self.peer_ip1, cmd)
            if process.system(peer_cmd, shell=True, ignore_status=True) != 0:
                self.log.info("bond removing command failed in peer machine")

    def ping_check(self, arg1):
        '''
        ping check
        '''
        cmd = "ping -I %s %s -c 5" % (self.bond_name, self.peer_ip1)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("ping failed in Mode %s, check bonding configuration"
                      % arg1)

    def bond_fail(self, arg1):
        '''
        bond fail
        '''
        interfaces = [self.host_if1, self.host_if2]
        for interface in interfaces:
            self.log.info("Failing interface %s for mode %s"
                          % (interface, arg1))
            cmd = "ifconfig %s down" % interface
            if process.system(cmd, shell=True, ignore_status=True) != 0:
                self.fail("bonding not working when trying to down the\
                          interface %s " % interface)
            time.sleep(15)
            self.ping_check(arg1)
            cmd = "cat /proc/net/bonding/%s" % self.bond_name
            process.system_output(cmd, shell=True, verbose=True)
            cmd = "ifconfig %s up" % interface
            if process.system(cmd, shell=True, ignore_status=True) != 0:
                self.fail("bonding not working when trying to up the\
                          interface %s" % interface)
            time.sleep(5)

    def bond_setup(self, arg1, arg2):
        '''
        bond setup
        '''
        if arg1 == "local":
            self.log.info("Configuring Bonding on Local machine")
            self.log.info("--------------------------------------")
            for ifs in [self.host_if1, self.host_if2]:
                cmd = "ip addr flush dev %s" % ifs
                process.system(cmd, shell=True, ignore_status=True)
                cmd = "ifconfig %s down" % ifs
                process.system(cmd, shell=True, ignore_status=True)
            cmd = "modprobe bonding"
            process.system(cmd, shell=True, ignore_status=True)
            cmd = "echo +%s > /sys/class/net/bonding_masters" % self.bond_name
            process.system(cmd, shell=True, ignore_status=True)
            cmd = "echo %s > /sys/class/net/%s/bonding/mode"\
                  % (arg2, self.bond_name)
            process.system(cmd, shell=True, ignore_status=True)
            cmd = "echo 100 > /sys/class/net/%s/bonding/miimon"\
                  % self.bond_name
            process.system(cmd, shell=True, ignore_status=True)
            cmd = "echo '+%s' > %s"\
                  % (self.host_if1, self.bonding_slave_file)
            if process.system(cmd, shell=True, ignore_status=True) != 0:
                self.fail("Mode %s FAIL while bonding setup" % arg2)
            time.sleep(2)
            cmd = "echo '+%s' > %s"\
                  % (self.host_if2, self.bonding_slave_file)
            if process.system(cmd, shell=True, ignore_status=True) != 0:
                self.fail("Mode %s FAIL while bonding setup" % arg2)
            time.sleep(2)
            cmd = "cat /proc/net/bonding/%s | grep 'Bonding Mode' |\
                  cut -d ':' -f 2" % self.bond_name
            bond_name_val = process.system_output(cmd, shell=True).strip('\n')
            self.log.info("Trying bond mode %s [ %s ]"
                          % (arg2, bond_name_val))
            for ifs in [self.host_if1, self.host_if2]:
                cmd = "ifconfig %s up" % ifs
                if process.system(cmd, shell=True, ignore_status=True) != 0:
                    self.fail("unable to interface up")
            cmd = "ifconfig %s %s netmask %s up"\
                  % (self.bond_name, self.local_ip1, self.If1_mask)
            if process.system(cmd, shell=True, ignore_status=True) != 0:
                self.fail("bond setup command failed in local machine")
            time.sleep(5)
        else:
            self.log.info("Configuring Bonding on Peer machine")
            self.log.info("------------------------------------------")
            cmd = "ip addr flush dev %s;\
                  ip addr flush dev %s;\
                  ifconfig %s down;\
                  ifconfig %s down;\
                  modprobe bonding;\
                  echo +%s > /sys/class/net/bonding_masters;\
                  echo 0 > /sys/class/net/%s/bonding/mode;\
                  echo 100 > /sys/class/net/%s/bonding/miimon;\
                  echo '+%s' > %s;\
                  echo '+%s' > %s;\
                  ifconfig %s up;\
                  ifconfig %s up;\
                  ifconfig %s %s netmask %s up;\
                  sleep 5;\
                  " % (self.peer_if1, self.peer_if2, self.peer_if1,
                       self.peer_if2, self.bond_name, self.bond_name,
                       self.bond_name, self.peer_if1, self.bonding_slave_file,
                       self.peer_if2, self.bonding_slave_file, self.peer_if1,
                       self.peer_if2, self.bond_name, self.peer_ip1,
                       self.If1_mask)
            peer_cmd = "ssh %s@%s \"%s\"" % (self.user, self.peer_ip1, cmd)
            if process.system(peer_cmd, shell=True, ignore_status=True) != 0:
                self.fail("bond setup command failed in peer machine")

    def test_bonding(self):
        '''
        test options are mandatory
        ext test options are depends upon user
        '''
        self.log.info("Bonding")
        msg = "[ -d /sys/class/net/%s ]" % self.bond_name
        cmd = "ssh %s@%s %s" % (self.user, self.peer_ip1, msg)
        if process.system(cmd, shell=True, ignore_status=True) == 0:
            self.fail("bond name already exists on peer machine")
        self.bond_dir = os.path.join("/sys/class/net/", self.bond_name)
        if os.path.isdir(self.bond_dir):
            self.fail("bond name already exists on local machine")
        self.log.info("TESTING FOR MODE %s" % self.mode)
        self.log.info("-------------------------------------------------")
        self.bond_setup("peer", "")
        self.bond_setup("local", self.mode)
        cmd = "cat /proc/net/bonding/%s" % self.bond_name
        process.run(cmd, shell=True, verbose=True)
        self.ping_check(self.mode)
        self.bond_fail(self.mode)
        self.log.info("Mode %s OK" % self.mode)

    def tearDown(self):
        '''
        set the initial state
        '''
        self.bond_remove("local")
        cmd = "ifconfig %s %s netmask %s up"\
              % (self.host_if1, self.local_ip1, self.If1_mask)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.log.info("unable to bring up to original state in host")
        time.sleep(5)
        cmd = "ifconfig %s %s netmask %s up"\
              % (self.host_if2, self.local_ip2, self.If2_mask)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.log.info("unable to bring up to original state in host")
        time.sleep(5)
        self.bond_remove("peer")
        msg = "ifconfig %s %s netmask %s up"\
              % (self.peer_if1, self.peer_ip1, self.If1_mask)
        cmd = "ssh %s@%s \"%s\"" % (self.user, self.peer_ip1, msg)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.log.info("unable to bring up to original state in host")
        time.sleep(5)
        msg = "ifconfig %s %s netmask %s up"\
              % (self.peer_if2, self.peer_ip2, self.If2_mask)
        cmd = "ssh %s@%s \"%s\"" % (self.user, self.peer_ip1, msg)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.log.info("unable to bring up to original state in host")
        time.sleep(2)


if __name__ == "__main__":
    main()
