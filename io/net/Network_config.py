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
from avocado.utils import pci


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
                self.cancel("%s package is need to test" % pkg)
        interfaces = netifaces.interfaces()
        self.iface = self.params.get("interface")
        if self.iface not in interfaces:
            self.cancel("%s interface is not available" % self.iface)
        cmd = "ethtool -i %s" % self.iface
        for line in process.system_output(cmd, shell=True).decode("utf-8") \
                                                          .splitlines():
            if 'bus-info' in line:
                self.businfo = line.split()[-1]
        self.log.info(self.businfo)
        self.driver = pci.get_driver(self.businfo)

    def test_driver_check(self):
        '''
        driver match check using lspci and ethtool
        '''
        cmd = "ethtool -i %s" % self.iface
        for line in process.system_output(cmd, shell=True).decode("utf-8") \
                                                          .splitlines():
            if 'driver' in line:
                driver = line.split()[-1]
        self.log.info(driver)
        if self.driver != driver:
            self.fail("mismatch in driver information")

    def get_network_sysfs_param(self, param):
        '''
        To finding the value for all parameters
        '''
        cmd = r"cat /sys/module/%s/drivers/pci\:%s/%s/net/%s/%s" %\
              (self.driver, self.driver, self.businfo, self.iface, param)
        return process.system_output(cmd, shell=True).decode("utf-8").strip()

    def test_mtu_check(self):
        '''
        comparing mtu value
        '''
        mtu = self.get_network_sysfs_param("mtu")
        self.log.info("mtu value is %s" % mtu)
        mtuval = process.system_output("ip link show %s" % self.iface,
                                       shell=True).decode("utf-8").split()[4]
        self.log.info("through ip link show, mtu value is %s" % mtuval)
        if mtu != mtuval:
            self.fail("mismatch in mtu")

    def test_speed_check(self):
        '''
        Comparing speed
        '''
        speed = self.get_network_sysfs_param("speed")
        cmd = "ethtool %s" % self.iface
        for line in process.system_output(cmd, shell=True).decode("utf-8") \
                                                          .splitlines():
            if 'Speed' in line:
                eth_speed = line.split()[-1].strip('Mb/s')
        if speed != eth_speed:
            self.fail("mis match in speed")

    def test_mac_aadr_check(self):
        '''
        comparing mac address
        '''
        address = self.get_network_sysfs_param("address")
        self.log.info("mac address is %s" % address)
        hw_addr = netifaces.ifaddresses(self.iface)[netifaces.AF_LINK]
        hw_addr = hw_addr[0]['addr']
        if hw_addr != address:
            self.fail("mismatch in hardware address")

    def test_duplex_check(self):
        '''
        comparing duplex
        '''
        duplex = self.get_network_sysfs_param("duplex")
        self.log.info("transmission mode is %s" % duplex)
        cmd = "ethtool %s" % self.iface
        for line in process.system_output(cmd, shell=True).decode("utf-8") \
                                                          .splitlines():
            if 'Duplex' in line:
                eth_duplex = line.split()[-1]
        if str(duplex).capitalize() != eth_duplex:
            self.fail("mismatch in duplex")


if __name__ == "__main__":
    main()
