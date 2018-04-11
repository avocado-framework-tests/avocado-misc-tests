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

"""
Network virtualized devices can be bound and unbound to drivers.
This test verifies that for a given Network virtualized device.
"""

import os
import time
import netifaces
from avocado.utils import genio
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils.software_manager import SoftwareManager
from avocado.utils.process import CmdError


class NetworkVirtualizationDriverBindTest(Test):

    """
    Network virtualized devices can be bound and unbound to drivers.
    This test verifies that for a given Network virtualized device.
    """

    def setUp(self):
        """
        Identify the network virtualized device.
        """
        smm = SoftwareManager()
        for pkg in ["net-tools"]:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel("%s package is need to test" % pkg)
        self.device_ip = self.params.get('device_ip', '*', default=None)
        self.netmask = self.params.get('netmask', '*', default=None)
        self.peer_ip = self.params.get('peer_ip', default=None)
        self.count = int(self.params.get('count', default="1"))

    def test(self):
        """
        Performs driver unbind and bind for the Network virtualized device
        """
        device_id = self.find_device_id()
        try:
            for _ in range(self.count):
                for operation in ["unbind", "bind"]:
                    self.log.info("Running %s operation for Network virtualized \
                                   device", operation)
                    genio.write_file(os.path.join
                                     ("/sys/bus/vio/drivers/ibmvnic",
                                      operation), "%s" % device_id)
                    time.sleep(5)
                self.log.info("Running a ping test to check if unbind/bind \
                                    affected newtwork connectivity")
                if not self.ping_check():
                    self.fail("Ping test failed. Network virtualized \
                           unbind/bind has affected Network connectivity")
        except CmdError as details:
            self.log.debug(str(details))
            self.fail("Driver %s operation failed" % operation)

    @staticmethod
    def find_device():
        """
        Finds out the latest added network virtualized device
        """
        device = netifaces.interfaces()[-1]
        return device

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
        if 'state UP' in process.system_output("ip link \
             show %s" % device, shell=True):
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

    def ping_check(self):
        """
        ping check
        """
        device = self.configure_device()
        cmd = "ping -I %s %s -c 5"\
              % (device, self.peer_ip)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            return False
        return True

    def tearDown(self):
        """
        Flush the ip configured for network virtualized device
        """
        device = self.find_device()
        cmd = "ip addr flush dev %s" % device
        if process.system(cmd, shell=True, verbose=True,
                          ignore_status=True) != 0:
            self.log.info("Unable to flush the IP for %s", device)


if __name__ == "__main__":
    main()
