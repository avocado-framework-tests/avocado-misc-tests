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
NVM-Express user space tooling for Linux, which handles NVMe devices.
This Suite creates and formats a namespace, reads and writes on it
using nvme cli.
"""

import os
from avocado import Test
from avocado import main
from avocado.utils import process
from avocado.utils import download
from avocado.utils.software_manager import SoftwareManager


class NVMeTest(Test):

    """
    NVM-Express user space tooling for Linux, which handles NVMe devices.

    :param device: Name of the nvme device
    :param namespace: Namespace of the device
    """

    def setUp(self):
        """
        Build 'nvme-cli' and setup the device.
        """
        self.device = self.params.get('device', default='nvme0')
        self.device = "/dev/%s" % self.device
        cmd = 'ls %s' % self.device
        if process.system(cmd, ignore_status=True) is not 0:
            self.cancel("%s does not exist" % self.device)
        smm = SoftwareManager()
        if not smm.check_installed("nvme-cli") and not \
                smm.install("nvme-cli"):
            self.cancel('nvme-cli is needed for the test to be run')
        self.format_size = self.get_block_size()
        self.namespace = self.params.get('namespace', default='1')
        self.id_ns = "%sn%s" % (self.device, self.namespace)
        self.firmware_url = self.params.get('firmware_url', default='')
        if 'firmware_upgrade' in str(self.name) and not self.firmware_url:
            self.cancel("firmware url not gien")

        cmd = "nvme id-ctrl %s -H" % self.device
        self.id_ctrl = process.system_output(cmd, shell=True)
        cmd = "nvme show-regs %s -H" % self.device
        regs = process.system_output(cmd, shell=True)

        test_dic = {'compare': 'Compare', 'formatnamespace': 'Format NVM',
                    'dsm': 'Data Set Management',
                    'writezeroes': 'Write Zeroes',
                    'firmware_upgrade': 'FW Commit and Download',
                    'writeuncorrectable': 'Write Uncorrectable',
                    'subsystemreset': 'NVM Subsystem Reset'}
        for key, value in test_dic.iteritems():
            if key in str(self.name):
                if "%s Supported" % value not in self.id_ctrl:
                    self.cancel("%s is not supported" % value)
                # NVM Subsystem Reset Supported  (NSSRS): No
                if "%s Supported   (NSSRS): No" % value in regs:
                    self.cancel("%s is not supported" % value)

    def get_id_ctrl_prop(self, prop):
        """
        :param prop: property whose value is requested

        Returns the property value from 'nvme id-ctrl' command
        """
        for line in self.id_ctrl.splitlines():
            if line.startswith(prop):
                return line.split()[-1]
        return ''

    def get_firmware_version(self):
        """
        Returns the firmware verison.
        """
        return self.get_id_ctrl_prop('fr')

    def get_firmware_log(self):
        """
        Returns the firmware log.
        """
        cmd = "nvme fw-log %s" % self.device
        process.system(cmd, shell=True, ignore_status=True)

    def get_firmware_slots(self):
        """
        Returns number of firmware slots
        """
        for line in self.id_ctrl.splitlines():
            if "Firmware Slots" in line:
                return int(line.split()[2].split('x')[-1])
        return 0

    def firmware_slot_write_supported(self, slot_num):
        """
        Returns False if firmware slot num is read only.
        Returns True otherwise.
        """
        for line in self.id_ctrl.splitlines():
            if "Firmware Slot %d Read-Only" % slot_num in line:
                return False
        return True

    def reset_controller_sysfs(self):
        """
        Resets the controller via sysfs.
        """
        cmd = "echo 1 > /sys/class/nvme/%s/reset_controller" \
            % self.device.split("/")[-1]
        return process.system(cmd, shell=True, ignore_status=True)

    def get_max_ns_count(self):
        """
        Returns the maximum number of namespaces supported
        """
        output = self.get_id_ctrl_prop('nn')
        if output:
            return int(output)
        return 1

    def get_total_capacity(self):
        """
        Returns the total capacity of the nvme controller.
        If not found, return defaults to 0.
        """
        output = self.get_id_ctrl_prop('tnvmcap')
        if output:
            return int(output)
        return 0

    def ns_list(self):
        """
        Returns the list of namespaces in the nvme controller
        """
        cmd = "nvme list-ns %s" % self.device
        namespaces = []
        for line in process.system_output(cmd, shell=True,
                                          ignore_status=True).splitlines():
            namespaces.append(int(line.split()[1].split(']')[0]) + 1)
        return namespaces

    def list_ns(self):
        """
        Prints the namespaces list command, and does a rescan as part of it
        """
        cmd = "nvme ns-rescan %s" % self.device
        process.system(cmd, shell=True, ignore_status=True)
        cmd = "nvme list"
        return process.system_output(cmd, shell=True, ignore_status=True)

    def get_ns_controller(self):
        """
        Returns the nvme controller id
        """
        cmd = "nvme list-ctrl %s" % self.device
        output = process.system_output(cmd, shell=True, ignore_status=True)
        if output:
            return output.split(':')[-1]
        return ""

    def get_lba(self):
        """
        Returns LBA of the namespace.
        If not found, return defaults to 0.
        """
        namespace = self.ns_list()
        if namespace:
            namespace = namespace[0]
            cmd = "nvme id-ns %sn%s" % (self.device, namespace)
            for line in process.system_output(cmd, shell=True,
                                              ignore_status=True).splitlines():
                if 'in use' in line:
                    return int(line.split()[1])
        return '0'

    def get_block_size(self):
        """
        Returns the block size of the namespace.
        If not found, return defaults to 4k.
        """
        namespace = self.ns_list()
        if namespace:
            namespace = namespace[0]
            cmd = "nvme id-ns %sn%s" % (self.device, namespace)
            for line in process.system_output(cmd, shell=True,
                                              ignore_status=True).splitlines():
                if 'in use' in line:
                    return pow(2, int(line.split()[4].split(':')[-1]))
        return 4096

    def delete_all_ns(self):
        """
        Deletes all namespaces in the controller
        """
        for namespace in self.ns_list():
            self.delete_ns(namespace)

    def delete_ns(self, namespace):
        """
        :param ns: namespace id to be deleted

        Deletes the specified namespace on the controller
        """
        cmd = "nvme delete-ns %s -n %s" % (self.device, namespace)
        process.system(cmd, shell=True, ignore_status=True)

    def create_full_capacity_ns(self):
        """
        Creates one namespace with full capacity
        """
        max_ns_blocks = self.get_total_capacity() / self.get_block_size()
        self.create_one_ns('1', max_ns_blocks, self.get_ns_controller())

    def create_max_ns(self):
        """
        Creates maximum number of namespaces, with equal capacity
        """
        max_ns_blocks = self.get_total_capacity() / self.get_block_size()
        max_ns_blocks_considered = 60 * max_ns_blocks / 100
        per_ns_blocks = max_ns_blocks_considered / self.get_max_ns_count()
        ns_controller = self.get_ns_controller()
        for ns_id in range(1, self.get_max_ns_count() + 1):
            self.create_one_ns(str(ns_id), per_ns_blocks, ns_controller)

    def create_one_ns(self, ns_id, blocksize, controller):
        """
        Creates one namespace, with the specified id, block size, controller
        """
        cmd = "nvme create-ns %s --nsze=%s --ncap=%s --flbas=0 -dps=0" % (
            self.device, blocksize, blocksize)
        process.system(cmd, shell=True, ignore_status=True)
        cmd = "nvme attach-ns %s --namespace-id=%s -controllers=%s" % (
            self.device, ns_id, controller)
        process.system(cmd, shell=True, ignore_status=True)

    def test_firmware_upgrade(self):
        """
        Updates firmware of the device.
        """
        fw_file = self.firmware_url.split('/')[-1]
        fw_version = fw_file.split('.')[0]
        fw_file_path = download.get_file(self.firmware_url,
                                         os.path.join(self.teststmpdir,
                                                      fw_file))
        # Getting the current FW details
        self.log.debug("Current FW: %s", self.get_firmware_version())
        self.get_firmware_log()

        # Activating new FW
        for i in range(1, self.get_firmware_slots() + 1):
            if not self.firmware_slot_write_supported(i):
                continue
            # Downloading new FW to the device for each slot
            d_cmd = "nvme fw-download %s --fw=%s" % (self.device, fw_file_path)
            if process.system(d_cmd, shell=True, ignore_status=True):
                self.fail("Failed to download firmware to the device")
            cmd = "nvme fw-activate %s -a 0 -s %d" % (self.device, i)
            if process.system(cmd, shell=True, ignore_status=True):
                self.fail("Failed to write firmware on slot %d" % i)
            if i == self.get_firmware_slots():
                # Downloading new FW to the device for each action
                if process.system(d_cmd, shell=True, ignore_status=True):
                    self.fail("Failed to download firmware to the device")
                cmd = "nvme fw-activate %s -a 3 -s %d" % (self.device, i)
                if process.system(cmd, shell=True, ignore_status=True):
                    self.fail("Failed to activate firmware on slot %d" % i)

        if self.reset_controller_sysfs():
            self.fail("Controller reset after FW update failed")

        # Getting the current FW details after updating
        self.get_firmware_log()
        if fw_version != self.get_firmware_version():
            self.fail("New Firmware not reflecting after updating")

    def test_create_max_ns(self):
        """
        Test to create maximum number of namespaces
        """
        self.delete_all_ns()
        self.create_max_ns()
        self.list_ns()

    def test_create_full_capacity_ns(self):
        """
        Test to create namespace with full capacity
        """
        self.delete_all_ns()
        self.create_full_capacity_ns()
        self.list_ns()

    def testformatnamespace(self):
        """
        Formats the namespace on the device.
        """
        cmd = 'nvme format %s -l %s' % (self.id_ns, self.get_lba())
        process.run(cmd, shell=True)

    def testread(self):
        """
        Reads from the namespace on the device.
        """
        cmd = 'nvme read %s -z %d -t' % (self.id_ns, self.format_size)
        if process.system(cmd, timeout=300, ignore_status=True, shell=True):
            self.fail("Read failed")

    def testwrite(self):
        """
        Write to the namespace on the device.
        """
        cmd = 'echo 1|nvme write %s -z %d -t' % (self.id_ns, self.format_size)
        if process.system(cmd, timeout=300, ignore_status=True, shell=True):
            self.fail("Write failed")

    def testcompare(self):
        """
        Compares data written on the device with given data.
        """
        self.testwrite()
        cmd = 'echo 1|nvme compare %s -z %d' % (self.id_ns, self.format_size)
        if process.system(cmd, timeout=300, ignore_status=True, shell=True):
            self.fail("Compare failed")

    def testflush(self):
        """
        flush data on controller.
        """
        cmd = 'nvme flush %s' % self.id_ns
        if process.system(cmd, ignore_status=True, shell=True):
            self.fail("Flush failed")

    def testwritezeroes(self):
        """
        Write zeroes command to the device.
        """
        cmd = 'nvme write-zeroes %s' % self.id_ns
        if process.system(cmd, ignore_status=True, shell=True):
            self.fail("Writing Zeroes failed")

    def testwriteuncorrectable(self):
        """
        Write uncorrectable command to the device.
        """
        cmd = 'nvme write-uncor %s' % self.id_ns
        if process.system(cmd, ignore_status=True, shell=True):
            self.fail("Writing Uncorrectable failed")

    def testdsm(self):
        """
        The Dataset Management command test.
        """
        cmd = 'nvme dsm %s -a 1 -b 1 -s 1 -d -w -r' % self.id_ns
        if process.system(cmd, ignore_status=True, shell=True):
            self.fail("Subsystem reset failed")

    def testreset(self):
        """
        resets the controller.
        """
        cmd = 'nvme reset %s' % self.device
        if process.system(cmd, ignore_status=True, shell=True):
            self.fail("Reset failed")

    def testreset_sysfs(self):
        """
        resets the controller via sysfs.
        """
        if self.reset_controller_sysfs():
            self.fail("Reset failed")

    def testsubsystemreset(self):
        """
        resets the controller subsystem.
        """
        cmd = 'nvme subsystem-reset %s' % self.device
        if process.system(cmd, ignore_status=True, shell=True):
            self.fail("Subsystem reset failed")


if __name__ == "__main__":
    main()
