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
# Author: Naresh Bannoth <nbannoth@in.ibm.com>
"""
This script will perform scsi add and remove test case
"""
import time
from avocado import main
from avocado import Test
from avocado.utils import process, genio
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import multipath
from avocado.utils import pci


class ScsiAddRemove(Test):

    '''
    Class to execute scsi add/remove operation
    '''

    def setUp(self):
        '''
        Function for preliminary set-up to execute the test
        '''
        self.err_paths = []
        self.device_list = []
        smm = SoftwareManager()
        if not smm.check_installed("lsscsi") and not smm.install("lsscsi"):
            self.cancel("lsscsi is not installed")
        self.wwids = self.params.get('wwids', default='')
        self.pci_device = self.params.get("pci_device", default='')
        system_pci_adress = pci.get_pci_addresses()
        system_wwids = multipath.get_multipath_wwids()
        if self.wwids:
            self.wwids = self.wwids.split(',')
            for wwid in self.wwids:
                if wwid not in system_wwids:
                    self.cancel("%s not present in the system" % wwid)
                for path in multipath.get_paths(wwid):
                    self.device_list.append(path)
        elif self.pci_device:
            self.pci_device = self.pci_device.split(',')
            for pci_id in self.pci_device:
                if pci_id not in system_pci_adress:
                    self.cancel("%s not present in the system" % pci_id)
                cmd = "ls -l /dev/disk/by-path/"
                for line in process.system_output(cmd).splitlines():
                    if pci_id in line and 'part' not in line:
                        self.device_list.append(line.split('/')[-1])
        else:
            self.cancel("please provide pci adrees or wwids of scsi disk")

    def is_exists_scsi_device(self, device):
        '''
        Check whether the scsi_device is present in lsscsi output
        '''
        devices = []
        for line in process.system_output("lsscsi").splitlines():
            devices.append(line.split('/')[-1].strip(' '))
        if device in devices:
            return True
        else:
            return False

    def get_scsi_id(self, path):
        '''
        calculate and return the scsi_id of a disk
        '''
        cmd = "lsscsi"
        out = process.run(cmd)
        for lines in out.stdout.splitlines():
            if path in lines:
                scsi_num = lines.split()[0].strip("[").strip("]")
                self.log.info("scsi_num=%s", scsi_num)
                scsi_num = scsi_num.replace(":", " ")
                return scsi_num

    def test(self):
        '''
        Function where test is executed
        '''
        self.log.info("device lists : %s " % self.device_list)
        for device in self.device_list:
            scsi_id = self.get_scsi_id(device)
            process.run("\nlsscsi\n")
            self.log.info("\nDeleting %s = %s\n" % (device, scsi_id))
            genio.write_file("/sys/block/%s/device/delete" % device, "1")
            time.sleep(5)
            if self.is_exists_scsi_device(device) is True:
                self.err_paths.append(device)
            else:
                self.log.info("\n%s = %s deleted\n" % (device, scsi_id))
            self.log.info("\nadding back %s = %s\n" % (device, scsi_id))
            part = "scsi add-single-device %s" % scsi_id
            genio.write_file("/proc/scsi/scsi", part)
            time.sleep(5)
            if self.is_exists_scsi_device(device) is False:
                self.err_paths.append(device)
            else:
                process.run("\nlsscsi\n")
                self.log.info("\n%s = %s Added back\n" % (device, scsi_id))

    def tearDown(self):
        '''
        checking if any failure and exit the test
        '''
        if self.err_paths:
            self.fail("\nPaths failed to add or remove %s\n" % self.err_paths)


if __name__ == "__main__":
    main()
