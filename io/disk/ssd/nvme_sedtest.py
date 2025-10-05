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
# Copyright: 2025 IBM
# Author: Maram.Srimannarayana.Murthy <msmurthy@linux.ibm.com>

"""
NVM-Express user space tooling for Linux, which handles NVMe devices.
This Suite tests NVME SED functionality.
"""

from avocado import Test
from avocado.utils import disk
from avocado.utils import nvme
from avocado.utils.software_manager.manager import SoftwareManager


class NVMeSEDTest(Test):

    """
    NVM-Express user space tooling for Linux, which handles NVMe devices.

    :param device: Name of the nvme device
    :param namespace: Namespace of the device
    """

    def setUp(self):
        """
        Build 'nvme-cli' and setup the device.
        """
        smm = SoftwareManager()
        if not smm.check_installed("nvme-cli") and not \
                smm.install("nvme-cli"):
            self.cancel('nvme-cli is needed for the test to be run')
        self.namespace = self.params.get("disk", default=None)
        if not self.namespace:
            nvme_node = self.params.get('device', default=None)
            self.shared = False
            subsys = nvme.get_subsystem_using_ctrl_name(nvme_node)
            if not nvme_node:
                self.log.fail("Both disk and device are not provided, Exiting test")
            elif "subsys" in nvme_node:
                nvme_node = nvme.get_controllers_with_subsys(subsys)[0]
            elif nvme_node.startswith("nqn."):
                nvme_node = nvme.get_controllers_with_nqn(nvme_node)[0]
            if len(nvme.get_controllers_with_subsys(subsys)) > 1:
                self.shared = True
                if not nvme.get_current_ns_list(nvme_node, shared_ns=self.shared):
                    nvme_node = nvme.get_alternate_controller_name(nvme_node)[0]
            self.log.info(self.shared)
            self.log.info(nvme.get_current_ns_list(nvme_node, shared_ns=self.shared))
            if nvme.get_current_ns_list(nvme_node, shared_ns=self.shared):
                self.namespace = nvme.get_current_ns_list(nvme_node, shared_ns=self.shared)[0]
            if not self.namespace:
                nvme.create_namespaces(nvme_node, 1, shared_ns=self.shared)
                self.namespace = nvme.get_current_ns_list(nvme_node)[0]
        self.sed_password = self.params.get("sed_password", default=None)
        self.change_sed_password = self.params.get("change_sed_password",
                                                   default=None)

    def lock_unlock(self):
        """
        Perform lock and unlock of nvme drive
        """
        nvme.lock_drive(self.namespace)
        if disk.dd_read_records_device(self.namespace):
            self.log.fail(f"dd read command on {self.namespace} is successful, dd should fail when drive is locked")
        nvme.unlock_drive(self.namespace)
        if not disk.dd_read_records_device(self.namespace):
            self.log.fail(f"dd read command on {self.namespace} is failed, dd should success when drive is unlocked")

    def lock_unlock_with_key(self, password):
        """
        Perform lock and unlock with provided key
        """
        nvme.lock_drive(self.namespace, with_pass_key=password)
        if disk.dd_read_records_device(self.namespace):
            self.log.fail(f"dd read command on {self.namespace} is successful, dd should fail when drive is locked")
        nvme.unlock_drive(self.namespace, with_pass_key=password)
        if not disk.dd_read_records_device(self.namespace):
            self.log.fail(f"dd read command on {self.namespace} is failed, dd should success when drive is unlocked")

    def test_initialize_locking(self):
        """
        Initializes nvme SED drive
        """
        nvme.initialize_sed_locking(self.namespace, self.sed_password)

    def test_changed_password(self):
        """
        Changes SED password
        Performs lock, unlock and revert of nvme disk
        """
        nvme.initialize_sed_locking(self.namespace, self.sed_password)
        nvme.lock_drive(self.namespace)
        nvme.change_sed_password(self.namespace, self.sed_password, self.change_sed_password)
        nvme.unlock_drive(self.namespace)
        nvme.lock_drive(self.namespace, with_pass_key=self.change_sed_password)
        nvme.unlock_drive(self.namespace, with_pass_key=self.change_sed_password)
        nvme.revert_sed_locking(self.namespace, self.change_sed_password)

    def test_changed_password_with_destructive_revert(self):
        """
        Changes SED password
        Performs lock, unlock and destructive revert of nvme disk
        """
        nvme.initialize_sed_locking(self.namespace, self.sed_password)
        self.lock_unlock()
        nvme.change_sed_password(self.namespace, self.sed_password, self.change_sed_password)
        self.lock_unlock_with_key(self.change_sed_password)
        nvme.revert_sed_locking(self.namespace, self.change_sed_password, destructive=True)

    def test_sed_revert(self):
        """
        Reverts SED locking on NVME drive
        """
        nvme.initialize_sed_locking(self.namespace, self.sed_password)
        nvme.revert_sed_locking(self.namespace, self.sed_password)

    def test_lock_unlock(self):
        """
        Check locking and unlocking of nvme disk after SED initialization
        """
        nvme.initialize_sed_locking(self.namespace, self.sed_password)
        self.lock_unlock()
        self.lock_unlock_with_key(self.sed_password)
        nvme.revert_sed_locking(self.namespace, self.sed_password)

    def test_sed_destructive_revert(self):
        """
        Destructive reverts SED locking on NVME drive
        Erases drive data
        """
        nvme.initialize_sed_locking(self.namespace, self.sed_password)
        nvme.lock_drive(self.namespace)
        nvme.revert_sed_locking(self.namespace, self.sed_password, destructive=True)

    def tearDown(self):
        """
        Restore nvme disk with default values
        """
        if nvme.is_drive_locked(self.namespace):
            nvme.unlock_drive(self.namespace, with_pass_key=self.sed_password)
        if nvme.is_lockdown_enabled(self.namespace):
            nvme.revert_sed_locking(self.namespace, self.sed_password)
