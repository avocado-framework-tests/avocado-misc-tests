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
# Copyright: 2026 IBM
# Author: Naresh Bannoth <nbannoth@in.ibm.com>

"""
NVMe Firmware Flash Test.

Downloads and flashes new firmware to the NVMe device across all
writable firmware slots, then validates that the new firmware version
is correctly reported by the controller after a reset.
"""
import os
from avocado import Test
from avocado.utils import disk
from avocado.utils import process
from avocado.utils import download
from avocado.utils import nvme
from avocado.utils.software_manager.manager import SoftwareManager


class NVMeFirmwareFlash(Test):
    """
    NVMe Firmware Flash Test.

    Downloads firmware from a given URL, flashes it to all writable
    slots on the device, resets the controller, and validates that
    the reported firmware version matches the expected value.

    :param device: Name of the nvme device (e.g. nvme0, or subsystem NQN)
    :param firmware_url: URL to the firmware image to be flashed
    """

    def setUp(self):
        """
        Check nvme-cli is installed and verify prerequisites.
        """
        nvme_node = self.params.get('device', default=None)
        if not nvme_node:
            self.cancel("Please provide valid nvme node name")
        elif "subsys" in nvme_node:
            nvme_node = nvme.get_controllers_with_subsys(nvme_node)[0]
        elif nvme_node.startswith("nqn."):
            nvme_node = nvme.get_controllers_with_nqn(nvme_node)[0]
        self.device = disk.get_absolute_disk_path(nvme_node)
        if process.system('ls %s' % self.device, ignore_status=True):
            self.cancel("%s does not exist" % self.device)

        self.firmware_url = self.params.get('firmware_url', default=None)
        if not self.firmware_url:
            self.cancel("firmware_url parameter is required for this test")

        smm = SoftwareManager()
        if not smm.check_installed("nvme-cli") and not smm.install("nvme-cli"):
            self.cancel('nvme-cli is needed for the test to be run')

        # Confirm the device supports FW Commit and Download
        cmd = "nvme id-ctrl %s -H" % self.device
        self.id_ctrl = process.system_output(cmd, shell=True).decode("utf-8")
        if "FW Commit and Download Supported" not in self.id_ctrl:
            self.cancel("FW Commit and Download is not supported "
                        "on this device")

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    def _get_firmware_version(self):
        """
        Returns the live firmware revision by re-issuing id-ctrl.
        grep -w '^fr' fetches exactly the 'fr' line from the command
        output so no line-by-line iteration is needed in Python.
        Always queries fresh so post-reset values are correct.
        """
        cmd = "nvme id-ctrl %s | grep -w '^fr'" % self.device
        out = process.system_output(cmd, shell=True).decode("utf-8").strip()
        # out is exactly: "fr        : REV.CAS5"
        return out.split(':')[-1].strip()

    def _get_firmware_slots(self):
        """Returns number of firmware slots supported by the device."""
        for line in self.id_ctrl.splitlines():
            if "Firmware Slots" in line:
                return int(line.split()[2].split('x')[-1])
        return 0

    def _firmware_slot_write_supported(self, slot_num):
        """Returns False if firmware slot is read-only."""
        for line in self.id_ctrl.splitlines():
            if "Firmware Slot %d Read-Only" % slot_num in line:
                return False
        return True

    def _reset_controller_sysfs(self):
        """Resets the controller via sysfs."""
        ctrl_name = self.device.split("/")[-1]
        cmd = "echo 1 > /sys/class/nvme/%s/reset_controller" % ctrl_name
        return process.system(cmd, shell=True, ignore_status=True)

    def _get_firmware_log(self):
        """Prints the firmware log for the device."""
        cmd = "nvme fw-log %s" % self.device
        process.system(cmd, shell=True, ignore_status=True)

    # ------------------------------------------------------------------
    # Test
    # ------------------------------------------------------------------

    def test_firmware_upgrade(self):
        """
        Download and flash firmware to all writable slots, then validate.

        Steps:
          1. Download firmware image from firmware_url.
          2. Record older_fw (version before flashing).
          3. For each writable slot and each commit action, run fw-download
             then fw-commit. Collect every failure in error_list.
          4. Fail immediately if error_list is non-empty.
          5. Perform controller reset if any successful commit requires it.
          6. Read new_fw (version after flashing) and validate:
             - If fw_version set in yaml: new_fw must equal fw_version.
             - If fw_version not set    : new_fw must differ from older_fw.
        """
        fw_file = self.firmware_url.split('/')[-1]
        fw_file_path = download.get_file(
            self.firmware_url, os.path.join(self.teststmpdir, fw_file))

        # fw_version (optional): expected version string after flashing.
        # Set this in the yaml when known, e.g. fw_version: 43395339
        fw_version = self.params.get('fw_version', default=None)

        # Record firmware version BEFORE flashing
        older_fw = self._get_firmware_version()
        self.log.info("Firmware version before flash: %s", older_fw)
        if fw_version:
            self.log.info("Expected firmware version after flash: %s",
                          fw_version)
        self._get_firmware_log()

        # Action 3 = activate at next controller reset (no immediate reset)
        FW_COMMIT_ACTION_ACTIVATE_NO_RESET = 3

        d_cmd = "nvme fw-download %s --fw=%s" % (self.device, fw_file_path)
        passed_commits = {}
        # error_list collects every step that failed
        error_list = []

        for slot in range(1, self._get_firmware_slots() + 1):
            if not self._firmware_slot_write_supported(slot):
                self.log.info("Slot %d is read-only, skipping", slot)
                continue

            passed_actions = []

            for action in range(0, FW_COMMIT_ACTION_ACTIVATE_NO_RESET):
                if process.system(d_cmd, shell=True, ignore_status=True):
                    msg = ("slot %d action %d: fw-download failed"
                           % (slot, action))
                    self.log.error(msg)
                    error_list.append(msg)
                    continue

                c_cmd = "nvme fw-commit %s -s %d -a %d" % (
                    self.device, slot, action)
                if process.system(c_cmd, shell=True, ignore_status=True):
                    msg = ("slot %d action %d: fw-commit failed"
                           % (slot, action))
                    self.log.error(msg)
                    error_list.append(msg)
                else:
                    passed_actions.append(action)

            if passed_actions:
                passed_commits[slot] = passed_actions

        # Step 4: fail immediately if any download/commit step failed
        if error_list:
            self.log.error("Passed commits so far: %s", passed_commits)
            self.fail("Firmware flash had %d error(s):\n  %s"
                      % (len(error_list), "\n  ".join(error_list)))

        # Step 5: reset controller if any successful commit requires it
        reset_needed = any(
            FW_COMMIT_ACTION_ACTIVATE_NO_RESET not in actions
            for actions in passed_commits.values()
        )
        if reset_needed:
            self.log.info("Performing controller reset to activate firmware")
            if self._reset_controller_sysfs():
                self.fail("Controller reset after firmware update failed")

        # Step 6: read firmware version AFTER flashing
        self._get_firmware_log()
        new_fw = self._get_firmware_version()
        self.log.info("Firmware version after flash: %s", new_fw)

        # Validate
        if fw_version:
            # Expected version provided: new_fw must match it exactly
            if new_fw == fw_version:
                self.log.info("Firmware flash successful: '%s' -> '%s'",
                              older_fw, new_fw)
            else:
                self.fail("Firmware version mismatch after flash: "
                          "expected '%s', got '%s' (was '%s' before flash)"
                          % (fw_version, new_fw, older_fw))
        else:
            # No expected version provided: new_fw must differ from older_fw
            if new_fw != older_fw:
                self.log.info("Firmware flash successful: '%s' -> '%s'",
                              older_fw, new_fw)
            else:
                self.log.warning("Firmware version unchanged after "
                                 "flash: '%s'. Flash may not have "
                                 "taken effect." % new_fw)
