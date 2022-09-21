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
# Copyright: 2022 IBM
# Author: Maram Srimannarayana Murthy<Maram.Srimannarayana.Murthy@ibm.com>

"""
PCI CFG Test.
Needs to be run as root.
"""

from avocado import Test
from avocado.utils.software_manager import SoftwareManager
from avocado.utils import pci
from avocado.utils import process


class PciLscfgInfo(Test):
    '''
    Check lscfg info with lspci info
    '''

    def setUp(self):
        '''
        To check and install dependencies for the test
        '''
        smm = SoftwareManager()
        for pkg in ["lsvpd", "pciutils"]:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel("{pkg} package is need to test")

    def test(self):
        '''
        Capture data from lscfg and lspci then compare data
        '''
        error = []
        for pci_addr in pci.get_pci_addresses():
            self.log.info("Checking for PCI Address: %s\n\n", pci_addr)
            pci_info_dict = pci.get_pci_info(pci_addr)
            self.log.info(pci_info_dict)
            cfg_output = pci.get_cfg(pci_addr)
            self.log.info(cfg_output)
            if cfg_output and pci_info_dict:
                if 'YL' in cfg_output and 'PhySlot' in pci_info_dict:
                # Physical Slot Match
                    self.log.info("Physical Slot from lscfg is %s"
                                  " and lspci is %s",
                            cfg_output['YL'], pci_info_dict['PhySlot'])
                    cfg_output['YL'] = \
                            cfg_output['YL'][:cfg_output['YL'].rfind('-')]
                    if(cfg_output['YL'] == pci_info_dict['PhySlot']):
                        self.log.info("Physical Slot matched")
                    else:
                        error.append("Physical slot info didn't match")
                # Sub Device ID match
                if ('subvendor_device' in cfg_output and 
                'SDevice' in pci_info_dict):
                    self.log.info("Device iD from lscfg is %s"
                                  " and lspci is %s",
                            cfg_output['subvendor_device'][4:],
                            pci_info_dict['SDevice'])
                    if(cfg_output['subvendor_device'][4:]
                                           == pci_info_dict['SDevice']):
                        self.log.info("Sub Device ID matched")
                    else:
                        error.append("Device ID info didn't match")
                # Subvendor ID Match
                if ('subvendor_device' in cfg_output and 
                'SVendor' in pci_info_dict):
                    self.log.info("Subvendor ID from lscfg is %s"
                                  "and lspci is %s",
                            cfg_output['subvendor_device'],
                            pci_info_dict['SVendor'])
                    if(cfg_output['subvendor_device'][0:4] ==
                        pci_info_dict['SVendor']):
                        self.log.info("Sub vendor ID matched")
                    else:
                        error.append("Sub vendor ID didn't match")
                # PCI Slot ID Match
                if 'pci_id' in cfg_output and 'Slot' in pci_info_dict:
                    self.log.info("PCI ID from lscfg is %s and lspci is %s",
                            cfg_output['pci_id'], pci_info_dict['Slot'])
                    if(cfg_output['pci_id'] ==
                                           pci_info_dict['Slot']):
                        self.log.info("PCI Slot ID matched")
                    else:
                        error.append("PCI slot ID didn't match")
                # PCI Config Space Check
                if process.system(f"lspci -xxxx -s {pci_addr}",
                                  sudo=True):
                    error.append(pci_addr + " : pci_config_space")
        if error:
            self.fail(f"Errors for above pci addresses: {error}")

