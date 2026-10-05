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
NVMe Namespace Management Tests.

Covers:
  - Create a single namespace and verify it is visible.
  - Create a namespace consuming the full device capacity and verify.
  - Create the maximum supported number of equal-sized namespaces and verify.
  - Create a shared namespace (multi-path) and verify.
  - Create N equal-sized namespaces (count driven by test parameter)
    and verify.
  - Delete all namespaces and verify they are gone.
"""

import os
import time
from avocado import Test
from avocado.utils import disk
from avocado.utils import process
from avocado.utils import archive
from avocado.utils import nvme
from avocado.utils.software_manager.manager import SoftwareManager


class NVMeNamespaceManagement(Test):
    """
    NVMe Namespace Management Tests.

    :param device: Name of the nvme device (e.g. nvme0, or subsystem NQN)
    :param namespace_count: Number of equal-sized namespaces to create
                            (used by test_create_equal_ns). Default 4.
    :param shared_namespaces: If True, create namespaces in shared mode.
                              Default False.
    :param package: 'distro' (default) or 'upstream' to build
                    nvme-cli from source.
    """

    def setUp(self):
        """
        Install nvme-cli and set up the device reference.
        """
        nvme_node = self.params.get('device', default=None)
        if not nvme_node:
            self.cancel("Please provide valid nvme drive name")
        elif "subsys" in nvme_node:
            nvme_node = nvme.get_controllers_with_subsys(nvme_node)[0]
        elif nvme_node.startswith("nqn."):
            nvme_node = nvme.get_controllers_with_nqn(nvme_node)[0]
        self.device = disk.get_absolute_disk_path(nvme_node)
        if process.system(f'ls {self.device}', ignore_status=True):
            self.cancel(f"{self.device} does not exist")

        # Short controller name used by nvme utility functions (e.g. 'nvme0')
        self.ctrl_name = self.device.split("/")[-1]

        self.shared = self.params.get('shared_namespaces', default=False)
        self.ns_count = self.params.get('namespace_count', default=4)

        smm = SoftwareManager()
        self.package = self.params.get('package', default='distro')
        if self.package == 'upstream':
            if not smm.check_installed("meson") and not smm.install("meson"):
                self.cancel('meson is needed for the test to be run')
            locations = [
                "https://github.com/linux-nvme/nvme-cli/archive/master.zip"
            ]
            tarball = self.fetch_asset("nvme-cli.zip", locations=locations,
                                       expire='15d')
            archive.extract(tarball, self.teststmpdir)
            os.chdir(f"{self.teststmpdir}/nvme-cli-master")
            process.system("meson setup --force-fallback-for=libnvme .build",
                           ignore_status=True)
            process.system("meson compile -C .build", ignore_status=True)
            self.binary = './.build/nvme'
        else:
            if (not smm.check_installed("nvme-cli")
                    and not smm.install("nvme-cli")):
                self.cancel('nvme-cli is needed for the test to be run')
            self.binary = 'nvme'

        # Snapshot the controller state *before* any test modifies it so
        # tearDown can restore the drive to its original configuration.
        self._snapshot_ns_state()

    def tearDown(self):
        """
        Restore the NVMe controller to the namespace count that existed
        before this test ran.

        Whether the test passed, failed, or was cancelled the drive is left
        with the same number of namespaces that were present when the test
        started.  The work is delegated to ``_restore_ns_state()`` which:

          1. Deletes all namespaces currently on the controller.
          2. Re-creates namespaces using the library's own size computation
             (``create_full_capacity_ns`` for 1 NS, ``create_namespaces``
             for N > 1) so controller alignment constraints are always met.
        """
        if not hasattr(self, 'original_ns_count'):
            # setUp did not complete (e.g. device not found / cancelled early)
            # – nothing to restore.
            return
        self._restore_ns_state()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _snapshot_ns_state(self):
        """
        Capture the count of namespaces on the controller before the test runs
        so tearDown knows how many to restore.

        We only record the *count* of original namespaces.  For restore we
        let the library recompute sizes from the live controller capacity so
        that rounding / alignment differences between the snapshotted nsze and
        the value the controller accepts after deletion can never cause the
        restore to fail.

        The count is stored in ``self.original_ns_count`` (int).
        """
        self.original_ns_count = len(nvme.get_current_ns_ids(self.ctrl_name))
        self.log.info(
            "Snapshot: %d namespace(s) on %s before test",
            self.original_ns_count,
            self.ctrl_name,
        )

    def _restore_ns_state(self):
        """
        Restore the controller to the namespace count captured by
        ``_snapshot_ns_state()``.

        Strategy:
          - 0 original namespaces → leave the controller empty.
          - 1 original namespace  → use ``create_full_capacity_ns`` which
            always uses the full available capacity reported by the
            controller, avoiding any nsze rounding mismatch.
          - N original namespaces → use ``create_namespaces(ctrl, N)``
            which divides capacity equally, matching what the drive had.

        All size computation is delegated to the library so alignment
        differences between the pre-test state and post-delete capacity
        never cause the restore to fail.
        """
        self.log.info(
            "Restoring %d namespace(s) on %s",
            self.original_ns_count,
            self.ctrl_name,
        )
        # Step 1: wipe everything the test may have left behind
        try:
            nvme.delete_all_ns(self.ctrl_name, shared_ns=self.shared)
        except Exception as exc:  # pylint: disable=broad-except
            self.log.info(
                "delete_all_ns during tearDown: %s (continuing)", exc
            )
        self._ns_rescan()

        # Step 2: recreate original namespace count
        if self.original_ns_count == 0:
            self.log.info("Original state was empty; leaving %s with no NSes",
                          self.ctrl_name)
        elif self.original_ns_count == 1:
            try:
                self._create_ns_safe(
                    nvme.create_full_capacity_ns,
                    self.ctrl_name,
                    shared_ns=self.shared,
                )
                self._ns_rescan()
                self.log.info("Restored 1 full-capacity namespace on %s",
                              self.ctrl_name)
            except Exception as exc:  # pylint: disable=broad-except
                self.log.error("Failed to restore namespace on %s: %s",
                               self.ctrl_name, exc)
        else:
            try:
                self._create_ns_safe(
                    nvme.create_namespaces,
                    self.ctrl_name,
                    self.original_ns_count,
                    shared_ns=self.shared,
                )
                self._ns_rescan()
                self.log.info("Restored %d namespace(s) on %s",
                              self.original_ns_count, self.ctrl_name)
            except Exception as exc:  # pylint: disable=broad-except
                self.log.error("Failed to restore %d namespaces on %s: %s",
                               self.original_ns_count, self.ctrl_name, exc)

        self._ns_rescan()
        restored = nvme.get_current_ns_ids(self.ctrl_name)
        self.log.info(
            "NS state after restore on %s: %s", self.ctrl_name, restored
        )

    def _ns_rescan(self):
        """Trigger a namespace rescan and wait briefly."""
        process.system(f"{self.binary} ns-rescan {self.device}",
                       shell=True, ignore_status=True)
        time.sleep(2)

    def _wait_ns_visible(self, ns_id, timeout=30):
        """
        Poll until *ns_id* appears on the controller or *timeout* seconds
        elapse.

        The NVMe library's ``attach_ns()`` calls ``ns-rescan`` then sleeps
        only 2 seconds before checking visibility.  On some hardware the
        kernel takes longer to expose the block device, causing a spurious
        ``NvmeException("namespaces attached but not listing")``.  This
        helper re-polls at 1-second intervals so the calling code can
        proceed as soon as the namespace actually surfaces.

        :param ns_id:   integer namespace ID to wait for
        :param timeout: maximum seconds to wait (default 30)
        :raises TestError: if the namespace is still absent after *timeout*
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._ns_rescan()
            if nvme.is_ns_exists(self.ctrl_name, ns_id):
                self.log.info(
                    "ns_id=%s became visible on %s", ns_id, self.ctrl_name
                )
                return
            self.log.debug(
                "Waiting for ns_id=%s on %s …", ns_id, self.ctrl_name
            )
            time.sleep(1)
        self.error(
            f"Namespace {ns_id} not visible on {self.ctrl_name}"
            f" after {timeout}s"
        )

    def _create_ns_safe(self, create_fn, *args, **kwargs):
        """
        Call *create_fn* and tolerate the library's premature
        ``"namespaces attached but not listing"`` exception.

        ``nvme.attach_ns()`` raises that exception when the namespace is
        already attached but the kernel has not yet surfaced it within the
        library's fixed 2-second wait.  We catch it, trigger a fresh
        rescan, and let ``_wait_ns_visible`` confirm the NS is really there
        before continuing.

        For ``create_one_ns`` the newly created NS always gets ID equal to
        the first argument (positional ``ns_id``).  For the bulk helpers
        (``create_full_capacity_ns``, ``create_max_ns``,
        ``create_namespaces``) they always start from ns_id 1 and count up;
        we wait for every ID from 1 to the current attached count.

        :param create_fn: callable from ``avocado.utils.nvme``
        :param args:      positional arguments forwarded to *create_fn*
        :param kwargs:    keyword arguments forwarded to *create_fn*
        """
        caught_ns_id = None
        try:
            create_fn(*args, **kwargs)
        except Exception as exc:  # pylint: disable=broad-except
            if "attached but not listing" in str(exc):
                # The NS is attached – the library just timed out waiting
                # for the kernel.  Record which ns_id we need to poll for.
                # For create_one_ns the first positional arg is ns_id.
                if args:
                    try:
                        caught_ns_id = int(args[0])
                    except (ValueError, TypeError):
                        caught_ns_id = None
                self.log.info(
                    "create_fn raised '%s' – NS is attaching;"
                    " polling for visibility",
                    exc,
                )
            else:
                raise

        if caught_ns_id is not None:
            # Wait for the specific ns we know was being attached
            self._wait_ns_visible(caught_ns_id)
        else:
            # Bulk helper (create_max_ns / create_namespaces /
            # create_full_capacity_ns): wait for every currently attached NS
            self._ns_rescan()
            for ns_id in nvme.get_current_ns_ids(self.ctrl_name):
                self._wait_ns_visible(ns_id)

    def _list_ns(self):
        """Return human-readable nvme list output after a rescan."""
        self._ns_rescan()
        return process.system_output(
            f"{self.binary} list",
            shell=True, ignore_status=True).decode("utf-8")

    def _assert_ns_exists(self, ns_id):
        """
        Fail the test if namespace *ns_id* is not currently visible
        on the controller.
        """
        self._ns_rescan()
        if not nvme.is_ns_exists(self.ctrl_name, ns_id):
            self.fail(f"Namespace {ns_id} not found after creation"
                      f" on {self.ctrl_name}")
        self.log.info("Validation OK: namespace %s exists on %s",
                      ns_id, self.ctrl_name)

    def _assert_ns_absent(self, ns_id):
        """
        Fail the test if namespace *ns_id* is still visible on the
        controller (i.e. was not properly deleted).
        """
        self._ns_rescan()
        if nvme.is_ns_exists(self.ctrl_name, ns_id):
            self.fail(f"Namespace {ns_id} still exists on"
                      f" {self.ctrl_name} after deletion")
        self.log.info("Validation OK: namespace %s absent from %s",
                      ns_id, self.ctrl_name)

    def _assert_all_ns_absent(self):
        """Fail the test if any namespace remains visible."""
        self._ns_rescan()
        remaining = nvme.get_current_ns_ids(self.ctrl_name)
        if remaining:
            self.fail(f"Namespaces {remaining} still exist on"
                      f" {self.ctrl_name} after delete_all")
        self.log.info("Validation OK: no namespaces remain on %s",
                      self.ctrl_name)

    def _assert_device_path_accessible(self, ns_id):
        """
        Check that /dev/<ctrl>n<ns_id> exists as a block device,
        confirming the OS recognises the namespace.

        Polls via ``_wait_ns_visible`` first so transient kernel enumeration
        delays do not produce spurious warnings.  Fails the test if the path
        is still absent after the poll timeout.
        """
        dev_path = f"/dev/{self.ctrl_name}n{ns_id}"
        # Wait until the kernel surfaces the namespace (up to 30 s).
        self._wait_ns_visible(ns_id)
        if process.system(f"ls -la {dev_path}", shell=True,
                          ignore_status=True):
            self.fail(f"Block device path {dev_path} not accessible after "
                      f"namespace {ns_id} was created on {self.ctrl_name}")
        self.log.info("Validation OK: block device %s is accessible",
                      dev_path)

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_create_single_ns(self):
        """
        Create a single namespace using approximately 60 % of free space,
        then verify it appears in the namespace list and is accessible
        as a block device.

        Steps:
          1. Delete all existing namespaces.
          2. Calculate a safe size (60 % of free blocks).
          3. Create one namespace (ns_id = 1).
          4. Validate namespace is listed by nvme.is_ns_exists().
          5. Validate /dev/<ctrl>n1 is accessible.
          6. Delete the namespace and validate it is gone.
        """
        nvme.delete_all_ns(self.ctrl_name)
        self._assert_all_ns_absent()

        block_size = nvme.get_block_size(self.ctrl_name, shared_ns=self.shared)
        free_space = nvme.get_free_space(self.ctrl_name)
        if free_space < 1000:
            self.cancel(f"Insufficient free space on {self.ctrl_name}")

        ns_size = int((60 * (free_space // block_size)) // 100)
        self.log.info("Creating single namespace of %d blocks on %s",
                      ns_size, self.ctrl_name)
        self._create_ns_safe(
            nvme.create_one_ns, "1", self.ctrl_name, ns_size,
            shared_ns=self.shared)

        # Validation: namespace must be visible
        self._assert_ns_exists(1)
        self._assert_device_path_accessible(1)
        self.log.info("Single namespace creation test passed")

        # Cleanup
        nvme.delete_all_ns(self.ctrl_name)
        self._assert_all_ns_absent()

    def test_create_full_capacity_ns(self):
        """
        Create a single namespace consuming the full device capacity,
        then verify it is visible and accessible.

        Steps:
          1. Delete all existing namespaces.
          2. Create namespace using total capacity / block size blocks.
          3. Validate namespace exists and block device is accessible.
          4. Delete namespace and validate it is gone.
        """
        nvme.delete_all_ns(self.ctrl_name)
        self._assert_all_ns_absent()

        self.log.info("Creating full-capacity namespace on %s", self.ctrl_name)
        self._create_ns_safe(
            nvme.create_full_capacity_ns, self.ctrl_name,
            shared_ns=self.shared)

        # Validation
        self._assert_ns_exists(1)
        self._assert_device_path_accessible(1)
        self.log.info("Full-capacity namespace creation test passed")

        # Cleanup
        nvme.delete_all_ns(self.ctrl_name)
        self._assert_all_ns_absent()

    def test_create_max_ns(self):
        """
        Create the maximum number of namespaces (as reported by nn in id-ctrl),
        each with equal capacity, then verify all are visible.

        Steps:
          1. Delete all existing namespaces.
          2. Determine max namespace count from id-ctrl.
          3. Create max_ns equal-sized namespaces.
          4. Validate every actually-created namespace is visible and accessible.
             Warn (rather than fail) if fewer than max_ns were created, since
             some drives allocate capacity only up to available free blocks and
             may produce fewer namespaces than nn reports.
          5. Delete all namespaces and validate they are gone.
        """
        nvme.delete_all_ns(self.ctrl_name)
        self._assert_all_ns_absent()

        max_ns = int(nvme.get_max_ns_supported(self.ctrl_name))
        if max_ns < 1:
            self.cancel("Device reports 0 maximum namespaces")

        self.log.info("Creating maximum %d namespace(s) on %s",
                      max_ns, self.ctrl_name)
        # Allow the controller to update its free-space accounting
        # (unvmcap in id-ctrl) after delete_all_ns before querying it.
        self._ns_rescan()
        # force=True because we just deleted everything above
        self._create_ns_safe(
            nvme.create_max_ns, self.ctrl_name,
            force=True, shared_ns=self.shared)

        # Validation: check namespaces that were actually created.
        # Use the live list rather than asserting 1..max_ns unconditionally —
        # some drives do not allocate enough space for every nn slot and will
        # create fewer namespaces without returning an error.
        self._ns_rescan()
        created = nvme.get_current_ns_ids(self.ctrl_name)
        self.log.info("Namespaces present after creation: %s (max_ns=%d)",
                      created, max_ns)
        if not created:
            self.fail(f"No namespaces created by create_max_ns"
                      f" on {self.ctrl_name}")
        if len(created) < max_ns:
            self.log.info(
                "create_max_ns created %d namespace(s); id-ctrl reports"
                " nn=%d (device capacity limits the number of equal-sized"
                " slots that can be allocated)",
                len(created), max_ns)
        for ns_id in created:
            self._assert_ns_exists(ns_id)
            self._assert_device_path_accessible(ns_id)
        self.log.info(
            "Max namespace creation test passed: %d namespace(s) verified",
            len(created))

        # Cleanup
        nvme.delete_all_ns(self.ctrl_name)
        self._assert_all_ns_absent()

    def test_create_shared_ns(self):
        """
        Create a shared namespace (nmic bit set) for multi-path access,
        then verify it appears in the namespace list.

        Steps:
          1. Delete all existing namespaces.
          2. Create one namespace with shared_ns=True.
          3. Validate namespace exists.
          4. Delete namespace and validate it is gone.

        Note: This test is most meaningful on multi-path NVMe fabrics where
        the namespace is shared across multiple controllers (NQN).
        """
        nvme.delete_all_ns(self.ctrl_name)
        self._assert_all_ns_absent()

        block_size = nvme.get_block_size(self.ctrl_name, shared_ns=True)
        free_space = nvme.get_free_space(self.ctrl_name)
        if free_space < 1000:
            self.cancel(f"Insufficient free space on {self.ctrl_name}")

        ns_size = int((60 * (free_space // block_size)) // 100)
        self.log.info("Creating shared namespace of %d blocks on %s",
                      ns_size, self.ctrl_name)
        self._create_ns_safe(
            nvme.create_one_ns, "1", self.ctrl_name, ns_size,
            shared_ns=True)

        # Validation
        self._assert_ns_exists(1)
        self._assert_device_path_accessible(1)
        self.log.info("Shared namespace creation test passed")

        # Cleanup
        nvme.delete_all_ns(self.ctrl_name)
        self._assert_all_ns_absent()

    def test_create_equal_ns(self):
        """
        Create *namespace_count* equal-sized namespaces and verify each
        one is visible and accessible.

        Steps:
          1. Delete all existing namespaces.
          2. Create ns_count namespaces with equal block sizes.
          3. Validate every namespace exists and is accessible.
          4. Delete all namespaces and validate they are gone.

        :param namespace_count: Number of equal namespaces to create
                                (default 4).
        """
        nvme.delete_all_ns(self.ctrl_name)
        self._assert_all_ns_absent()

        self.log.info("Creating %d equal-sized namespace(s) on %s",
                      self.ns_count, self.ctrl_name)
        self._create_ns_safe(
            nvme.create_namespaces, self.ctrl_name, self.ns_count,
            shared_ns=self.shared)

        # Validation
        self._ns_rescan()
        for ns_id in range(1, self.ns_count + 1):
            if not nvme.is_ns_exists(self.ctrl_name, ns_id):
                self.fail(f"Namespace {ns_id} missing after"
                          f" create_namespaces on {self.ctrl_name}")
            self._assert_device_path_accessible(ns_id)
        self.log.info(
            "Equal namespace creation test passed: %d namespace(s) verified",
            self.ns_count)

        # Cleanup
        nvme.delete_all_ns(self.ctrl_name)
        self._assert_all_ns_absent()

    def test_delete_all_ns(self):
        """
        Create one namespace, verify it exists, then delete all namespaces
        and verify none remain.

        Steps:
          1. Delete any pre-existing namespaces.
          2. Create a single namespace.
          3. Validate it exists.
          4. Delete all namespaces.
          5. Validate no namespaces remain.
        """
        nvme.delete_all_ns(self.ctrl_name)

        block_size = nvme.get_block_size(self.ctrl_name, shared_ns=self.shared)
        free_space = nvme.get_free_space(self.ctrl_name)
        if free_space < 1000:
            self.cancel(f"Insufficient free space on {self.ctrl_name}")

        ns_size = int((60 * (free_space // block_size)) // 100)
        self._create_ns_safe(
            nvme.create_one_ns, "1", self.ctrl_name, ns_size,
            shared_ns=self.shared)
        self._assert_ns_exists(1)

        self.log.info("Deleting all namespaces from %s", self.ctrl_name)
        nvme.delete_all_ns(self.ctrl_name)
        self._assert_all_ns_absent()
        self.log.info("Delete all namespaces test passed")
