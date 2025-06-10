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
# Copyright: 2022 Advanced Micro Devices, Inc.
# Author: Dheeraj Kumar Srivastava <dheerajkumar.srivastava@amd.com>

"""
Various combination of unbind, bind, change iommu group domain type, reset
and rescan is used to form sub-tests that test and exercise iommu code.
"""

import os
from avocado import Test
from avocado.utils import process
from avocado.utils import pci, genio
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils import wait


def change_domain_check(dom, pci_addr, def_dom):
    """
    Check if the domain changed successfully to "dom" for "pci_addr"

    :param dom: domain type
    :param def_dom: default domain of pci address (pci_addr)
    :param pci_addr: full pci address including domain (0000:03:00.0)
    return: bool
    """
    output = genio.read_one_line(
            f"/sys/bus/pci/devices/{pci_addr}/iommu_group/type")
    out = output.rsplit(None, 1)[-1]
    if (dom not in ("auto", out)) or (dom == "auto" and out != def_dom):
        return False
    return True


# TODO: Need to push this to avocado utils later
def reset_check(pci_addr):
    """
    Check if reset for "pci_addr" is successful

    :param pci_addr: full pci address including domain (0000:03:00.0)
    return: bool
    """
    cmd = f"lspci -vvs {pci_addr}"
    output = process.run(cmd, ignore_status=True, shell=True).stdout_text
    if output != "":
        return False
    return True


# TODO: Need to push this to avocado utils later
def rescan_check(pci_addr):
    """
    Check if rescan for pci_addr is successful

    :param pci_addr: full pci address including domain (0000:03:00.0)
    return: bool
    """
    cmd = f"lspci -vvs {pci_addr}"
    output = process.run(cmd, ignore_status=True, shell=True).stdout_text
    if output == "":
        return False
    return True


class IommuTest(Test):

    """
    Various combination of unbind, bind, change iommu group domain type,
    reset and rescan is used to form sub-tests that test and exercise iommu
    code.

    :param device: full pci address including domain (0000:03:00.0)
    """

    def setUp(self):
        """
        Setup the device
        """
        self.pci_devices = self.params.get('pci_devices', default=None)
        self.count = int(self.params.get('count', default=1))
        self.domains = ["DMA", "DMA-FQ", "identity", "auto"]
        self.dmesg_grep = self.params.get('dmesg_grep', default='')
        if not self.pci_devices:
            self.cancel("No pci device given")
        smm = SoftwareManager()
        if not smm.check_installed("pciutils") and not smm.install("pciutils"):
            self.cancel("pciutils package not found and installing failed")

        # Check the number of devices in iommu-group for pci device passed.
        for pci_addr in self.pci_devices.split(" "):

            # Check if device input is valid
            cmd = f"lspci -s {pci_addr}"
            out = process.run(cmd, ignore_status=True, shell=True).stdout_text
            if not out:
                self.cancel(f"{pci_addr} not found on the system")

            driver = pci.get_driver(pci_addr)
            if driver is None:
                self.cancel("Device passed is not bound to any driver")

            if not os.path.exists(f'/sys/bus/pci/drivers/{driver}/{pci_addr}/'
                                  'iommu_group/devices/'):
                self.cancel("System does not have iommu enabled")

            lst = os.listdir(f'/sys/bus/pci/drivers/{driver}/{pci_addr}/'
                             'iommu_group/devices/')
            if len(lst) != 1:
                self.cancel(f"{pci_addr} belongs to iommu group having more "
                            "than one device but system does not support "
                            "domain type change for such device")

        cmd = "dmesg -T --level=alert,crit,err,warn > dmesg_initial.txt"
        process.run(cmd, ignore_status=True, shell=True, sudo=True)

    # TODO: Need to push this to avocado utils later
    def unbind(self, driver, pci_addr):
        """
        Unbind the device

        :param driver: driver of the pci address (pci_addr)
        :param pci_addr: full pci address including domain (0000:03:00.0)
        return: None
        """
        genio.write_file(f'/sys/bus/pci/drivers/{driver}/unbind', pci_addr)
        self.log.info(os.listdir(f'/sys/bus/pci/drivers/{driver}'))
        if wait.wait_for(lambda: os.path.exists(f"/sys/bus/pci/drivers/\
{driver}/{pci_addr}"), timeout=5):
            self.fail(f'Not able to unbind {pci_addr} from {driver}')
        else:
            self.log.info("successfully unbinded %s", pci_addr)

    def change_domain(self, dom, def_dom, pci_addr):
        """
        Change the domain of device to dom

        :param dom: domain type
        :param def_dom: default domain of pci address (pci_addr)
        :param pci_addr: full pci address including domain (0000:03:00.0)
        return: None
        """
        genio.write_file(f'/sys/bus/pci/devices/{pci_addr}/iommu_group/type',
                         dom)
        if not wait.wait_for(lambda: change_domain_check(dom,
                             pci_addr, def_dom), timeout=5):
            self.fail(f'Domain type change failed for {pci_addr}')
        else:
            self.log.info("successfully changed iommu group domain to %s", dom)

    # TODO: Need to push this to avocado utils later
    def bind(self, driver, pci_addr):
        """
        Bind the device to driver

        :param driver: driver of the pci address (pci_addr)
        :param pci_addr: full pci address including domain (0000:03:00.0)
        return: None
        """
        genio.write_file(f"/sys/bus/pci/drivers/{driver}/bind", pci_addr)
        self.log.info(os.listdir(f'/sys/bus/pci/drivers/{driver}'))
        if not wait.wait_for(lambda: os.path.exists(f"/sys/bus/pci/drivers/\
{driver}/{pci_addr}"), timeout=5):
            self.fail(f'Not able to bind {pci_addr} to {driver}')
        else:
            self.log.info("successfully binded %s", pci_addr)

    # TODO: Need to push this to avocado utils later
    def reset(self, pci_addr):
        """
        Remove the device

        :param pci_addr: full pci address including domain (0000:03:00.0)
        return: None
        """
        genio.write_file(f'/sys/bus/pci/devices/{pci_addr}/remove', '1')
        if not wait.wait_for(lambda: reset_check(pci_addr), timeout=5):
            self.fail(f'Unsuccessful to remove {pci_addr}')
        else:
            self.log.info("successfully removed the device %s", pci_addr)

    # TODO: Need to push this to avocado utils later
    def rescan(self, pci_addr):
        """
        Rescan the system

        :param pci_addr: full pci address including domain (0000:03:00.0)
        return: None
        """
        genio.write_file('/sys/bus/pci/rescan', '1')
        if not wait.wait_for(lambda: rescan_check(pci_addr), timeout=5):
            self.fail(f'Unsuccessful to rescan for {pci_addr}')
        else:
            self.log.info("successfully rescanned for the device %s", pci_addr)

    def get_params(self, pci_addr):
        """
        Get device parameter-driver, group, default domain(def_dom)

        :param pci_addr: full pci address including domain (0000:03:00.0)
        return: driver (driver of pci address (pci_addr)),
                def_dom (default domain of pci address (pci_addr))
        """
        driver = pci.get_driver(pci_addr)

        def_dom = None
        output = genio.read_one_line(
                f"/sys/bus/pci/drivers/{driver}/{pci_addr}/iommu_group/type")
        if output:
            def_dom = output.rsplit(None, 1)[-1]
        else:
            self.fail(f"Not able to get default domain of {pci_addr}")
        return driver, def_dom

    def check(self, def_dom, pci_addr, driver):
        """
        Check if the PCI device is in default domain

        :param def_dom: default domain of pci address (pci_addr)
        :param pci_addr: full pci address including domain (0000:03:00.0)
        :param driver: driver of the pci address (pci_addr)
        return: None
        """
        output = genio.read_one_line(
                f"/sys/bus/pci/devices/{pci_addr}/iommu_group/type")
        out = output.rsplit(None, 1)[-1]
        if out != def_dom:
            self.unbind(driver, pci_addr)
            self.change_domain(def_dom, def_dom, pci_addr)
            self.bind(driver, pci_addr)
            self.fail(f'{pci_addr} is not in default domain')
        else:
            self.log.info("Device is in default domain")

    def test_unbind_bind(self):
        """
        Test device for unbind and bind
        """
        for pci_addr in self.pci_devices.split(" "):
            driver, _ = self.get_params(pci_addr)
            self.log.info("PCI_ID = %s", pci_addr)
            # unbinding the driver
            self.unbind(driver, pci_addr)
            # binding the driver
            self.bind(driver, pci_addr)
        self.check_dmesg()

    def test_unbind_changedomain_bind(self):
        """
        Test device for unbind, change domain of device and bind
        """
        for pci_addr in self.pci_devices.split(" "):
            driver, def_dom = self.get_params(pci_addr)
            self.log.info("PCI_ID = %s", pci_addr)
            self.domains.remove(def_dom)
            self.domains.insert(0, def_dom)
            for j in range(len(self.domains)-1):
                pivot_dom = self.domains[j]
                i = j + 1
                while i < len(self.domains):
                    # unbinding the driver
                    self.unbind(driver, pci_addr)
                    # Changing domain of iommu group
                    self.change_domain(self.domains[i], def_dom, pci_addr)
                    # binding the driver
                    self.bind(driver, pci_addr)
                    # unbinding the driver
                    self.unbind(driver, pci_addr)
                    # Changing domain of iommu group
                    self.change_domain(pivot_dom, def_dom, pci_addr)
                    if i == len(self.domains)-1:
                        self.change_domain(self.domains[j+1], def_dom,
                                           pci_addr)
                    # binding the driver
                    self.bind(driver, pci_addr)
                    i = i + 1
            # check the device for default state
            self.check(def_dom, pci_addr, driver)
        self.check_dmesg()

    def test_unbind_changedomain_ntimes_bind(self):
        """
        Test device for unbind, change domain of group(n times) and bind
        """
        for pci_addr in self.pci_devices.split(" "):
            driver, def_dom = self.get_params(pci_addr)
            for _ in range(self.count):
                self.log.info("iteration:%s for PCI_ID = %s", _, pci_addr)
                self.domains.remove(def_dom)
                self.domains.insert(0, def_dom)
                for j in range(len(self.domains)-1):
                    pivot_dom = self.domains[j]
                    i = j + 1
                    while i < len(self.domains):
                        # unbinding the driver
                        self.unbind(driver, pci_addr)
                        # Changing domain type of iommu group
                        self.change_domain(self.domains[i], def_dom, pci_addr)
                        # binding the driver
                        self.bind(driver, pci_addr)
                        # unbinding the driver
                        self.unbind(driver, pci_addr)
                        # Changing domain type of iommu group
                        self.change_domain(pivot_dom, def_dom, pci_addr)
                        if i == len(self.domains)-1:
                            self.change_domain(self.domains[j+1], def_dom,
                                               pci_addr)
                        # binding the driver
                        self.bind(driver, pci_addr)
                        i = i + 1
            # check the device for default state
            self.check(def_dom, pci_addr, driver)
        self.check_dmesg()

    def test_unbind_bind_rescan(self):
        """
        Test device for unbind, bind, rescan
        """
        for pci_addr in self.pci_devices.split(" "):
            driver, def_dom = self.get_params(pci_addr)
            self.log.info("PCI_ID = %s", pci_addr)
            # unbinding the driver
            self.unbind(driver, pci_addr)
            # binding the driver
            self.bind(driver, pci_addr)
            # rescan
            self.rescan(pci_addr)
            # check the device for default state
            self.check(def_dom, pci_addr, driver)
        self.check_dmesg()

    def test_unbind_changedomain_bind_rescan(self):
        """
        Test device for unbind, change domain of group, bind and rescan
        """
        for pci_addr in self.pci_devices.split(" "):
            driver, def_dom = self.get_params(pci_addr)
            self.log.info("PCI_ID = %s", pci_addr)
            self.domains.remove(def_dom)
            self.domains.insert(0, def_dom)
            for j in range(len(self.domains)-1):
                pivot_dom = self.domains[j]
                i = j + 1
                while i < len(self.domains):
                    # unbinding the driver
                    self.unbind(driver, pci_addr)
                    # Changing domain type of iommu group
                    self.change_domain(self.domains[i], def_dom, pci_addr)
                    # binding the driver
                    self.bind(driver, pci_addr)
                    # rescan
                    self.rescan(pci_addr)
                    # (second) unbinding the driver
                    self.unbind(driver, pci_addr)
                    # Changing domain type of iommu group
                    self.change_domain(pivot_dom, def_dom, pci_addr)
                    if i == len(self.domains)-1:
                        self.change_domain(self.domains[j+1], def_dom,
                                           pci_addr)
                    # binding the driver
                    self.bind(driver, pci_addr)
                    i = i + 1
            # check the device for default state
            self.check(def_dom, pci_addr, driver)
        self.check_dmesg()

    def test_reset_rescan(self):
        """
        Test device for reset and rescan
        """
        for pci_addr in self.pci_devices.split(" "):
            driver, def_dom = self.get_params(pci_addr)
            self.log.info("PCI_ID = %s", pci_addr)
            # reset/rescan
            self.reset(pci_addr)
            self.rescan(pci_addr)
            # check the device for default state
            self.check(def_dom, pci_addr, driver)
        self.check_dmesg()

    def check_dmesg(self):
        """
        Checks for any error or failure messages in dmesg after test
        """

        cmd = "dmesg -T --level=alert,crit,err,warn > dmesg_final.txt"
        process.run(cmd, ignore_status=True, shell=True, sudo=True)

        cmd = "diff dmesg_final.txt dmesg_initial.txt"
        if self.dmesg_grep != '':
            cmd = f"{cmd} | grep -i -e '{self.dmesg_grep}'"
        dmesg_diff = process.run(cmd, ignore_status=True, shell=True, sudo=True).stdout_text
        if dmesg_diff != '':
            self.whiteboard = f"{dmesg_diff}"
            self.fail("Running test logged warn,err,alert,crit logs in dmesg. "
                      "Please refer whiteboard of the test result")

        # Clean temprorary files created
        cmd = "rm dmesg_final.txt dmesg_initial.txt"
        process.run(cmd, ignore_status=True, shell=True, sudo=True)
