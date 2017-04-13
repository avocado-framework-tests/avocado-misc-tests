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
#
# test network configuration
# network configuration includes speed,
# driver name, businfo, hardware address

import netifaces
from avocado import main
from avocado import Test
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import process


class NetworkconfigTest(Test):
    '''
    check Network_configuration
    using ethtool and lspci
    '''

    def setUp(self):
        '''
        To check and install dependencies for the test
        '''
        sm = SoftwareManager()
        for pkg in ["ethtool", "net-tools"]:
            if not sm.check_installed(pkg) and not sm.install(pkg):
                self.skip("%s package is need to test" % pkg)
        interfaces = netifaces.interfaces()
        self.iface = self.params.get("interface")
        if self.iface not in interfaces:
            self.skip("%s interface is not available" % self.iface)

    def test_networkconfig(self):
        '''
        check Network_configuration
        '''
        cmd = "ethtool -i %s | grep driver | awk '{print $2}'" % self.iface
        driver = process.system_output(cmd, shell=True).strip()
        self.log.info(driver)
        cmd = "ethtool -i %s | grep bus-info | awk '{print $2}'" % self.iface
        businfo = process.system_output(cmd, shell=True).strip()
        self.log.info(businfo)
        cmd = "lspci -v"
        bus_info = process.system_output(cmd, shell=True).strip()
        bus_info = bus_info.split('\n\n')
        self.log.info("Performing driver match check using lspci and ethtool")
        self.log.info("-----------------------------------------------------")
        for value in bus_info:
            if value.startswith(businfo):
                self.log.info("details are ---------> %s" % value)
                tmp = value.split('\n')
                for val in tmp:
                    if 'Kernel driver in use' in val:
                        cmd, driverinfo = val.split(': ')
                        self.log.info(driverinfo)
                        if driver != driverinfo:
                            self.fail("mismatch in driver information")
        cmd = "cat /sys/module/%s/drivers/pci\:%s/%s/net/%s/mtu" %\
              (driver, driver, businfo, self.iface)
        mtu = process.system_output(cmd, shell=True).strip()
        self.log.info("mtu value is %s" % mtu)
        cmd = "cat /sys/module/%s/drivers/pci\:%s/%s/net/%s/operstate" %\
              (driver, driver, businfo, self.iface)
        operstate = process.system_output(cmd, shell=True).strip()
        self.log.info("operstate is %s" % operstate)
        cmd = "cat /sys/module/%s/drivers/pci\:%s/%s/net/%s/duplex" %\
              (driver, driver, businfo, self.iface)
        duplex = process.system_output(cmd, shell=True).strip()
        self.log.info("transmission mode is %s" % duplex)
        cmd = "cat /sys/module/%s/drivers/pci\:%s/%s/net/%s/address" %\
              (driver, driver, businfo, self.iface)
        address = process.system_output(cmd, shell=True).strip()
        self.log.info("mac address is %s" % address)
        cmd = "cat /sys/module/%s/drivers/pci\:%s/%s/net/%s/speed" %\
              (driver, driver, businfo, self.iface)
        speed = process.system_output(cmd, shell=True).strip()
        self.log.info("speed is %s" % speed)
        cmd = "ethtool %s | grep Speed | awk '{print $2}'" % self.iface
        eth_speed = process.system_output(cmd, shell=True).strip()
        eth_speed = eth_speed.strip('Mb/s')
        self.log.info("Performing Ethtool and interface checks for interface")
        self.log.info("-----------------------------------------------------")
        if speed != eth_speed:
            self.fail("mis match in speed")
        hw_addr = netifaces.ifaddresses(self.iface)[netifaces.AF_LINK]
        hw_addr = hw_addr[0]['addr']
        if hw_addr != address:
            self.fail("mismatch in hardware address")
        cmd = "ifconfig %s" % self.iface
        mtuval = process.system_output(cmd, shell=True).strip().split('\n')
        for val in mtuval:
            if 'mtu' in val:
                cmd, mtu_val = val.split('mtu ')
                self.log.info("through ifconfig mtu value is %s" % mtu_val)
                if mtu != mtu_val:
                    self.fail("mismatch in mtu")
            if 'MTU' in val:
                cmd, mtu_val = val.split('MTU:')
                mtu_val, cmd = mtu_val.split(' M')
                mtu_val = mtu_val.strip()
                self.log.info("through ifconfig mtu value is %s" % mtu_val)
                if mtu != mtu_val:
                    self.fail("mismatch in mtu")
        eth_state = process.system_output("ethtool %s | grep 'Link detected:'\
                                          " % self.iface, shell=True)
        if 'yes' in eth_state and operstate == 'down':
            self.fail("mis match in link state")
        if 'no' in eth_state and operstate == 'up':
            self.fail("mis match in link state")


if __name__ == "__main__":
    main()
