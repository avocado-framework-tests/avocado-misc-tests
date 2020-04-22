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
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.network.hosts import LocalHost


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
                                            shell=True).decode("utf-8").strip()
        self.count = int(self.params.get('count', default="1"))
        self.peer_ip = self.params.get('peer_ip', default=None)
        self.ipaddr = self.params.get("host_ip", default="")
        self.netmask = self.params.get("netmask", default="")
        local = LocalHost()
        self.networkinterface = NetworkInterface(self.interface, local)
        try:
            self.networkinterface.add_ipaddr(self.ipaddr, self.netmask)
            self.networkinterface.save(self.ipaddr, self.netmask)
        except Exception:
            self.networkinterface.save(self.ipaddr, self.netmask)
        self.networkinterface.bring_up()

    def test(self):
        """
        Performs driver unbind and bind for the Network virtualized device
        """
        if self.networkinterface.ping_check(self.peer_ip, count=5) is not None:
            self.cancel("Please make sure the network peer is configured ?")

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
                if self.networkinterface.ping_check(self.peer_ip,
                                                    count=5) is not None:
                    self.fail("Ping test failed. Network virtualized \
                           unbind/bind has affected Network connectivity")
        except CmdError as details:
            self.log.debug(str(details))
            self.fail("Driver %s operation failed for Network virtualized \
                       device %s" % (operation, self.interface))


if __name__ == "__main__":
    main()
