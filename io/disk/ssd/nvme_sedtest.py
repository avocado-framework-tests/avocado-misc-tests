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
import pexpect
import re
import sys
import time

from avocado import Test
from avocado.utils import nvme
from avocado.utils import process
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
        self.change_sed_password_to = self.params.get("change_sed_password", default=None)

    def get_nvme_sed_discover_parameters(self, namespace):
        """
        Fetches values from nvme SED discover command
        :param namespace: NVMe namespace path
        :rtype: dictionary
        """
        cmd = f"nvme sed discover {namespace}"
        data = process.run(cmd, ignore_status=True, sudo=True, shell=True).stdout_text
        pattern = r"\tLocking Supported\s*:\s*(.*)\n\tLocking Feature Enabled\s*:\s*(.*)\n\tLocked\s*:\s*(.*)"
        match = re.search(pattern, data, re.MULTILINE)
        if match:
            locking_features = {
                "Locking Supported": match.group(1).strip(),
                "Locking Feature Enabled": match.group(2).strip(),
                "Locked": match.group(3).strip(),
            }
            return locking_features
        return {}

    def is_lockdown_supported(self, namespace):
        """
        Fetches information based on namespace
        Checks if SED locking is supported for the given namespace
        :param namespace: NVMe namespace path
        :rtype: boolean
        """
        lockdown_attr = self.get_nvme_sed_discover_parameters(namespace)
        return lockdown_attr.get("Locking Supported").lower() == "yes"

    def is_lockdown_enabled(self, namespace):
        """
        Fetches information based on namespace
        Checks if SED locking feature is enabled for the given namespace
        :param namespace: NVMe namespace path
        :rtype: boolean
        """
        lockdown_attr = self.get_nvme_sed_discover_parameters(namespace)
        return lockdown_attr.get("Locking Feature Enabled").lower() == "yes"

    def is_drive_locked(self, namespace):
        """
        Fetches information based on namespace
        Checks if the drive is currently locked for the given namespace
        :param namespace: NVMe namespace path
        :rtype: boolean
        """
        lockdown_attr = self.get_nvme_sed_discover_parameters(namespace)
        return lockdown_attr.get("Locked").lower() == "yes"

    def dd_read_records_device(self, disk, read_records="1", out_file="/tmp/data"):
        """
        Reads mentioned number of blocks from device to destination
        :param disk: disk absolute path
        :param read_records: Numbers of blocks to read from disk
        :param out_file: Destination file
        :rtype: boolean
        """
        cmd = f"dd count={read_records} if={disk} of={out_file}"
        return not process.system(cmd, ignore_status=True, sudo=True)

    def initialize_sed_locking(self, namespace, password):
        """
        Enables and initializes SED feature on nvme disk
        :param namespace: NVMe namespace path
        :param password: SED password
        """
        if not self.is_lockdown_supported(namespace):
            raise nvme.NvmeException(f"SED initialize not supported on {namespace}")
        if self.is_lockdown_enabled(namespace):
            raise nvme.NvmeException(
                f"nvme drive {namespace} locking is enabled, can't initialize it"
            )
        self.pexpect_cmd_execution(
            f"nvme sed initialize {namespace}",
            [("New Password:", password), ("Re-enter New Password:", password)],
        )
        if not self.is_lockdown_enabled(namespace):
            raise nvme.NvmeException(f"Failed to initialize nvme disk {namespace}")

    def revert_sed_locking(self, namespace, password, destructive=False):
        """
        Reverts SED locking state to factory defaults
        :param namespace: NVMe namespace path
        :param password: Current SED password
        :raises: NvmeException if revert is not supported, drive is not initialized,
                drive is locked, or revert operation fails
        """
        if not self.is_lockdown_supported(namespace):
            raise nvme.NvmeException(f"Revert not supported on {namespace}")
        if not self.is_lockdown_enabled(namespace):
            raise nvme.NvmeException(
                f"nvme drive {namespace} locking is not enabled, can't revert it"
            )
        if destructive:
            self.pexpect_cmd_execution(
                f"nvme sed revert -e {namespace}",
                [
                    ("Destructive revert erases drive data. Continue (y/n)?", "y"),
                    ("Are you sure (y/n)?", "y"),
                    ("Password:", password),
                ],
            )
        else:
            self.pexpect_cmd_execution(f"nvme sed revert {namespace}", [("Password:", password)])
        if self.is_lockdown_enabled(namespace):
            raise nvme.NvmeException(f"Failed to revert {namespace}")

    def unlock_drive(self, namespace, with_pass_key=""):
        """
        Unlocks SED locked driver
        :param namespace: NVMe namespace path
        :param with_pass_key: Password for unlocking (if empty, no password prompt)
        """
        if not self.is_drive_locked(namespace):
            raise nvme.NvmeException(f"Drive is not locked, unlock failed for {namespace}")
        cmd = f"nvme sed unlock {namespace}"
        if with_pass_key:
            cmd = f"{cmd} -k"
            self.pexpect_cmd_execution(cmd, [("Password:", with_pass_key)])
        elif process.system(cmd, shell=True, ignore_status=True):
            raise nvme.NvmeException(f"namespace {namespace} unlock failed")
        if self.is_drive_locked(namespace):
            raise nvme.NvmeException(f"Unlock failed for {namespace}")

    def lock_drive(self, namespace, with_pass_key=""):
        """
        SED lock enables on nvme drive
        :param namespace: NVMe namespace path
        :param with_pass_key: Password for locking (if empty, no password prompt)
        """
        if self.is_drive_locked(namespace):
            raise nvme.NvmeException(f"namespace {namespace} already in locked state")
        cmd = f"nvme sed lock {namespace}"
        if with_pass_key:
            cmd = f"{cmd} -k"
            self.pexpect_cmd_execution(cmd, [("Password:", with_pass_key)])
        elif process.system(cmd, shell=True, ignore_status=True):
            raise nvme.NvmeException(f"namespace {namespace} lock failed")
        if not self.is_drive_locked(namespace):
            raise nvme.NvmeException(f"locking failed for {namespace}")

    def change_sed_password(self, namespace, pwd1, pwd2):
        """
        Changes the SED password for the specified namespace
        :param namespace: NVMe namespace path
        :param pwd1: Current SED password
        :param pwd2: New SED password
        :raises: NvmeException if password change is not supported or drive is not initialized
        """
        if not self.is_lockdown_supported(namespace):
            raise nvme.NvmeException(f"Change password not supported on {namespace}")
        if not self.is_lockdown_enabled(namespace):
            raise nvme.NvmeException(
                f"nvme drive {namespace} is not initialized, can't change password"
            )
        self.pexpect_cmd_execution(
            f"nvme sed password {namespace}",
            [
                ("Password:", pwd1),
                ("New Password:", pwd2),
                ("Re-enter New Password:", pwd2),
            ],
        )

    def pexpect_cmd_execution(self, cmd, list_of_expect_sendline):
        """
        Execute command using pexpect with multiple expect/sendline interactions
        :param cmd: Command to execute
        :param list_of_expect_sendline: List of (expect_pattern, sendline_value) tuples
        :raises: NvmeException on command failures
        """
        try:
            self.log.info("Executing command using pexpect: %s", cmd)
            pexpect_handle = pexpect.spawn(cmd)
            pexpect_handle.log_read = sys.stdout
            for expect, value in list_of_expect_sendline:
                pexpect_handle.expect(expect, timeout=30)
                pexpect_handle.sendline(value)
                self.log.debug("Matched String: %s", pexpect_handle.after.strip())
                self.log.debug("Pexpect output: %s", pexpect_handle.before.strip())
                time.sleep(3)
            pexpect_handle.close()
            self.log.info("%s command executed successfully", cmd)
        except pexpect.exceptions.TIMEOUT as e:
            self.log.error("Command timed out: %s", cmd)
            raise nvme.NvmeException(f"Command timeout: {cmd}") from e
        except pexpect.exceptions.EOF as e:
            self.log.error("Command ended unexpectedly: %s", cmd)
            raise nvme.NvmeException(f"Command failed unexpectedly: {cmd}") from e

    def lock_unlock(self):
        """
        Perform lock and unlock of nvme drive
        """
        self.lock_drive(self.namespace)
        if self.dd_read_records_device(self.namespace):
            self.log.fail(f"dd read command on {self.namespace} is successful, dd should fail when drive is locked")
        self.unlock_drive(self.namespace)
        if not self.dd_read_records_device(self.namespace):
            self.log.fail(f"dd read command on {self.namespace} is failed, dd should success when drive is unlocked")

    def lock_unlock_with_key(self, password):
        """
        Perform lock and unlock with provided key
        """
        self.lock_drive(self.namespace, with_pass_key=password)
        if self.dd_read_records_device(self.namespace):
            self.log.fail(f"dd read command on {self.namespace} is successful, dd should fail when drive is locked")
        self.unlock_drive(self.namespace, with_pass_key=password)
        if not self.dd_read_records_device(self.namespace):
            self.log.fail(f"dd read command on {self.namespace} is failed, dd should success when drive is unlocked")

    def test_initialize_locking(self):
        """
        Initializes nvme SED drive
        """
        self.initialize_sed_locking(self.namespace, self.sed_password)

    def test_changed_password(self):
        """
        Changes SED password
        Performs lock, unlock and revert of nvme disk
        """
        self.initialize_sed_locking(self.namespace, self.sed_password)
        self.lock_drive(self.namespace)
        self.change_sed_password(self.namespace, self.sed_password, self.change_sed_password_to)
        self.unlock_drive(self.namespace)
        self.lock_drive(self.namespace, with_pass_key=self.change_sed_password_to)
        self.unlock_drive(self.namespace, with_pass_key=self.change_sed_password_to)
        self.revert_sed_locking(self.namespace, self.change_sed_password_to)

    def test_changed_password_with_destructive_revert(self):
        """
        Changes SED password
        Performs lock, unlock and destructive revert of nvme disk
        """
        self.initialize_sed_locking(self.namespace, self.sed_password)
        self.lock_unlock()
        self.change_sed_password(self.namespace, self.sed_password, self.change_sed_password_to)
        self.lock_unlock_with_key(self.change_sed_password_to)
        self.revert_sed_locking(self.namespace, self.change_sed_password_to, destructive=True)

    def test_sed_revert(self):
        """
        Reverts SED locking on NVME drive
        """
        self.initialize_sed_locking(self.namespace, self.sed_password)
        self.revert_sed_locking(self.namespace, self.sed_password)

    def test_lock_unlock(self):
        """
        Check locking and unlocking of nvme disk after SED initialization
        """
        self.initialize_sed_locking(self.namespace, self.sed_password)
        self.lock_unlock()
        self.lock_unlock_with_key(self.sed_password)
        self.revert_sed_locking(self.namespace, self.sed_password)

    def test_sed_destructive_revert(self):
        """
        Destructive reverts SED locking on NVME drive
        Erases drive data
        """
        self.initialize_sed_locking(self.namespace, self.sed_password)
        self.lock_drive(self.namespace)
        self.revert_sed_locking(self.namespace, self.sed_password, destructive=True)

    def tearDown(self):
        """
        Restore nvme disk with default values
        """
        if self.is_drive_locked(self.namespace):
            self.unlock_drive(self.namespace, with_pass_key=self.sed_password)
        if self.is_lockdown_enabled(self.namespace):
            self.revert_sed_locking(self.namespace, self.sed_password)
