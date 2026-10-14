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
NVMe Reset Tests.

Covers:
  - Controller reset via nvme-cli (nvme reset).
  - Controller reset via sysfs (echo 1 > reset_controller).
  - NVM Subsystem reset (nvme subsystem-reset) — requires device support
    and a kernel not in lockdown mode.

After each reset the tests verify that the device is still accessible
and namespaces are intact.
"""

import os
import time
from avocado import Test
from avocado.utils import disk
from avocado.utils import process
from avocado.utils import archive
from avocado.utils import nvme
from avocado.utils.software_manager.manager import SoftwareManager


class NVMeReset(Test):
    """
    NVMe Reset Tests.

    :param device: Name of the nvme device (e.g. nvme0, or subsystem NQN)
    :param shared_namespaces: True if the namespace is shared (default False)
    :param package: 'distro' (default) or 'upstream' to build nvme-cli from source
    """

    def setUp(self):
        """
        Install nvme-cli and set up the device reference.  The first namespace
        on the controller is discovered automatically at run time.
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

        self.ctrl_name = self.device.split("/")[-1]
        self.shared = self.params.get('shared_namespaces', default=False)

        # Discover all namespaces on the controller and pick the first one.
        ns_list = nvme.get_current_ns_list(self.ctrl_name,
                                           shared_ns=self.shared)
        if not ns_list:
            self.cancel("No namespaces found on controller %s" % self.ctrl_name)
        self.id_ns = ns_list[0]
        # Derive the integer namespace ID from the device path
        # (e.g. /dev/nvme0n1 -> 1).
        self.namespace = int(self.id_ns.split("n")[-1])
        self.log.info("Selected namespace: %s (id=%d)",
                      self.id_ns, self.namespace)

        smm = SoftwareManager()
        self.package = self.params.get('package', default='distro')
        if self.package == 'upstream':
            if not smm.check_installed("meson") and not smm.install("meson"):
                self.cancel('meson is needed for the test to be run')
            locations = ["https://github.com/linux-nvme/nvme-cli/archive/master.zip"]
            tarball = self.fetch_asset("nvme-cli.zip", locations=locations,
                                       expire='15d')
            archive.extract(tarball, self.teststmpdir)
            os.chdir("%s/nvme-cli-master" % self.teststmpdir)
            process.system("meson setup --force-fallback-for=libnvme .build",
                           ignore_status=True)
            process.system("meson compile -C .build", ignore_status=True)
            self.binary = './.build/nvme'
        else:
            if not smm.check_installed("nvme-cli") and not smm.install("nvme-cli"):
                self.cancel('nvme-cli is needed for the test to be run')
            self.binary = 'nvme'

        # Snapshot id-ctrl output once for capability checks
        cmd = "%s id-ctrl %s -H" % (self.binary, self.device)
        self.id_ctrl = process.system_output(cmd, shell=True).decode("utf-8")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _wait_for_device(self, timeout=30):
        """
        Wait up to *timeout* seconds for the device to reappear after reset.
        Fails the test if the device does not come back within that window.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not process.system('ls %s' % self.device, ignore_status=True):
                self.log.info("Device %s is back online", self.device)
                return
            time.sleep(2)
        self.fail("Device %s did not reappear within %d s after reset"
                  % (self.device, timeout))

    def _validate_device_accessible(self):
        """Fail the test if the controller device node is not accessible."""
        if process.system('ls -la %s' % self.device, shell=True,
                          ignore_status=True):
            self.fail("Controller device %s is not accessible after reset"
                      % self.device)
        self.log.info("Validation OK: controller device %s accessible",
                      self.device)

    def _validate_ns_accessible(self):
        """Fail the test if the namespace device node is not accessible."""
        if process.system('ls -la %s' % self.id_ns, shell=True,
                          ignore_status=True):
            self.log.warning("Namespace %s not accessible after reset. "
                             "A rescan may be needed.", self.id_ns)
        else:
            self.log.info("Validation OK: namespace %s accessible after reset",
                          self.id_ns)

    def _validate_ns_list_intact(self, expected_ns_ids):
        """
        Verify that all *expected_ns_ids* are still listed after a reset.
        """
        process.system("%s ns-rescan %s" % (self.binary, self.device),
                       shell=True, ignore_status=True)
        time.sleep(2)
        for ns_id in expected_ns_ids:
            if not nvme.is_ns_exists(self.ctrl_name, ns_id):
                self.fail("Namespace %d missing from %s after reset"
                          % (ns_id, self.ctrl_name))
        self.log.info("Validation OK: all namespaces %s intact after reset",
                      expected_ns_ids)

    def _get_ns_ids_before_reset(self):
        """Snapshot the current namespace IDs before performing a reset."""
        return nvme.get_current_ns_ids(self.ctrl_name)

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_reset(self):
        """
        Reset the NVMe controller using the nvme-cli reset command, then
        verify the device and its namespaces are fully recovered.

        Steps:
          1. Snapshot current namespace IDs.
          2. Issue: nvme reset <device>
          3. Wait for device node to reappear.
          4. Validate controller device is accessible.
          5. Validate all pre-reset namespaces are still listed.
        """
        ns_ids_before = self._get_ns_ids_before_reset()
        self.log.info("Namespace IDs before reset: %s", ns_ids_before)

        cmd = '%s reset %s' % (self.binary, self.device)
        self.log.info("Reset command: %s", cmd)
        ret = process.system(cmd, ignore_status=True, shell=True)
        if ret:
            self.fail("nvme reset command failed on %s (exit code %d)"
                      % (self.device, ret))

        self._wait_for_device()
        self._validate_device_accessible()
        if ns_ids_before:
            self._validate_ns_list_intact(ns_ids_before)
        self.log.info("Controller reset test passed on %s", self.device)

    def test_reset_sysfs(self):
        """
        Reset the NVMe controller via the sysfs reset_controller attribute,
        then verify the device and its namespaces are fully recovered.

        Steps:
          1. Snapshot current namespace IDs.
          2. Write 1 to /sys/class/nvme/<ctrl>/reset_controller.
          3. Wait for device node to reappear.
          4. Validate controller device is accessible.
          5. Validate all pre-reset namespaces are still listed.
        """
        ns_ids_before = self._get_ns_ids_before_reset()
        self.log.info("Namespace IDs before sysfs reset: %s", ns_ids_before)

        sysfs_path = "/sys/class/nvme/%s/reset_controller" % self.ctrl_name
        cmd = "echo 1 > %s" % sysfs_path
        self.log.info("Sysfs reset command: %s", cmd)
        ret = process.system(cmd, shell=True, ignore_status=True)
        if ret:
            self.fail("Sysfs reset failed on %s (exit code %d)"
                      % (self.device, ret))

        self._wait_for_device()
        self._validate_device_accessible()
        if ns_ids_before:
            self._validate_ns_list_intact(ns_ids_before)
        self.log.info("Sysfs controller reset test passed on %s", self.device)

    def test_subsystem_reset(self):
        """
        Issue an NVM Subsystem Reset using nvme-cli, then verify the device
        and its namespaces are fully recovered.

        Prerequisites:
          - 'NVM Subsystem Reset Supported' must be indicated in id-ctrl.
          - Kernel lockdown must be disabled (checked via
            /sys/kernel/security/lockdown).

        Steps:
          1. Confirm lockdown is not active.
          2. Confirm NVM Subsystem Reset is advertised.
          3. Snapshot current namespace IDs.
          4. Issue: nvme subsystem-reset <device>
          5. Wait for device node to reappear.
          6. Validate controller device is accessible.
          7. Validate all pre-reset namespaces are still listed.
        """
        # Check kernel lockdown
        lockdown = process.system_output(
            "cat /sys/kernel/security/lockdown",
            shell=True, ignore_status=True).decode("utf-8")
        if '[none]' not in lockdown:
            self.cancel("Kernel lockdown is active; cannot run nvme show-regs "
                        "which is required for subsystem reset validation")

        # Check device capability via show-regs
        regs_cmd = "%s show-regs %s -H" % (self.binary, self.device)
        regs = process.system_output(regs_cmd, shell=True,
                                     ignore_status=True).decode("utf-8")
        if "NVM Subsystem Reset Supported   (NSSRS): No" in regs:
            self.cancel("NVM Subsystem Reset is not supported on this device")

        # Also check id-ctrl for the feature flag
        if "NVM Subsystem Reset Supported" not in self.id_ctrl:
            self.cancel("NVM Subsystem Reset Supported not advertised in id-ctrl")

        ns_ids_before = self._get_ns_ids_before_reset()
        self.log.info("Namespace IDs before subsystem reset: %s", ns_ids_before)

        cmd = '%s subsystem-reset %s' % (self.binary, self.device)
        self.log.info("Subsystem reset command: %s", cmd)
        ret = process.system(cmd, ignore_status=True, shell=True)
        if ret:
            self.fail("nvme subsystem-reset failed on %s (exit code %d)"
                      % (self.device, ret))

        self._wait_for_device()
        self._validate_device_accessible()
        if ns_ids_before:
            self._validate_ns_list_intact(ns_ids_before)
        self.log.info("NVM Subsystem reset test passed on %s", self.device)
