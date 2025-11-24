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
Testing interrupt allocation and IOMMU remapping for PCI devices.
"""

import os
import errno
import struct
from fcntl import ioctl
from avocado import Test, skipIf
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils import cpu, process, dmesg, linux_modules, pci, vfio


def get_2k_irq_sup_bits():
    """
    Extracts bits 9:8 from the AMD IOMMU extended feature register2,
    which indicates whether IOMMU supports remapping of 2k interrupt per
    device function or not.

    :return: bits 9:8 value from the AMD IOMMU extended feature register2
    :rtype: int
    :raise: raise exception if sysfs entry for IOMMU extended feature register/2
            is not present or not readable.
    """

    feature_regs = "/sys/class/iommu/ivhd0/amd-iommu/features"

    try:
        with open(feature_regs, "r", encoding="utf-8") as f:
            features = f.read().strip()
    except FileNotFoundError as e:
        raise ValueError(
            f"{feature_regs} not found. Is AMD IOMMU enabled on this system?"
        ) from e

    if ":" not in features:
        raise ValueError(f"Unexpected format in {feature_regs}: {features}")

    part1, part2 = features.split(":")
    ext2 = part2 if len(part1) > len(part2) else part1

    reg_val = int(ext2, 16)
    # Extract bits 9:8 -> Whether IOMMU supports 2k interrupt remapping per device function)
    return (reg_val >> 8) & 0b11


@skipIf(cpu.get_vendor() != "amd", "Requires AMD platform")
# pylint: disable=C0103
class VFIOInterruptTest(Test):  # pylint: disable=too-many-instance-attributes
    """
    Testing interrupt allocation and IOMMU remapping for PCI devices.

    :param device: full pci address including domain (0000:03:00.0)
    :param count: number of interrupt/s to be allocated.
    """

    def setUp(self):
        """
        Test initialisation, setup and pre checks
        """

        # VFIO IOCTL constants
        self.pci_device = self.params.get("pci_device", default=None)
        self.initial_driver = pci.get_driver(self.pci_device)
        self.count = self.params.get("count", default=1)

        self.container_fd = None
        self.group_fd = None
        self.device_fd = None

        self.vfio_ioctls = {}

        smm = SoftwareManager()
        if not smm.check_installed("pciutils") and not smm.install("pciutils"):
            self.cancel("pciutils package not found and installing failed")

        try:
            self.count = int(self.count)
        except (ValueError, TypeError):
            self.cancel("'Count' input has to be an integer value")

        try:
            # Check if interrupt remapping is enabled
            if not dmesg.check_kernel_logs("AMD-Vi: Interrupt remapping enabled"):
                self.cancel("IOMMU Interrupt remapping is not enabled on the system")

            # Check kernel and hardware support for requested number of interrupt/s
            if self.count > 512 and get_2k_irq_sup_bits() == 0:
                self.cancel(
                    "IOMMU HW doesnot supports remapping of more than 512 interrupts per function"
                )

            if self.count > 2048 and (
                get_2k_irq_sup_bits() == 0 or get_2k_irq_sup_bits() == 1
            ):
                self.cancel(
                    "IOMMU HW doesnot support remapping of more than 2048 irqs per device function"
                )

            # Validate pci_device input
            if (
                self.pci_device is None
                or self.pci_device not in pci.get_pci_addresses()
            ):
                self.cancel(
                    "Please provide full pci address of a valid pci device on system"
                )

            # Check whether device has MSIX capability
            if not pci.check_msix_capability(self.pci_device):
                self.cancel(f"{self.pci_device} doesnot have msix capability")

            # Check device for "count" number of interrupt/s support
            if not pci.device_supports_irqs(self.pci_device, self.count):
                self.cancel(
                    f"lspci:{self.pci_device} does not support atleast {self.count} interrupts"
                )

            # Load vfio-pci driver
            self.log.info(
                "%s", linux_modules.configure_module("vfio-pci", "CONFIG_VFIO_PCI")
            )

            # Attach PCI device to vfio-pci driver
            pci.attach_driver(self.pci_device, "vfio-pci")
            self.log.info("Attached vfio-pci driver to %s device", self.pci_device)

        except Exception as e:  # pylint: disable=broad-except
            self.cancel(f"{e}")

        self.get_vfio_ioctls()

    def get_vfio_ioctls(self):
        """
        Get VFIO IOCTLS
        """
        try:
            path = os.path.dirname(os.path.realpath(__file__))
            os.chdir(f"{path}/interrupt.py.data/")
            cmd = "gcc get_vfio_ioctls.c -o get_vfio_ioctls"
            process.run(cmd, shell=True, sudo=True)
            output = (
                process.run("./get_vfio_ioctls", shell=True, sudo=True)
                .stdout_text.strip()
                .split("\n")
            )
            for i in output:
                self.vfio_ioctls[f"{i.split()[0]}"] = int(f"{i.split()[1]}")
        except Exception as e:  # pylint: disable=broad-except
            self.cancel(f"Not able to get required vfio IOCTLS. Reason: {e}")
        finally:
            os.chdir(f"{path}")

    def test_allocate_interrupts(self):
        """
        Request and validate interrupt/s allocation and remapping support for PCI device.
        """
        try:
            # Open VFIO container
            self.container_fd = vfio.get_vfio_container_fd()

            # Validate VFIO container support
            vfio.check_vfio_container(
                self.container_fd,
                self.vfio_ioctls["VFIO_GET_API_VERSION"],
                self.vfio_ioctls["VFIO_API_VERSION"],
                self.vfio_ioctls["VFIO_CHECK_EXTENSION"],
                self.vfio_ioctls["VFIO_TYPE1_IOMMU"],
            )

            # Get IOMMU group file descriptor
            self.group_fd = vfio.get_iommu_group_fd(
                self.pci_device,
                self.vfio_ioctls["VFIO_GROUP_GET_STATUS"],
                self.vfio_ioctls["VFIO_GROUP_FLAGS_VIABLE"],
            )

            # Attach the IOMMU group to the VFIO container
            vfio.attach_group_to_container(
                self.group_fd,
                self.container_fd,
                self.vfio_ioctls["VFIO_GROUP_SET_CONTAINER"],
            )
            self.log.info("Attached PCI device's IOMMU group to the VFIO container")

            # Set VFIO IOMMU of type 1
            ioctl(
                self.container_fd,
                self.vfio_ioctls["VFIO_SET_IOMMU"],
                self.vfio_ioctls["VFIO_TYPE1_IOMMU"],
            )

            # Get device file descriptor
            self.device_fd = vfio.get_device_fd(
                self.pci_device,
                self.group_fd,
                self.vfio_ioctls["VFIO_GROUP_GET_DEVICE_FD"],
            )

            # Validate if input PCI device is capable of 2k interrupts via VFIO_DEVICE_GET_IRQ_INFO
            if not vfio.vfio_device_supports_irq(
                self.device_fd,
                self.vfio_ioctls["VFIO_PCI_MSIX_IRQ_INDEX"],
                self.vfio_ioctls["VFIO_DEVICE_GET_IRQ_INFO"],
                self.count,
            ):
                self.cancel(
                    f"ioctls:{self.pci_device} doesnot support atleast {self.count} interrupts"
                )

        except Exception as e:  # pylint: disable=broad-except
            self.cancel(f"{e}")

        # Request for "count" no. of interrupt allocation for input PCI device
        for i in range(self.count):
            argsz = struct.calcsize("IIIIIi")
            flags = (
                self.vfio_ioctls["VFIO_IRQ_SET_DATA_EVENTFD"]
                | self.vfio_ioctls["VFIO_IRQ_SET_ACTION_TRIGGER"]
            )
            index = self.vfio_ioctls["VFIO_PCI_MSIX_IRQ_INDEX"]
            efd = os.eventfd(0, os.EFD_NONBLOCK)
            nirq = 1
            irq_set = struct.pack("IIIIIi", argsz, flags, index, i, nirq, efd)
            try:
                ioctl(self.device_fd, self.vfio_ioctls["VFIO_DEVICE_SET_IRQS"], irq_set)
            except IOError as e:
                if e.errno == errno.ENOSPC:
                    self.cancel("Kernel doesnot support 2k interrupt remapping feature")
                else:
                    self.fail(
                        f"Failed to allocate {self.count} irqs. Able to allocate upto {i} irqs"
                    )
            finally:
                os.close(efd)

    def tearDown(self):
        """
        Restore PCI device state on test completion
        """
        try:
            if self.device_fd is not None:
                # Reset VFIO PCI device
                ioctl(self.device_fd, self.vfio_ioctls["VFIO_DEVICE_RESET"])

                # Close device file descriptor
                os.close(self.device_fd)

            # Unset container for pci device
            if self.group_fd is not None and self.container_fd is not None:
                vfio.detach_group_from_container(
                    self.group_fd,
                    self.container_fd,
                    self.vfio_ioctls["VFIO_GROUP_UNSET_CONTAINER"],
                )

            # Close PCI device's IOMMU group and container file discriptor
            if self.group_fd is not None:
                os.close(self.group_fd)

            if self.container_fd is not None:
                os.close(self.container_fd)

            # Attach device back to original driver
            if self.pci_device and self.pci_device in pci.get_pci_addresses():
                if self.initial_driver is None:
                    cur_driver = pci.get_driver(self.pci_device)
                    if cur_driver is not None:
                        pci.unbind(cur_driver, self.pci_device)
                else:
                    pci.attach_driver(self.pci_device, self.initial_driver)
        except Exception as e:  # pylint: disable=broad-except
            self.fail(f"TearDown failed: Reason {e}")
