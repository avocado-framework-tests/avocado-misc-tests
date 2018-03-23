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
    :param device: Name of the Network virtualized device
    """

    def setUp(self):
        """
        Identify the network virtualized device.
        """
        smm = SoftwareManager()
        for pkg in ["net-tools"]:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel("%s package is need to test" % pkg)
        interfaces = netifaces.interfaces()
        self.interface = self.params.get('interface')
        if self.interface not in interfaces:
            self.cancel("%s interface is not available" % self.interface)
        self.device = process.system_output("ls -l /sys/class/net/ | \
                                             grep %s | cut -d '/' -f \
                                             5" % self.interface,
                                            shell=True).strip()
        self.count = int(self.params.get('count', default="1"))
        self.peer_ip = self.params.get('peer_ip', default=None)

    def ping_check(self):
        """
        ping check
        """
        cmd = "ping -I %s %s -c 5"\
              % (self.interface, self.peer_ip)
        if process.system(cmd, shell=True, ignore_status=True) != 0:
            return False
        return True

    def test(self):
        """
        Performs driver unbind and bind for the Network virtualized device
        """
        try:
            for _ in range(self.count):
                for operation in ["unbind", "bind"]:
                    self.log.info("Running %s operation for Network virtualized \
                                   device" % operation)
                    genio.write_file(os.path.join
                                     ("/sys/bus/vio/drivers/ibmvnic",
                                      operation), "%s" % self.device)
                    time.sleep(5)
                self.log.info("Running a ping test to check if unbind/bind \
                                    affected newtwork connectivity")
                if not self.ping_check():
                    self.fail("Ping test failed. Network virtualized \
                           unbind/bind has affected Network connectivity")
        except CmdError as details:
            self.log.debug(str(details))
            self.fail("Driver %s operation failed for Network virtualized \
                       device %s" % (operation, self.interface))


if __name__ == "__main__":
    main()
