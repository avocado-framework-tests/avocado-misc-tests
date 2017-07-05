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
        self.slot = self.params.get('pci_device', default='0001:01:00.0')
        self.driver = pci.get_driver(self.slot)
        if not self.driver:
            self.cancel("%s does not exist" % self.slot)

    def test(self):
        """
        Creates namespace on the device.
        """
        cmd = "echo -n %s > /sys/bus/pci/drivers/%s/unbind" \
            % (self.slot, self.driver)
        process.run(cmd, shell=True, sudo=True)
        time.sleep(5)
        cmd = 'ls /sys/bus/pci/drivers/%s' % self.driver
        process.run(cmd, shell=True)
        if os.path.exists("/sys/bus/pci/drivers/%s/%s"
                          % (self.driver, self.slot)):
            self.return_code = 1
        cmd = "echo -n %s > /sys/bus/pci/drivers/%s/bind" \
            % (self.slot, self.driver)
        process.run(cmd, shell=True, sudo=True)
        time.sleep(5)
        cmd = 'ls /sys/bus/pci/drivers/%s' % self.driver
        process.run(cmd, shell=True)
        if not os.path.exists("/sys/bus/pci/drivers/%s/%s"
                              % (self.driver, self.slot)):
            self.return_code = 2
        if self.return_code == 1:
            self.fail('%s not unbound' % self.slot)
        if self.return_code == 2:
            self.fail('%s not bound back' % self.slot)


if __name__ == "__main__":
    main()
