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
    """

    def setUp(self):
        """
        Build 'nvme-cli' and setup the device.
        """
        self.device = self.params.get('device', default='/dev/nvme0')
        cmd = 'ls %s' % self.device
        if process.system(cmd, ignore_status=True) is not 0:
            self.skip("%s does not exist" % self.device)
        smm = SoftwareManager()
        if not smm.check_installed("nvme-cli") and not \
                smm.install("nvme-cli"):
            self.skip('nvme-cli is needed for the test to be run')
        self.id_ns = self.create_namespace()
        self.log.info(self.id_ns)
        cmd = "nvme id-ns %s | grep 'in use' | awk '{print $5}' | \
            awk -F':' '{print $NF}'" % self.id_ns
        self.format_size = process.system_output(cmd, shell=True).strip('\n')
        self.format_size = pow(2, int(self.format_size))
        cmd = "nvme id-ns %s | grep 'in use' | awk '{print $2}'" % self.id_ns
        self.lba = process.system_output(cmd, shell=True).strip('\n')
        self.firmware_url = self.params.get('firmware_url', default='')
        if 'firmware_upgrade' in str(self.name) and not self.firmware_url:
            self.skip("firmware url not gien")

    def get_firmware_version(self):
        """
        Returns the firmware verison.
        """
        cmd = "nvme list | grep %s" % self.device
        return process.system_output(cmd, shell=True,
                                     ignore_status=True).split()[-1]

    def get_firmware_log(self):
        """
        Returns the firmware log.
        """
        cmd = "nvme fw-log %s" % self.device
        return process.system_output(cmd, shell=True, ignore_status=True)

    def reset_controller_sysfs(self):
        """
        Resets the controller via sysfs.
        """
        cmd = "echo 1 > /sys/class/nvme/%s/reset_controller" \
            % self.device.split("/")[-1]
        return process.system(cmd, shell=True, ignore_status=True)

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
        self.log.debug("Current FW: %s" % self.get_firmware_version())
        fw_log = self.get_firmware_log()

        # Downloading new FW to the device
        cmd = "nvme fw-download %s --fw=%s" % (self.device, fw_file_path)
        if process.system(cmd, shell=True, ignore_status=True):
            self.fail("Failed to download firmware to the device")

        # Acvitating new FW on the device
        for line in fw_log.splitlines():
            if "frs" in line:
                s_num = line.split()[0].split("s")[-1]
                cmd = "nvme fw-activate %s -a 1 -s %s" % (self.device, s_num)
                if process.system(cmd, shell=True, ignore_status=True):
                    self.fail("Failed to activate firmware for %s" % s_num)

        if self.reset_controller_sysfs():
            self.fail("Controller reset after FW update failed")

        # Getting the current FW details after updating
        self.get_firmware_log()
        if fw_version != self.get_firmware_version():
            self.fail("New Firmware not reflecting after updating")

    def create_namespace(self):
        """
        Creates namespace on the device.
        """
        cmd = "nvme show-regs %s | grep version | awk '{print $NF}'" \
            % self.device
        if int(process.system_output(cmd, shell=True).strip('\n')) < 10200:
            return self.device + 'n1'
        cmd = 'nvme create-ns %s' % self.device
        process.run(cmd, shell=True)
        # TODO: retrieve the created namespace for nvme spec 1.2 and above
        return self.device + 'n1'

    def delete_namespace(self):
        """
        Deletes namespace on the device.
        """
        cmd = "nvme show-regs %s | grep version | awk '{print $NF}'" \
            % self.device
        if int(process.system_output(cmd, shell=True).strip('\n')) < 10200:
            return
        cmd = 'nvme delete-ns %s' % self.device
        process.run(cmd, shell=True)

    def testformatnamespace(self):
        """
        Formats the namespace on the device.
        """
        cmd = 'nvme format %s -l %s' % (self.id_ns, self.lba)
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
        cmd = 'nvme flush %s -n 1' % self.device
        if process.system(cmd, ignore_status=True, shell=True):
            self.fail("Flush failed")

    def testwritezeroes(self):
        """
        Write zeroes command to the device.
        """
        cmd = 'nvme write-zeroes %s -n 1' % self.device
        if process.system(cmd, ignore_status=True, shell=True):
            self.fail("Writing Zeroes failed")

    def testwriteuncorrectable(self):
        """
        Write uncorrectable command to the device.
        """
        cmd = 'nvme write-uncor %s -n 1' % self.device
        if process.system(cmd, ignore_status=True, shell=True):
            self.fail("Writing Uncorrectable failed")

    def testdsm(self):
        """
        The Dataset Management command test.
        """
        cmd = 'nvme dsm %s -n 1 -a 1 -b 1 -s 1 -d -w -r' % self.device
        if process.system(cmd, ignore_status=True, shell=True):
            self.fail("Subsystem reset failed")

    def testreset(self):
        """
        resets the controller.
        """
        cmd = 'nvme reset %s' % self.device
        if process.system(cmd, ignore_status=True, shell=True):
            self.fail("Reset failed")

    def testsubsystemreset(self):
        """
        resets the controller subsystem.
        """
        cmd = 'nvme subsystem-reset %s' % self.device
        if process.system(cmd, ignore_status=True, shell=True):
            self.fail("Subsystem reset failed")

    def testreset_sysfs(self):
        """
        resets the controller via sysfs.
        """
        if self.reset_controller_sysfs():
            self.fail("Reset failed")

    def tearDown(self):
        """
        Clean up
        """
        self.delete_namespace()


if __name__ == "__main__":
    main()
