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
# Author: Naresh Bannoth <nbannoth@linux.vnet.ibm.com>

"""
PCI VPD Test.
Needs to be run as root.
"""

from avocado import Test
from avocado.utils.software_manager import SoftwareManager
from avocado import main
from avocado.utils import pci
from avocado.utils import process


class PciLsvpdInfo(Test):
    '''
    check lsvpd info
    '''

    def setUp(self):
        '''
        To check and install dependencies for the test
        '''
        smm = SoftwareManager()
        for pkg in ["lsvpd"]:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel("%s package is need to test" % pkg)
        if process.system("vpdupdate", ignore_status=True, shell=True):
            self.fail("VPD Update fails")

    def test(self):
        '''
        Test
        '''
        error = []
        for pci_addr in pci.get_pci_addresses():
            self.log.info("Checking for PCI Address: %s\n\n", pci_addr)
            vpd_output = pci.get_vpd(pci_addr)
            if vpd_output:

                # Slot Match
                if 'slot' in vpd_output:
                    sys_slot = pci.get_slot_from_sysfs(pci_addr)
                    if sys_slot:
                        sys_slot = sys_slot.strip('\0')
                    vpd_slot = vpd_output['slot']
                    self.log.info("Slot from sysfs: %s", sys_slot)
                    self.log.info("Slot from lsvpd: %s", vpd_slot)
                    if sys_slot in [sys_slot, vpd_slot[:vpd_slot.rfind('-')]]:
                        self.log.info("=======>>> slot matches perfectly\n\n")
                    else:
                        error.append(pci_addr + "-> slot")
                        self.log.info("--->>Slot Numbers not Matched\n\n")
                else:
                    self.log.error("Slot info not available in vpd output\n")

                # Device ID match
                sys_pci_id_output = pci.get_pci_id_from_sysfs(pci_addr)
                vpd_dev_id = vpd_output['pci_id'][4:]
                sysfs_dev_id = sys_pci_id_output[5:-10]
                sysfs_sdev_id = sys_pci_id_output[15:]
                self.log.info("Device ID from sysfs: %s", sysfs_dev_id)
                self.log.info("Sub Device ID from sysfs: %s", sysfs_sdev_id)
                self.log.info("Device ID from vpd: %s", vpd_dev_id)
                if vpd_dev_id == sysfs_sdev_id or vpd_dev_id == sysfs_dev_id:
                    self.log.info("=======>>Device ID Match Success\n\n")
                else:
                    self.log.error("----->>Device ID did not Match\n\n")
                    error.append(pci_addr + "-> Device_id")

                # Subvendor ID Match
                sysfs_subvendor_id = sys_pci_id_output[10:-5]
                vpd_subvendor_id = vpd_output['pci_id'][:4]
                self.log.info("Subvendor ID frm sysfs: %s", sysfs_subvendor_id)
                self.log.info("Subvendor ID from vpd : %s", vpd_subvendor_id)
                if sysfs_subvendor_id == vpd_subvendor_id:
                    self.log.info("======>>>Subvendor ID Match Success\n\n")
                else:
                    self.log.error("---->>Subvendor_id Not Matched\n\n")
                    error.append(pci_addr + "-> Subvendor_id")

                # PCI ID Match
                lspci_pci_id = pci.get_pci_id(pci_addr)
                self.log.info(" PCI ID from Sysfs: %s", sys_pci_id_output)
                self.log.info("PCI ID from Vpd : %s", lspci_pci_id)

                if sys_pci_id_output == lspci_pci_id:
                    self.log.info("======>>>> All PCI ID match Success\n\n")
                else:
                    self.log.error("---->>>PCI info Did not Matches\n\n")
                    error.append(pci_addr + "-> pci_id")

                # PCI Config Space Check
                if process.system("lspci -xxxx -s %s" % pci_addr,
                                  ignore_status=True, sudo=True):
                    error.append(pci_addr + "->pci_config_space")

        if error:
            self.fail("Errors for above pci addresses: %s" % error)


if __name__ == "__main__":
    main()
