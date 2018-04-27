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

import time
import netifaces
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils.software_manager import SoftwareManager
from avocado.utils.process import CmdError


class NetworkVirtualizationFailoverTest(Test):

    """
    This test performs failover for a Network virtualized device
    """

    def setUp(self):
        """
        Install necessary packages and identify the network
        virtualized device.
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

    def test(self):
        '''
        Performs failover for Network virtualized device
        '''
        try:
            for val in range(self.count):
                self.log.info("Performing Client initiated\
                              failover - Attempt %s" % int(val+1))
                process.run('echo 1 > /sys/devices/vio/%s/failover' %
                            self.device, shell=True, sudo=True)
                time.sleep(10)
                self.log.info("Running a ping test to check if failover \
                                affected Network connectivity")
                if process.system('ping -I %s %s -c 5' %
                                  (self.interface, self.peer_ip),
                                  shell=True, ignore_status=True):
                    self.fail("Ping test failed. Network virtualized \
                               failover had affected Network connectivity")
        except CmdError as details:
            self.log.debug(str(details))
            self.fail("Client initiated Failover for Network virtualized \
                       device %s failed" % self.interface)


if __name__ == "__main__":
    main()
