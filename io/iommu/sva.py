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
# Copyright: 2025 Advanced Micro Devices, Inc.
# Author: Dheeraj Kumar Srivastava <dheerajkumar.srivastava@amd.com>

"""
SVA-related PCIe capability - (PASID, ATS, PRI) tests.
"""

import re

from avocado import Test
from avocado.utils import pci, process
from avocado.utils.software_manager.manager import SoftwareManager


class SVA(Test):
    """
    Test suite to check PCI device capabilities such as PASID, ATS, and PRI.
    """

    def setUp(self):
        """
        Test initialisation, setup and pre checks.
        """
        self.pci_device = self.params.get("pci_device", default=None)

        smm = SoftwareManager()
        if not smm.check_installed("pciutils") and not smm.install("pciutils"):
            self.cancel("pciutils package not found and installing failed")

        # Check if device input is valid
        if self.pci_device is None or self.pci_device not in pci.get_pci_addresses():
            self.cancel(
                "Please provide full pci address of a valid pci device on system"
            )

    # TODO: Need to push this to avocado utils later
    def check_device_capability(self, pci_device, cap, cap_ctrl):
        """
        Checks the given PCI device for a specific capability and whether it is enabled or not.

        :param pci_device: full pci address including domain (e.g., "0000:01:00.0")
        :param cap: capability to search for in the lspci output.
        :param cap_ctrl: Field that specifies whether the capability is enabled.
        """
        # Run lspci once
        cmd = f"lspci -vvv -s '{pci_device}'"
        output = process.run(cmd, ignore_status=True, shell=True, sudo=True).stdout_text

        # Check capability
        if cap not in output:
            self.cancel(f"{cap} capability not found for {pci_device}")

        # Check if capability is enabled
        if cap_ctrl not in output or not re.search(rf"{cap_ctrl}:\s*Enable\+", output):
            self.cancel(f"{pci_device}: {cap} capability is not enabled")

        self.log.info("%s: %s capability is enabled", pci_device, cap)

    def test_pasid_capability(self):
        """
        Test the PCI device for PASID capability and verifies whether PASID enabled.
        """
        cap = "Process Address Space ID (PASID)"
        self.check_device_capability(self.pci_device, cap, "PASIDCtl")

    def test_ats_capability(self):
        """
        Test the PCI device for ATS capability and verifies whether ATS is enabled.
        """
        cap = "Address Translation Service (ATS)"
        self.check_device_capability(self.pci_device, cap, "ATSCtl")

    def test_pri_capability(self):
        """
        Test the PCI device for PRI capability and verifies whether PRI is enabled.
        """
        cap = "Page Request Interface (PRI)"
        self.check_device_capability(self.pci_device, cap, "PRICtl")
