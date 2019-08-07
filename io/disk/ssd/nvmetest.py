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
from avocado.utils import archive
from avocado.utils import build
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
        if process.system(cmd, ignore_status=True):
            self.cancel("%s does not exist" % self.device)

        self.package = self.params.get('package', default='distro')
        if self.package == 'upstream':
            locations = ["https://github.com/linux-nvme/nvme-cli/archive/"
                         "master.zip"]
            tarball = self.fetch_asset("nvme-cli.zip", locations=locations,
                                       expire='15d')
            archive.extract(tarball, self.teststmpdir)
            os.chdir("%s/nvme-cli-master" % self.teststmpdir)
            process.system("./NVME-VERSION-GEN", ignore_status=True)
            build.make(".")
            self.binary = './nvme'
        else:
            smm = SoftwareManager()
            if not smm.check_installed("nvme-cli") and not \
                    smm.install("nvme-cli"):
                self.cancel('nvme-cli is needed for the test to be run')
            self.binary = 'nvme'
        self.format_size = self.get_block_size()
        self.namespace = self.params.get('namespace', default='1')
        self.id_ns = "%sn%s" % (self.device, self.namespace)
        self.firmware_url = self.params.get('firmware_url', default='')
        if 'firmware_upgrade' in str(self.name) and not self.firmware_url:
            self.cancel("firmware url not given")

        cmd = "%s id-ctrl %s -H" % (self.binary, self.device)
        self.id_ctrl = process.system_output(cmd, shell=True).decode("utf-8")
        cmd = "%s show-regs %s -H" % (self.binary, self.device)
        regs = process.system_output(cmd, shell=True).decode("utf-8")

        test_dic = {'compare': 'Compare', 'formatnamespace': 'Format NVM',
                    'dsm': 'Data Set Management',
                    'writezeroes': 'Write Zeroes',
                    'firmware_upgrade': 'FW Commit and Download',
                    'writeuncorrectable': 'Write Uncorrectable',
                    'subsystemreset': 'NVM Subsystem Reset'}
        for key, value in list(test_dic.items()):
            if key in str(self.name):
                if "%s Supported" % value not in self.id_ctrl:
                    self.cancel("%s is not supported" % value)
                # NVM Subsystem Reset Supported  (NSSRS): No
                if "%s Supported   (NSSRS): No" % value in regs:
                    self.cancel("%s is not supported" % value)

    @staticmethod
    def run_cmd_return_output_list(cmd):
        """
        Runs the command, returns the output as a list, each of which is a line
        in the output.
        """
        return process.system_output(cmd, ignore_status=True,
                                     shell=True).decode("utf-8").splitlines()

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
        cmd = "%s fw-log %s" % (self.binary, self.device)
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
        cmd = "%s list-ns %s" % (self.binary, self.device)
        namespaces = []
        for line in self.run_cmd_return_output_list(cmd):
            namespaces.append(int(line.split()[1].split(']')[0]) + 1)
        return namespaces

    def list_ns(self):
        """
        Prints the namespaces list command, and does a rescan as part of it
        """
        cmd = "%s ns-rescan %s" % (self.binary, self.device)
        process.system(cmd, shell=True, ignore_status=True)
        cmd = "%s list" % self.binary
        return process.system_output(cmd, shell=True,
                                     ignore_status=True).decode("utf-8")

    def get_ns_controller(self):
        """
        Returns the nvme controller id
        """
        cmd = "%s list-ctrl %s" % (self.binary, self.device)
        output = process.system_output(cmd, shell=True,
                                       ignore_status=True).decode("utf-8")
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
            cmd = "%s id-ns %sn%s" % (self.binary, self.device, namespace)
            for line in self.run_cmd_return_output_list(cmd):
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
            cmd = "%s id-ns %sn%s" % (self.binary, self.device, namespace)
            for line in self.run_cmd_return_output_list(cmd):
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
        cmd = "%s delete-ns %s -n %s" % (self.binary, self.device, namespace)
        process.system(cmd, shell=True, ignore_status=True)

    def create_full_capacity_ns(self):
        """
        Creates one namespace with full capacity
        """
        max_ns_blocks = self.get_total_capacity() // self.get_block_size()
        self.create_one_ns('1', max_ns_blocks, self.get_ns_controller())

    def create_max_ns(self):
        """
        Creates maximum number of namespaces, with equal capacity
        """
        max_ns_blocks = self.get_total_capacity() // self.get_block_size()
        max_ns_blocks_considered = 60 * max_ns_blocks / 100
        per_ns_blocks = max_ns_blocks_considered // self.get_max_ns_count()
        ns_controller = self.get_ns_controller()
        for ns_id in range(1, self.get_max_ns_count() + 1):
            self.create_one_ns(str(ns_id), per_ns_blocks, ns_controller)

    def create_one_ns(self, ns_id, blocksize, controller):
        """
        Creates one namespace, with the specified id, block size, controller
        """
        cmd = "%s create-ns %s --nsze=%s --ncap=%s --flbas=0 -dps=0" % (
            self.binary, self.device, blocksize, blocksize)
        process.system(cmd, shell=True, ignore_status=True)
        cmd = "%s attach-ns %s --namespace-id=%s -controllers=%s" % (
            self.binary, self.device, ns_id, controller)
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
        passed_commits = []
        failed = False
        d_cmd = "%s fw-download %s --fw=%s" % (self.binary, self.device,
                                               fw_file_path)
        for slot in range(1, self.get_firmware_slots() + 1):
            if not self.firmware_slot_write_supported(slot):
                continue
            passed_actions = []
            for action in range(0, 4):
                # Downloading new FW to the device for each slot
                if process.system(d_cmd, shell=True, ignore_status=True):
                    continue
                cmd = "%s fw-commit %s -s %d -a %d" % (self.binary,
                                                       self.device, slot,
                                                       action)
                if process.system(cmd, shell=True, ignore_status=True):
                    failed = True
                else:
                    passed_actions.append(action)
            passed_commits.append(passed_actions)

        # Reset device if not already taken care
        reset_needed = False
        for commit in passed_commits:
            if 3 not in commit:
                reset_needed = True
        if reset_needed:
            if self.reset_controller_sysfs():
                self.fail("Controller reset after FW update failed")
        if failed:
            self.log.debug(passed_commits)
            self.fail("Passed only for the above slot actions")

        # Getting the current FW details after updating
        self.get_firmware_log()
        if fw_version != self.get_firmware_version():
            self.log.warn("New Firmware not reflecting after updating")

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
        cmd = '%s format %s -l %s' % (self.binary, self.id_ns, self.get_lba())
        process.run(cmd, shell=True)

    def testread(self):
        """
        Reads from the namespace on the device.
        """
        cmd = '%s read %s -z %d -t' % (self.binary, self.id_ns,
                                       self.format_size)
        if process.system(cmd, timeout=300, ignore_status=True, shell=True):
            self.fail("Read failed")

    def testwrite(self):
        """
        Write to the namespace on the device.
        """
        cmd = 'echo 1|%s write %s -z %d -t' % (self.binary, self.id_ns,
                                               self.format_size)
        if process.system(cmd, timeout=300, ignore_status=True, shell=True):
            self.fail("Write failed")

    def testcompare(self):
        """
        Compares data written on the device with given data.
        """
        self.testwrite()
        cmd = 'echo 1|%s compare %s -z %d' % (self.binary, self.id_ns,
                                              self.format_size)
        if process.system(cmd, timeout=300, ignore_status=True, shell=True):
            self.fail("Compare failed")

    def testflush(self):
        """
        flush data on controller.
        """
        cmd = '%s flush %s' % (self.binary, self.id_ns)
        if process.system(cmd, ignore_status=True, shell=True):
            self.fail("Flush failed")

    def testwritezeroes(self):
        """
        Write zeroes command to the device.
        """
        cmd = '%s write-zeroes %s' % (self.binary, self.id_ns)
        if process.system(cmd, ignore_status=True, shell=True):
            self.fail("Writing Zeroes failed")

    def testwriteuncorrectable(self):
        """
        Write uncorrectable command to the device.
        """
        cmd = '%s write-uncor %s' % (self.binary, self.id_ns)
        if process.system(cmd, ignore_status=True, shell=True):
            self.fail("Writing Uncorrectable failed")

    def testdsm(self):
        """
        The Dataset Management command test.
        """
        cmd = '%s dsm %s -a 1 -b 1 -s 1 -d -w -r' % (self.binary,
                                                     self.id_ns)
        if process.system(cmd, ignore_status=True, shell=True):
            self.fail("Subsystem reset failed")

    def testreset(self):
        """
        resets the controller.
        """
        cmd = '%s reset %s' % (self.binary, self.device)
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
        cmd = '%s subsystem-reset %s' % (self.binary, self.device)
        if process.system(cmd, ignore_status=True, shell=True):
            self.fail("Subsystem reset failed")


if __name__ == "__main__":
    main()
