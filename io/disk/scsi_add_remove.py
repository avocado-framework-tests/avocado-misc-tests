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
# Copyright: 2017 IBM
# Author: Narasimhan V <sim@linux.vnet.ibm.com>
# Author: Venkat Rao B <vrbagal1@linux.vnet.ibm.com>
"""
This script will perform scsi add and remove test case
"""
import time
from avocado import Test
from avocado.utils import process, genio
from avocado.utils.software_manager import SoftwareManager


class ScsiAddRemove(Test):

    '''
    Class to execute scsi add/remove operation
    '''

    def setUp(self):
        '''
        Function for preliminary set-up to execute the test
        '''
        smm = SoftwareManager()
        if not smm.check_installed("lsscsi") and not smm.install("lsscsi"):
            self.error("lsscsi is not installed")
        self.pci_device = self.params.get("pci_device", default=None)
        if not self.pci_device:
            self.cancel("Please provide PCI address for which you \
                        want to run the test")

    def test(self):
        '''
        Function where test is executed
        '''
        device_list = []
        cmd = "ls -l /dev/disk/by-path/"
        output = process.run(cmd)
        for lines in output.stdout.splitlines():
            if self.pci_device in lines:
                device_list.append(lines.split()[-1])
        if not device_list:
            self.log.warning("No devices under the given PCI device")
        else:
            for device_id in device_list:
                device = device_id.split()[-1].strip("../*")
                self.log.info("device = %s", device)
                cmd = "lsscsi"
                output = process.run(cmd)
                for lines in output.stdout.splitlines():
                    if device in lines:
                        scsi_num = lines.split()[0].strip("[").strip("]")
                        self.log.info("scsi_num=%s", scsi_num)
                        scsi_num_seperated = scsi_num.replace(":", " ")
                        self.log.info("Deleting %s", scsi_num)
                        genio.write_file("/sys/block/%s/device/delete"
                                         % device, "1")
                        time.sleep(5)
                        self.log.info("%s deleted", scsi_num)
                        self.log.info("adding back %s", scsi_num)
                        process.run("echo scsi add-single-device %s > \
                                     /proc/scsi/scsi", scsi_num_seperated)
                        time.sleep(5)
                        self.log.info("%s Added back", scsi_num)
