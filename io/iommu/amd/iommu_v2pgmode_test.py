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
# Copyright: 2023 Advanced Micro Devices, Inc.
# Author: Dheeraj Kumar Srivastava <dheerajkumar.srivastava@amd.com>

"""
Validate 5 level page table support in v2 iommu page table mode
"""

from avocado import Test, skipUnless
from avocado.utils import cpu, dmesg


def get_v2_pgtbl_lvl_sup_bits():
    """
    Extracts bits 13:12 from the AMD IOMMU extended feature register,
    which indicates maximum number of translation levels supported for guest
    address translation.

    :return: bits 13:12 value from the AMD IOMMU extended feature register
    :rtype: int
    :raise: raise exception if sysfs entry for IOMMU extended feature register/2
            is not present or not readable.
    """

    feature_regs = "/sys/class/iommu/ivhd0/amd-iommu/features"

    try:
        with open(feature_regs, "r", encoding="utf-8") as feature_file:
            features = feature_file.read().strip()
    except FileNotFoundError as err:
        raise ValueError(
            f"{feature_regs} not found. Is AMD IOMMU enabled on this system?"
        ) from err

    if ":" not in features:
        raise ValueError(f"Unexpected format in {feature_regs}: {features}")

    part1, part2 = features.split(":")
    ext1 = part1 if len(part1) > len(part2) else part2

    reg_val = int(ext1, 16)
    return (reg_val >> 12) & 0b11


def get_v2pgtbl_mode():
    """
    Parse dmesg to get the current v2 page table paging mode.
    """
    for mode in ["4", "5"]:
        if dmesg.check_kernel_logs(
            f"V2 page table enabled (Paging mode : {mode} level)"
        ):
            return mode
    return None


class IommuPageTable(Test):
    """
    Test v2 page table -
    1. Checks whether IOMMU in v2 page table boots with expected paging level.
       If both IOMMU and cpu supports 5-level page table, then IOMMU should boot with
       5-level v2 page table. Else IOMMU should boot with 4-level v2 page table.
    """

    @skipUnless(
        "x86_64" in cpu.get_arch(),
        "This test runs on x86-64 platform.\
        If 5-level page table supported on other platform then\
        this condition can be removed",
    )
    def setUp(self):
        """
        Few checks before test
        """

        # Check if iommu is in translation
        if dmesg.check_kernel_logs("AMD-Vi"):
            if not dmesg.check_kernel_logs("iommu: Default domain type: Translated"):
                self.cancel("IOMMU is not in Translation mode")
        else:
            self.cancel("IOMMU is not enabled")

        if not dmesg.check_kernel_logs("V2 page table enabled"):
            self.cancel("IOMMU is in v1 page table")

        self.v2pgtbl_mode = get_v2pgtbl_mode()
        if self.v2pgtbl_mode is None:
            self.cancel(
                "Current v2 page table mode could not be determined via dmesg. "
                "This may be due to dmesg or journalctl logs being cleaned, "
                "deleted, or unavailable."
            )

    def test(self):
        """
        Test if host page table mode matches with iommu v2 page table mode
        """
        try:
            if cpu.cpu_has_flags(["la57"]) and get_v2_pgtbl_lvl_sup_bits() == 1:
                expected_v2pgtbl_mode = "5"
            else:
                expected_v2pgtbl_mode = "4"

            if not self.v2pgtbl_mode == expected_v2pgtbl_mode:
                self.fail(
                    f"IOMMU expected {expected_v2pgtbl_mode}-level v2 page table, "
                    f"but current IOMMU v2 page table level is "
                    f"{self.v2pgtbl_mode if self.v2pgtbl_mode else 'unknown'}."
                )
            self.log.info(
                "IOMMU booted with expected %s-level v2 page table.",
                expected_v2pgtbl_mode,
            )

        except Exception as err:  # pylint: disable=broad-exception-caught
            self.fail(f"{err}")
