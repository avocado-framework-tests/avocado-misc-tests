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
PCI devices can be bound and unbound to drivers.
This test verifies that for given adapters.
"""

import os
import time
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils import pci
from avocado.utils.software_manager import SoftwareManager


class DriverBindTest(Test):

    """
    PCI devices can be bound and unbound to drivers.
    This test verifies that for given adapters.

    :param device: Name of the pci device
    """

    def setUp(self):
        """
        Setup the device.
        """
        self.return_code = 0
        self.pci_devices = self.params.get('pci_devices', default=None)
        self.count = int(self.params.get('count', default=1))
        if not self.pci_devices:
            self.cancel("No pci_adresses Given")
        smm = SoftwareManager()
        if not smm.check_installed("pciutils") and not smm.install("pciutils"):
            self.cancel("pciutils package is need to test")

    def test(self):
        """
        Creates namespace on the device.
        """
        for pci_addr in self.pci_devices.split(","):
            driver = pci.get_driver(pci_addr)
            for _ in range(self.count):
                self.log.info("iteration:%s for PCI_ID = %s" % (_, pci_addr))
                cmd = "echo -n %s > /sys/bus/pci/drivers/%s/unbind" \
                    % (pci_addr, driver)
                process.run(cmd, shell=True, sudo=True)
                time.sleep(5)
                cmd = 'ls /sys/bus/pci/drivers/%s' % driver
                process.run(cmd, shell=True)
                if os.path.exists("/sys/bus/pci/drivers/%s/%s"
                                  % (driver, pci_addr)):
                    self.return_code = 1
                else:
                    self.log.info("successfully unbinded %s" % pci_addr)
                cmd = "echo -n %s > /sys/bus/pci/drivers/%s/bind" \
                    % (pci_addr, driver)
                process.run(cmd, shell=True, sudo=True)
                time.sleep(5)
                cmd = 'ls /sys/bus/pci/drivers/%s' % driver
                process.run(cmd, shell=True)
                if not os.path.exists("/sys/bus/pci/drivers/%s/%s"
                                      % (driver, pci_addr)):
                    self.return_code = 2
                else:
                    self.log.info("successfully binded back %s" % pci_addr)
                if self.return_code == 1:
                    self.fail('%s not unbound in itertion=%s' % (pci_addr, _))
                if self.return_code == 2:
                    self.fail('%s not bound back itertion=%s' % (pci_addr, _))


if __name__ == "__main__":
    main()
