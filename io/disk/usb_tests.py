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
# Copyright: 2023 IBM
# Author: Maram Srimannarayana Murthy <msmurthy@linux.vnet.ibm.com>
"""
This script will perform usb related testcases
"""
from avocado import Test
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils import disk
from avocado.utils import pci


class USBTests(Test):

    '''
    Class to execute usb tests
    '''

    def setUp(self):
        """
        Function for preliminary set-up to execute the test
        """
        smm = SoftwareManager()
        for pkg in ["usbguard"]:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel(f"{pkg} is not installed")
        self.usb_pci_device = self.params.get("pci_device", default=None)
        if not self.usb_pci_device:
            self.cancel("please provide pci adrees or wwids of scsi disk")
        if self.usb_pci_device not in pci.get_pci_addresses():
            self.cancel(f"PCI Adress {self.usb_pci_device} not found among "
                        f"list of available PCI devices")
        self.usb_disk = self.params.get("disk", default=None)
        if not self.usb_disk:
            self.cancel("Disk information not provided in yaml")
        if self.usb_disk:
            self.usb_disk = disk.get_absolute_disk_path(self.usb_disk)
        self.num_of_partitions = self.params.get("num_of_partitions", default=None)
        self.partition_size = self.params.get("partition_size", default=None)

    def test_create_usb_partitions(self):
        """
        Create specified number of partitions on USB disk
        """
        if self.num_of_partitions and self.partition_size:
            partitions = disk.create_linux_raw_partition(
                self.usb_disk,
                size=self.partition_size,
                num_of_par=self.num_of_partitions
            )
        elif self.num_of_partitions and not self.partition_size:
            partitions = disk.create_linux_raw_partition(
                self.usb_disk,
                num_of_par=self.num_of_partitions
            )
        elif not self.num_of_partitions and self.partition_size:
            partitions = disk.create_linux_raw_partition(
                self.usb_disk,
                size=self.partition_size,
            )
        self.log.info(f"Partitions created: {partitions}")

    def test_delete_all_usb_partitions(self):
        """
        Deletes all partition on USB disk and wipes partition table on USB
        """
        disk.clean_disk(self.usb_disk)
        partitions = disk.get_disk_partitions(self.usb_disk)
        if partitions:
            self.log.fail("Partitions {partitions} not deleted")
