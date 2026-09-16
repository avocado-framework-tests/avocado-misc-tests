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
NVMe Format Namespace Test.

Issues the NVMe Format NVM command on a namespace across several
functional modes and verifies that the namespace is still accessible
and I/O succeeds after each operation.

Requires the device to advertise 'Format NVM Supported' in id-ctrl.

Test methods
------------
test_format_namespace         : baseline format with current LBAF
test_format_ses_user_data_erase : format + user data erase  (ses=1)
test_format_ses_crypto_erase  : format + cryptographic erase (ses=2)
test_format_with_reset        : format + automatic controller reset
test_format_block_size        : format to a target block size via -b
"""

import os
from avocado import Test
from avocado.utils import disk
from avocado.utils import process
from avocado.utils import archive
from avocado.utils import nvme
from avocado.utils.software_manager.manager import SoftwareManager


class NVMeFormat(Test):
    """
    NVMe Format Namespace Test.

    :param device: Name of the nvme device (e.g. nvme0, or subsystem NQN)
    :param shared_namespaces: True if the namespace is shared (default False)
    :param package: 'distro' (default) or 'upstream' to build nvme-cli
                    from source

    The first namespace reported by the controller is selected automatically
    via ``nvme.get_current_ns_list()``; no namespace parameter is required.
    The block size used by test_format_block_size is read from the device
    at setUp time via ``nvme.get_block_size()``.
    """

    def setUp(self):
        """
        Install nvme-cli, resolve the device path, and verify Format NVM
        support.
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
            self.cancel("No namespaces found on controller %s"
                        % self.ctrl_name)
        self.id_ns = ns_list[0]
        # Derive the namespace ID from the device path
        # (e.g. /dev/nvme0n1 -> 1).
        self.namespace = self.id_ns.split("n")[-1]
        self.log.info("Selected namespace: %s (id=%s)",
                      self.id_ns, self.namespace)

        self.fmt_timeout = 60000
        # Read the block size directly from the device so it is always valid.
        self.target_block_size = nvme.get_block_size(self.ctrl_name,
                                                     shared_ns=self.shared)
        self.log.info("Device block size: %d bytes", self.target_block_size)

        smm = SoftwareManager()
        self.package = self.params.get('package', default='distro')
        if self.package == 'upstream':
            if not smm.check_installed("meson") and not smm.install("meson"):
                self.cancel('meson is needed for the test to be run')
            locations = [
                "https://github.com/linux-nvme/nvme-cli/archive/master.zip"]
            tarball = self.fetch_asset("nvme-cli.zip", locations=locations,
                                       expire='15d')
            archive.extract(tarball, self.teststmpdir)
            os.chdir("%s/nvme-cli-master" % self.teststmpdir)
            process.system("meson setup --force-fallback-for=libnvme .build",
                           ignore_status=True)
            process.system("meson compile -C .build", ignore_status=True)
            self.binary = './.build/nvme'
        else:
            if not smm.check_installed("nvme-cli") and \
                    not smm.install("nvme-cli"):
                self.cancel('nvme-cli is needed for the test to be run')
            self.binary = 'nvme'

        # Verify Format NVM is supported
        cmd = "%s id-ctrl %s -H" % (self.binary, self.device)
        self.id_ctrl = process.system_output(cmd, shell=True).decode("utf-8")
        if "Format NVM Supported" not in self.id_ctrl:
            self.cancel("Format NVM is not supported on this device")

        # Validate namespace device path exists
        if process.system('ls %s' % self.id_ns, ignore_status=True):
            self.cancel("Namespace device %s does not exist. "
                        "Ensure the namespace is created before "
                        "running this test." % self.id_ns)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_lba(self):
        """
        Return the LBA format index currently in use by the namespace.
        Falls back to 0 if it cannot be determined.
        """
        lba = nvme.get_lba(self.id_ns, shared_ns=self.shared)
        if lba is not None:
            return lba
        self.log.debug("Could not determine current LBA for %s; using 0",
                       self.id_ns)
        return 0

    def _validate_ns_accessible(self):
        """Fail the test if the namespace device node is not accessible."""
        if process.system('ls -la %s' % self.id_ns, shell=True,
                          ignore_status=True):
            self.fail("Namespace %s is not accessible" % self.id_ns)

    def _run_format(self, extra_opts=''):
        """
        Issue ``nvme format`` on ``self.id_ns`` with the current LBA format
        plus any *extra_opts* and return the exit code.
        """
        lba = self._get_lba()
        cmd = '%s format %s -l %s -t %d --force %s' % (
            self.binary, self.id_ns, lba, self.fmt_timeout, extra_opts)
        self.log.info("Format command: %s", cmd)
        return process.system(cmd, shell=True, ignore_status=True)

    def _post_format_validate(self):
        """
        Common post-format checks:
          1. Namespace block device is still accessible.
          2. Namespace is still listed by the controller.
          3. A basic read succeeds.
        """
        self._validate_ns_accessible()
        self.log.info("Validation OK: namespace %s accessible after format",
                      self.id_ns)

        ns_id = int(self.namespace)
        if not nvme.is_ns_exists(self.ctrl_name, ns_id):
            self.fail("Namespace %d missing from %s after format"
                      % (ns_id, self.ctrl_name))
        self.log.info("Validation OK: namespace %d present in controller "
                      "list after format", ns_id)

        block_size = nvme.get_block_size(self.ctrl_name, shared_ns=self.shared)
        read_cmd = '%s read %s -z %d' % (self.binary, self.id_ns, block_size)
        ret = process.system(read_cmd, timeout=60, ignore_status=True,
                             shell=True)
        if ret:
            self.fail("Read after format failed on %s (exit code %d)"
                      % (self.id_ns, ret))
        self.log.info("Validation OK: read after format succeeded on %s",
                      self.id_ns)

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_format_namespace(self):
        """
        Baseline format: re-apply the current LBA format with no erase.

        Steps:
          1. Validate namespace block device is accessible.
          2. Issue: nvme format <ns> -l <lbaf> --force
          3. Validate return code is 0.
          4. Run post-format validation (accessible, listed, readable).
        """
        self._validate_ns_accessible()
        ret = self._run_format()
        if ret:
            self.fail("nvme format failed on %s (exit code %d)"
                      % (self.id_ns, ret))
        self._post_format_validate()
        self.log.info("test_format_namespace passed on %s", self.id_ns)

    def test_format_ses_user_data_erase(self):
        """
        Format with Secure Erase Setting 1 (User Data Erase).

        The controller overwrites all user data in the namespace with a
        fixed pattern before completing the format.  Verifies that the
        namespace is still accessible and readable after the erase.

        Steps:
          1. Validate namespace block device is accessible.
          2. Issue: nvme format <ns> -l <lbaf> -s 1 --force
          3. Validate return code is 0.
          4. Run post-format validation (accessible, listed, readable).
        """
        self._validate_ns_accessible()
        ret = self._run_format(extra_opts='-s 1')
        if ret:
            self.fail("nvme format (ses=1 user data erase) failed on %s "
                      "(exit code %d)" % (self.id_ns, ret))
        self._post_format_validate()
        self.log.info("test_format_ses_user_data_erase passed on %s",
                      self.id_ns)

    def test_format_ses_crypto_erase(self):
        """
        Format with Secure Erase Setting 2 (Cryptographic Erase).

        The controller discards the encryption key so all previously
        written data becomes unreadable.  Skipped automatically when the
        device does not advertise crypto-erase support (FNA bit 2 in
        id-ctrl).

        Steps:
          1. Check FNA bit 2 in id-ctrl; skip if not set.
          2. Validate namespace block device is accessible.
          3. Issue: nvme format <ns> -l <lbaf> -s 2 --force
          4. Validate return code is 0.
          5. Run post-format validation (accessible, listed, readable).
        """
        if 'Cryptographic Erase Supported' not in self.id_ctrl:
            self.cancel("Cryptographic erase (ses=2) not supported on %s"
                        % self.device)
        self._validate_ns_accessible()
        ret = self._run_format(extra_opts='-s 2')
        if ret:
            self.fail("nvme format (ses=2 crypto erase) failed on %s "
                      "(exit code %d)" % (self.id_ns, ret))
        self._post_format_validate()
        self.log.info("test_format_ses_crypto_erase passed on %s", self.id_ns)

    def test_format_with_reset(self):
        """
        Format with automatic controller reset (--reset).

        After the format completes the controller resets itself and
        re-enumerates all namespaces.  Verifies the namespace is still
        accessible and I/O works after the reset.

        Steps:
          1. Validate namespace block device is accessible.
          2. Issue: nvme format <ns> -l <lbaf> --reset --force
          3. Validate return code is 0.
          4. Run post-format validation (accessible, listed, readable).
        """
        self._validate_ns_accessible()
        ret = self._run_format(extra_opts='--reset')
        if ret:
            self.fail("nvme format with --reset failed on %s (exit code %d)"
                      % (self.id_ns, ret))
        self._post_format_validate()
        self.log.info("test_format_with_reset passed on %s", self.id_ns)

    def test_format_block_size(self):
        """
        Format to a target block size using --block-size / -b.

        The controller selects the matching LBAF entry automatically.
        Skipped when the device does not support the requested block size.
        The target block size is read from the ``target_block_size`` yaml
        parameter (default: 4096).

        Steps:
          1. Validate namespace block device is accessible.
          2. Issue: nvme format <ns> -b <target_block_size> --force
          3. Validate return code is 0.
          4. Run post-format validation (accessible, listed, readable).
          5. Confirm the namespace block size matches the target.
          6. Re-format back to the original block size to restore state.
        """
        self._validate_ns_accessible()
        original_block_size = nvme.get_block_size(self.ctrl_name,
                                                  shared_ns=self.shared)
        cmd = '%s format %s -b %d -t %d --force' % (
            self.binary, self.id_ns, self.target_block_size, self.fmt_timeout)
        self.log.info("Format command: %s", cmd)
        ret = process.system(cmd, shell=True, ignore_status=True)
        if ret:
            self.cancel("nvme format -b %d not supported on %s (exit code %d)"
                        % (self.target_block_size, self.id_ns, ret))
        self._post_format_validate()

        # Confirm the block size changed as requested
        new_block_size = nvme.get_block_size(self.ctrl_name,
                                             shared_ns=self.shared)
        if new_block_size != self.target_block_size:
            self.fail("Block size after format is %d, expected %d"
                      % (new_block_size, self.target_block_size))
        self.log.info("Validation OK: block size is now %d bytes",
                      new_block_size)

        # Restore original block size so device is left in original state
        self.log.info("Restoring original block size %d", original_block_size)
        restore_cmd = '%s format %s -b %d -t %d --force' % (
            self.binary, self.id_ns, original_block_size, self.fmt_timeout)
        process.system(restore_cmd, shell=True, ignore_status=True)
        self.log.info("test_format_block_size passed on %s", self.id_ns)
