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
# Author: Narasimhan V <sim@linux.vnet.ibm.com>

"""
Tcpdump Test.
"""

import os
import netifaces
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils.software_manager import SoftwareManager


class TcpdumpTest(Test):
    """
    Test the tcpdump for specified interface.
    """

    def setUp(self):
        """
        Set up.
        """
        self.iface = self.params.get("interface", default="")
        self.count = self.params.get("count", default="500")
        self.peer_ip = self.params.get("peer_ip", default="")
        self.drop = self.params.get("drop_accepted", default="10")
        # Check if interface exists in the system
        interfaces = netifaces.interfaces()
        if self.iface not in interfaces:
            self.cancel("%s interface is not available" % self.iface)
        if not self.peer_ip:
            self.cancel("peer ip should specify in input")

        # Install needed packages
        smm = SoftwareManager()
        if not smm.check_installed("tcpdump") and not smm.install("tcpdump"):
            self.cancel("Can not install tcpdump")

    def test(self):
        """
        Performs the tcpdump test.
        """
        cmd = "ping -I %s %s -c %s" % (self.iface, self.peer_ip, self.count)
        obj = process.SubProcess(cmd, verbose=False, shell=True)
        obj.start()
        output_file = os.path.join(self.outputdir, 'tcpdump')
        cmd = "tcpdump -i %s -n -c %s -w '%s'" % (self.iface, self.count,
                                                  output_file)
        for line in process.run(cmd, shell=True,
                                ignore_status=True).stderr.decode("utf-8") \
                                                   .splitlines():
            if "packets dropped by interface" in line:
                self.log.info(line)
                if int(line[0]) >= (int(self.drop) * int(self.count) / 100):
                    self.fail("%s, more than %s percent" % (line, self.drop))
        obj.stop()


if __name__ == "__main__":
    main()
