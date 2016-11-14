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
from avocado import main
import netifaces
from avocado import Test
from avocado.utils.software_manager import SoftwareManager
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
        sm = SoftwareManager()
        depends = ["openssh-clients", "iputils"]
        for pkg in depends:
            if not sm.check_installed(pkg) and not sm.install(pkg):
                self.skip("%s package is need to test" % pkg)
        interfaces = netifaces.interfaces()
        self.host_if1 = self.params.get("Iface1", default="")
        self.host_if2 = self.params.get("Iface2", default="")
        self.peer_if2 = self.params.get("peerif2", default="")
        if self.host_if1 not in interfaces or self.host_if2 not in interfaces:
            self.skip("interface is not available")
        self.peer_ip = self.params.get("peerip", default="")
        if self.peer_ip == "" or self.peer_if2 == "":
            self.skip("peer machine should available")
        msg = "ip addr show  | grep %s | grep -oE '[^ ]+$'" % self.peer_ip
        cmd = "ssh %s %s" % (self.peer_ip, msg)
        self.peer_if1 = process.system_output(cmd, shell=True).strip()
        if self.peer_if1 == "":
            self.fail("test failed because peer interface can not retrieved")
        self.bond_name = self.params.get("bondname", default="tempbond")
        self.mode = self.params.get("bonding_mode", default="").split(" ")
        if self.mode == "":
            self.skip("test skipped because mode not specified")
        if self.host_if1 != "" and self.host_if2 != "" and self.peer_if2 != "":
            cmd = "ip -f inet -o addr show %s | awk '{print $4}' | cut -d /\
                  -f1" % self.host_if1
            self.local_ip = process.system_output(cmd, shell=True).strip()
            if self.local_ip == "":
                self.fail("test failed because local ip can not retrieved")
            cmd = "ip -f inet -o addr show %s | awk '{print $4}' | cut -d /\
                  -f1" % self.host_if2
            self.local_ip2 = process.system_output(cmd, shell=True).strip()
            if self.local_ip2 == "":
                self.fail("test failed because local ip can not retrieved")

    def bond_remove(self, arg1):
        '''
        bond_remove
        '''
        if arg1 == "local":
            cmd = "ifconfig %s down" % self.host_if1
            if process.system(cmd, shell=True, ignore_status=True) != 0:
                self.log.info("unable to bring down the interface")
            cmd = "ifconfig %s down" % self.host_if2
            if process.system(cmd, shell=True, ignore_status=True) != 0:
                self.log.info("unable to bring down the interface")
            cmd = "echo -%s > /sys/class/net/%s/bonding/slaves"\
                  % (self.host_if1, self.bond_name)
            process.system(cmd, shell=True, ignore_status=True)
            cmd = "echo -%s > /sys/class/net/%s/bonding/slaves"\
                  % (self.host_if2, self.bond_name)
            process.system(cmd, shell=True, ignore_status=True)
            cmd = "echo -%s > /sys/class/net/bonding_masters" % self.bond_name
            process.system(cmd, shell=True, ignore_status=True)
            time.sleep(5)
        else:
            cmd = "echo 'Bonding configuration removed on Peer machine';\
                  ifconfig %s down;\
                  ifconfig %s down;\
                  ifconfig %s down;\
                  ip addr flush dev %s;\
                  ip addr flush dev %s;\
                  echo '-%s' > /sys/class/net/%s/bonding/slaves;\
                  echo '-%s' > /sys/class/net/%s/bonding/slaves;\
                  echo '-%s' > /sys/class/net/bonding_masters;\
                  ifconfig %s up;\
                  ifconfig %s %s netmask 255.255.255.0 up;\
                  sleep 5;"\
                  % (self.bond_name, self.peer_if1, self.peer_if2,
                     self.peer_if1, self.peer_if2, self.peer_if1,
                     self.bond_name, self.peer_if2, self.bond_name,
                     self.bond_name, self.peer_if2, self.peer_if1,
                     self.peer_ip)
            peer_cmd = "ssh %s \"%s\"" % (self.peer_ip, cmd)
            if process.system(peer_cmd, shell=True, ignore_status=True) != 0:
                self.log.info("bond removing command failed in peer machine")

    def ping_check(self, arg1):
        '''
        ping check
        '''
        cmd = "ping -I %s %s -c 5" % (self.bond_name, self.peer_ip)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            time.sleep(5)
            self.log.info("Mode %s == FAIL" % arg1)
            self.bond_remove("local")
            cmd = "ifconfig %s %s netmask 255.255.255.0 up" %\
                  (self.host_if1, self.local_ip)
            if process.system(cmd, shell=True, ignore_status=True) != 0:
                self.fail("unable to bring up to original state")
            time.sleep(5)
            cmd = "ifconfig %s %s netmask 255.255.255.0 up" %\
                  (self.host_if2, self.local_ip2)
            if process.system(cmd, shell=True, ignore_status=True) != 0:
                self.fail("unable to bring up to original state")
            time.sleep(5)
            self.bond_remove("peer")
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
            time.sleep(5)
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
            cmd = "ip addr flush dev %s" % self.host_if1
            process.system(cmd, shell=True, ignore_status=True)
            cmd = "ip addr flush dev %s" % self.host_if2
            process.system(cmd, shell=True, ignore_status=True)
            cmd = "ifconfig %s down" % self.host_if1
            process.system(cmd, shell=True, ignore_status=True)
            cmd = "ifconfig %s down" % self.host_if2
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
            cmd = "echo '+%s' > /sys/class/net/%s/bonding/slaves"\
                  % (self.host_if1, self.bond_name)
            if process.system(cmd, shell=True, ignore_status=True) != 0:
                self.bond_remove("local")
                cmd = "ifconfig %s %s netmask 255.255.255.0 up"\
                      % (self.host_if1, self.local_ip)
                if process.system(cmd, shell=True, ignore_status=True) != 0:
                    self.fail("unable to bring up to original state")
                time.sleep(5)
                cmd = "ifconfig %s %s netmask 255.255.255.0 up"\
                      % (self.host_if2, self.local_ip2)
                if process.system(cmd, shell=True, ignore_status=True) != 0:
                    self.fail("unable to bring up to original state")
                time.sleep(5)
                self.bond_remove("peer")
                time.sleep(2)
                self.fail("Mode %s FAIL while bonding setup" % arg2)
            time.sleep(2)
            cmd = "echo '+%s' > /sys/class/net/%s/bonding/slaves"\
                  % (self.host_if2, self.bond_name)
            if process.system(cmd, shell=True, ignore_status=True) != 0:
                self.bond_remove("local")
                cmd = "ifconfig %s %s netmask 255.255.255.0 up"\
                      % (self.host_if1, self.local_ip)
                if process.system(cmd, shell=True, ignore_status=True) != 0:
                    self.fail("unable to bring up to original state")
                time.sleep(5)
                cmd = "ifconfig %s %s netmask 255.255.255.0 up"\
                      % (self.host_if2, self.local_ip2)
                if process.system(cmd, shell=True, ignore_status=True) != 0:
                    self.log.info("unable to bring up to original state")
                time.sleep(5)
                self.bond_remove("peer")
                time.sleep(2)
                self.fail("Mode %s FAIL while bonding setup" % arg2)
            time.sleep(2)
            cmd = "cat /proc/net/bonding/%s | grep 'Bonding Mode' |\
                  cut -d ':' -f 2" % self.bond_name
            bond_name_val = process.system_output(cmd, shell=True).strip('\n')
            self.log.info("Trying bond mode %s [ %s ]"
                          % (arg2, bond_name_val))
            cmd = "ifconfig %s up" % self.host_if1
            if process.system(cmd, shell=True, ignore_status=True) != 0:
                self.log.info("unable to interface up")
            cmd = "ifconfig %s up" % self.host_if2
            if process.system(cmd, shell=True, ignore_status=True) != 0:
                self.log.info("unable to interface up")
            cmd = "ifconfig %s %s netmask 255.255.255.0 up"\
                  % (self.bond_name, self.local_ip)
            if process.system(cmd, shell=True, ignore_status=True) != 0:
                self.log.info("unable to bring up the bonding interface")
            time.sleep(5)
        else:
            self.log.info("Configuring Bonding on Peer machine")
            cmd = "ip addr flush dev %s;\
                  ip addr flush dev %s;\
                  ifconfig %s down;\
                  ifconfig %s down;\
                  modprobe bonding;\
                  echo +%s > /sys/class/net/bonding_masters;\
                  echo 0 > /sys/class/net/%s/bonding/mode;\
                  echo 100 > /sys/class/net/%s/bonding/miimon;\
                  echo '+%s' > /sys/class/net/%s/bonding/slaves;\
                  echo '+%s' > /sys/class/net/%s/bonding/slaves;\
                  ifconfig %s up;\
                  ifconfig %s up;\
                  ifconfig %s %s netmask 255.255.255.0 up;\
                  sleep 5;\
                  " % (self.peer_if1, self.peer_if2, self.peer_if1,
                       self.peer_if2, self.bond_name, self.bond_name,
                       self.bond_name, self.peer_if1, self.bond_name,
                       self.peer_if2, self.bond_name, self.peer_if1,
                       self.peer_if2, self.bond_name, self.peer_ip)
            peer_cmd = "ssh %s \"%s\"" % (self.peer_ip, cmd)
            if process.system(peer_cmd, shell=True, ignore_status=True) != 0:
                self.fail("bond setup command failed in peer machine")

    def test_bonding(self):
        '''
        test options are mandatory
        ext test options are depends upon user
        '''
        self.log.info("Bonding")
        msg = "[ -d /sys/class/net/%s ]" % self.bond_name
        cmd = "ssh %s %s" % (self.peer_ip, msg)
        if process.system(cmd, shell=True, ignore_status=True) == 0:
            self.fail("bond name already exists on peer machine")
        self.bond_dir = os.path.join("/sys/class/net/", self.bond_name)
        if os.path.isdir(self.bond_dir):
            self.fail("bond name already exists on local machine")
        self.bond_setup("peer", "")
        for val in self.mode:
            self.bond_setup("local", val)
            cmd = "cat /proc/net/bonding/%s" % self.bond_name
            process.run(cmd, shell=True, verbose=True)
            self.ping_check(val)
            self.bond_fail(val)
            time.sleep(5)
            self.log.info("Mode %s OK" % val)
            self.bond_remove("local")
        cmd = "ifconfig %s %s netmask 255.255.255.0 up"\
              % (self.host_if1, self.local_ip)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("unable to bring up to original state")
        time.sleep(5)
        cmd = "ifconfig %s %s netmask 255.255.255.0 up"\
              % (self.host_if2, self.local_ip2)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            self.fail("unable to bring up to original state")
        time.sleep(5)
        self.bond_remove("peer")


if __name__ == "__main__":
    main()
