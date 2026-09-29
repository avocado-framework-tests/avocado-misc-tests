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
NVMe Read / Write Tests.

Covers:
  - Read from a namespace.
  - Read from a specific LBA offset (--start-block).
  - Read multiple blocks (--block-count).
  - Read with Force-Unit-Access (--force-unit-access).
  - Read to a file (--data).
  - Write to a namespace.
  - Write at a specific LBA offset (--start-block).
  - Write multiple blocks (--block-count).
  - Write with Force-Unit-Access (--force-unit-access).
  - Write from a file (--data).
  - Flush the namespace / controller cache.
  - Write-Zeroes to a namespace (requires device support).
  - Write-Uncorrectable to a namespace (requires device support).

Each test verifies that the namespace is healthy before exercising the
I/O path and checks the return code after every command.
"""

import os
import tempfile
from avocado import Test
from avocado.utils import disk
from avocado.utils import process
from avocado.utils import archive
from avocado.utils import nvme
from avocado.utils.software_manager.manager import SoftwareManager


class NVMeReadWrite(Test):
    """
    NVMe Read / Write Tests.

    :param device: Name of the nvme device (e.g. nvme0, or subsystem NQN)
    :param shared_namespaces: True if the namespace is shared (default False)
    :param package: 'distro' (default) or 'upstream' to build nvme-cli
                    from source
    """

    def setUp(self):
        """
        Install nvme-cli, resolve the device path, and locate the target
        namespace by querying the controller directly.
        """
        nvme_node = self.params.get('device', default=None)
        if not nvme_node:
            self.cancel("Please provide valid nvme disk name")
        elif "subsys" in nvme_node:
            nvme_node = nvme.get_controllers_with_subsys(nvme_node)[0]
        elif nvme_node.startswith("nqn."):
            nvme_node = nvme.get_controllers_with_nqn(nvme_node)[0]
        self.device = disk.get_absolute_disk_path(nvme_node)
        if process.system(f'ls {self.device}', ignore_status=True):
            self.cancel(f"{self.device} does not exist")

        self.ctrl_name = self.device.split("/")[-1]
        self.shared = self.params.get('shared_namespaces', default=False)

        # Discover all namespaces on the controller and pick the first one.
        ns_list = nvme.get_current_ns_list(self.ctrl_name,
                                           shared_ns=self.shared)
        if not ns_list:
            self.cancel(f"No namespaces found on controller {self.ctrl_name}")
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
            locations = [
                "https://github.com/linux-nvme/nvme-cli/archive/master.zip"]
            tarball = self.fetch_asset("nvme-cli.zip", locations=locations,
                                       expire='15d')
            archive.extract(tarball, self.teststmpdir)
            os.chdir(f"{self.teststmpdir}/nvme-cli-master")
            process.system("meson setup --force-fallback-for=libnvme .build",
                           ignore_status=True)
            process.system("meson compile -C .build", ignore_status=True)
            self.binary = './.build/nvme'
        else:
            if not smm.check_installed("nvme-cli") and \
                    not smm.install("nvme-cli"):
                self.cancel('nvme-cli is needed for the test to be run')
            self.binary = 'nvme'

        # Obtain the block size once; used as the I/O transfer length
        self.block_size = nvme.get_block_size(self.ctrl_name,
                                              shared_ns=self.shared)

        # Check capability flags for commands that are optional per NVMe spec
        cmd = f"{self.binary} id-ctrl {self.device} -H"
        self.id_ctrl = process.system_output(cmd, shell=True).decode("utf-8")

        # Validate that the target namespace device path exists
        if process.system(f'ls {self.id_ns}', ignore_status=True):
            self.cancel(f"Namespace device {self.id_ns} does not exist. "
                        "Ensure the namespace is created before "
                        "running this test.")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _ns_is_healthy(self):
        """
        Return True if the target namespace is healthy, False otherwise.

        Queries ``nvme show-topology`` via ``nvme.get_ns_status()`` which
        returns ``[State, ANAState]`` on success or ``[]`` when
        show-topology is unavailable.

        Healthy state   : "live"
        Unhealthy states: "inaccessible", "persistent-loss", "change"

        When show-topology is unavailable, returns an error JSON object
        instead of a list (older avocado versions crash with TypeError on
        this), or raises any other exception, the check is skipped and
        True is returned — the command is optional in the NVMe spec.
        """
        try:
            status = nvme.get_ns_status(self.ctrl_name, self.namespace)
        except TypeError:
            # Older avocado: show-topology returned an error dict instead of
            # a list; the library tried to subscript it as a dict and raised
            # TypeError.  Treat as unavailable and skip.
            self.log.debug("show-topology returned unexpected output for %s; "
                           "skipping health check.", self.id_ns)
            return True
        except Exception as exc:  # pylint: disable=broad-except
            self.log.debug("show-topology check skipped for %s: %s",
                           self.id_ns, exc)
            return True
        if not status:
            # show-topology not available on this setup — skip the check.
            self.log.debug("show-topology unavailable for %s; "
                           "skipping health check.", self.id_ns)
            return True
        state = status[0].lower()
        self.log.info("Namespace %s state: %s", self.id_ns, state)
        if state != "live":
            self.log.warning("Namespace %s is not in 'live' state: %s",
                             self.id_ns, state)
            return False
        return True

    def _validate_ns_accessible(self):
        """Fail the test if the namespace block device is not accessible."""
        if process.system(f'ls -la {self.id_ns}', shell=True,
                          ignore_status=True):
            self.fail(f"Namespace {self.id_ns} is not accessible before I/O")
        else:
            self.log.info(f"Namespace {self.id_ns} is accessible before I/O")

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_read(self):
        """
        Issue a read command on the namespace and verify it succeeds.

        Steps:
          1. Validate namespace block device is accessible.
          2. Verify namespace is in 'live' state.
          3. Issue: nvme read <ns> -z <block_size> -t
          4. Validate return code is 0 (success).
        """
        self._validate_ns_accessible()
        if not self._ns_is_healthy():
            self.cancel(f"Namespace {self.id_ns} is not healthy; "
                        "skipping I/O test")

        cmd = f"{self.binary} read {self.id_ns} -z {self.block_size} -t"
        self.log.info("Read command: %s", cmd)
        ret = process.system(cmd, timeout=300, ignore_status=True, shell=True)
        if ret:
            self.fail(f"NVMe read failed on {self.id_ns} (exit code {ret})")
        self.log.info("Read test passed on %s", self.id_ns)

    def test_read_start_block(self):
        """
        Issue a read command starting at a non-zero LBA offset and verify
        it succeeds.

        Uses --start-block (-s) to address block 1 instead of block 0,
        exercising the LBA-offset code path in the controller.

        Steps:
          1. Validate namespace block device is accessible.
          2. Verify namespace is in 'live' state.
          3. Issue: nvme read <ns> -s 1 -z <block_size> -t
          4. Validate return code is 0 (success).
        """
        self._validate_ns_accessible()
        if not self._ns_is_healthy():
            self.cancel(f"Namespace {self.id_ns} is not healthy; "
                        "skipping I/O test")

        cmd = (f"{self.binary} read {self.id_ns}"
               f" -s 1 -z {self.block_size} -t")
        self.log.info("Read start-block command: %s", cmd)
        ret = process.system(cmd, timeout=300, ignore_status=True, shell=True)
        if ret:
            self.fail(f"NVMe read (start-block=1) failed on {self.id_ns} "
                      f"(exit code {ret})")
        self.log.info("Read start-block test passed on %s", self.id_ns)

    def test_read_block_count(self):
        """
        Issue a read command that transfers multiple blocks and verify
        it succeeds.

        Uses --block-count (-c 3) together with --data-size (-z) sized for
        4 blocks (block_size * 4), exercising multi-block read addressing.

        Steps:
          1. Validate namespace block device is accessible.
          2. Verify namespace is in 'live' state.
          3. Issue: nvme read <ns> -c 3 -z <block_size*4> -t
          4. Validate return code is 0 (success).
        """
        self._validate_ns_accessible()
        if not self._ns_is_healthy():
            self.cancel(f"Namespace {self.id_ns} is not healthy; "
                        "skipping I/O test")

        block_count = 3          # 0-based: requests 4 blocks (0..3)
        data_size = self.block_size * (block_count + 1)
        cmd = (f"{self.binary} read {self.id_ns}"
               f" -c {block_count} -z {data_size} -t")
        self.log.info("Read block-count command: %s", cmd)
        ret = process.system(cmd, timeout=300, ignore_status=True, shell=True)
        if ret:
            self.fail(f"NVMe read (block-count={block_count}) failed on "
                      f"{self.id_ns} (exit code {ret})")
        self.log.info("Read block-count test passed on %s", self.id_ns)

    def test_read_force_unit_access(self):
        """
        Issue a read command with Force-Unit-Access (FUA) set and verify
        it succeeds.

        --force-unit-access (-f) instructs the controller to read directly
        from non-volatile storage, bypassing any volatile cache.  This
        exercises the FUA code path through the submission queue.

        Steps:
          1. Validate namespace block device is accessible.
          2. Verify namespace is in 'live' state.
          3. Issue: nvme read <ns> -z <block_size> -f -t
          4. Validate return code is 0 (success).
        """
        self._validate_ns_accessible()
        if not self._ns_is_healthy():
            self.cancel(f"Namespace {self.id_ns} is not healthy; "
                        "skipping I/O test")

        cmd = (f"{self.binary} read {self.id_ns}"
               f" -z {self.block_size} -f -t")
        self.log.info("Read FUA command: %s", cmd)
        ret = process.system(cmd, timeout=300, ignore_status=True, shell=True)
        if ret:
            self.fail(f"NVMe read (force-unit-access) failed on {self.id_ns} "
                      f"(exit code {ret})")
        self.log.info("Read force-unit-access test passed on %s", self.id_ns)

    def test_read_to_file(self):
        """
        Issue a read command that writes output to a file and verify the
        file is created and non-empty.

        --data (-d) redirects the read payload to a file instead of stdout,
        allowing data-pattern verification by external tools.

        Steps:
          1. Validate namespace block device is accessible.
          2. Verify namespace is in 'live' state.
          3. Issue: nvme read <ns> -z <block_size> -d <tmpfile> -t
          4. Validate return code is 0 (success).
          5. Validate the output file exists and is non-empty.
          6. Remove the temporary file.
        """
        self._validate_ns_accessible()
        if not self._ns_is_healthy():
            self.cancel(f"Namespace {self.id_ns} is not healthy; "
                        "skipping I/O test")

        with tempfile.NamedTemporaryFile(prefix="nvme_read_", suffix=".bin",
                                         delete=False) as tmp:
            out_file = tmp.name

        try:
            cmd = (f"{self.binary} read {self.id_ns}"
                   f" -z {self.block_size} -d {out_file} -t")
            self.log.info("Read to-file command: %s", cmd)
            ret = process.system(cmd, timeout=300, ignore_status=True,
                                 shell=True)
            if ret:
                self.fail(f"NVMe read (to-file) failed on {self.id_ns} "
                          f"(exit code {ret})")
            if not os.path.isfile(out_file) or os.path.getsize(out_file) == 0:
                self.fail(f"Read output file {out_file} is missing or empty")
            self.log.info("Read to-file test passed on %s (file: %s)",
                          self.id_ns, out_file)
        finally:
            if os.path.exists(out_file):
                os.remove(out_file)

    def test_write(self):
        """
        Issue a write command on the namespace and verify it succeeds.

        Steps:
          1. Validate namespace block device is accessible.
          2. Verify namespace is in 'live' state.
          3. Issue: echo 1 | nvme write <ns> -z <block_size> -t
          4. Validate return code is 0 (success).
        """
        self._validate_ns_accessible()
        if not self._ns_is_healthy():
            self.cancel(f"Namespace {self.id_ns} is not healthy; "
                        "skipping I/O test")

        cmd = (f"echo 1|{self.binary} write {self.id_ns}"
               f" -z {self.block_size} -t")
        self.log.info("Write command: %s", cmd)
        ret = process.system(cmd, timeout=300, ignore_status=True, shell=True)
        if ret:
            self.fail(f"NVMe write failed on {self.id_ns} (exit code {ret})")
        self.log.info("Write test passed on %s", self.id_ns)

    def test_write_start_block(self):
        """
        Issue a write command starting at a non-zero LBA offset and verify
        it succeeds.

        Uses --start-block (-s 1) to address block 1, exercising the
        LBA-offset code path for writes inside the controller.

        Steps:
          1. Validate namespace block device is accessible.
          2. Verify namespace is in 'live' state.
          3. Issue: echo 1 | nvme write <ns> -s 1 -z <block_size> -t
          4. Validate return code is 0 (success).
        """
        self._validate_ns_accessible()
        if not self._ns_is_healthy():
            self.cancel(f"Namespace {self.id_ns} is not healthy; "
                        "skipping I/O test")

        cmd = (f"echo 1|{self.binary} write {self.id_ns}"
               f" -s 1 -z {self.block_size} -t")
        self.log.info("Write start-block command: %s", cmd)
        ret = process.system(cmd, timeout=300, ignore_status=True, shell=True)
        if ret:
            self.fail(f"NVMe write (start-block=1) failed on {self.id_ns} "
                      f"(exit code {ret})")
        self.log.info("Write start-block test passed on %s", self.id_ns)

    def test_write_block_count(self):
        """
        Issue a write command that transfers multiple blocks and verify
        it succeeds.

        Uses --block-count (-c 3) together with --data-size (-z) sized for
        4 blocks (block_size * 4), exercising multi-block write addressing.

        Steps:
          1. Validate namespace block device is accessible.
          2. Verify namespace is in 'live' state.
          3. Issue: echo 1 | nvme write <ns> -c 3 -z <block_size*4> -t
          4. Validate return code is 0 (success).
        """
        self._validate_ns_accessible()
        if not self._ns_is_healthy():
            self.cancel(f"Namespace {self.id_ns} is not healthy; "
                        "skipping I/O test")

        block_count = 3          # 0-based: writes 4 blocks (0..3)
        data_size = self.block_size * (block_count + 1)
        cmd = (f"echo 1|{self.binary} write {self.id_ns}"
               f" -c {block_count} -z {data_size} -t")
        self.log.info("Write block-count command: %s", cmd)
        ret = process.system(cmd, timeout=300, ignore_status=True, shell=True)
        if ret:
            self.fail(f"NVMe write (block-count={block_count}) failed on "
                      f"{self.id_ns} (exit code {ret})")
        self.log.info("Write block-count test passed on %s", self.id_ns)

    def test_write_force_unit_access(self):
        """
        Issue a write command with Force-Unit-Access (FUA) set and verify
        it succeeds.

        --force-unit-access (-f) instructs the controller to commit data
        to non-volatile storage before signalling completion, providing a
        strong write-durability guarantee.

        Steps:
          1. Validate namespace block device is accessible.
          2. Verify namespace is in 'live' state.
          3. Issue: echo 1 | nvme write <ns> -z <block_size> -f -t
          4. Validate return code is 0 (success).
        """
        self._validate_ns_accessible()
        if not self._ns_is_healthy():
            self.cancel(f"Namespace {self.id_ns} is not healthy; "
                        "skipping I/O test")

        cmd = (f"echo 1|{self.binary} write {self.id_ns}"
               f" -z {self.block_size} -f -t")
        self.log.info("Write FUA command: %s", cmd)
        ret = process.system(cmd, timeout=300, ignore_status=True, shell=True)
        if ret:
            self.fail(f"NVMe write (force-unit-access) failed on {self.id_ns} "
                      f"(exit code {ret})")
        self.log.info("Write force-unit-access test passed on %s", self.id_ns)

    def test_write_from_file(self):
        """
        Issue a write command that reads its payload from a file and verify
        it succeeds.

        --data (-d) supplies the write data from a file instead of stdin,
        exercising the file-backed I/O path and allowing deterministic
        data-pattern writes.

        Steps:
          1. Validate namespace block device is accessible.
          2. Verify namespace is in 'live' state.
          3. Create a temporary file filled with one block of 0xAB bytes.
          4. Issue: nvme write <ns> -z <block_size> -d <tmpfile> -t
          5. Validate return code is 0 (success).
          6. Remove the temporary file.
        """
        self._validate_ns_accessible()
        if not self._ns_is_healthy():
            self.cancel(f"Namespace {self.id_ns} is not healthy; "
                        "skipping I/O test")

        with tempfile.NamedTemporaryFile(prefix="nvme_write_", suffix=".bin",
                                         delete=False) as tmp:
            tmp.write(b'\xab' * self.block_size)
            in_file = tmp.name

        try:
            cmd = (f"{self.binary} write {self.id_ns}"
                   f" -z {self.block_size} -d {in_file} -t")
            self.log.info("Write from-file command: %s", cmd)
            ret = process.system(cmd, timeout=300, ignore_status=True,
                                 shell=True)
            if ret:
                self.fail(f"NVMe write (from-file) failed on {self.id_ns} "
                          f"(exit code {ret})")
            self.log.info("Write from-file test passed on %s (file: %s)",
                          self.id_ns, in_file)
        finally:
            if os.path.exists(in_file):
                os.remove(in_file)

    def test_flush(self):
        """
        Issue a flush command on the namespace/controller and verify success.

        Steps:
          1. Validate namespace block device is accessible.
          2. Issue: nvme flush <ns>
          3. Validate return code is 0 (success).
        """
        self._validate_ns_accessible()

        cmd = f"{self.binary} flush {self.id_ns}"
        self.log.info("Flush command: %s", cmd)
        ret = process.system(cmd, ignore_status=True, shell=True)
        if ret:
            self.fail(f"NVMe flush failed on {self.id_ns} (exit code {ret})")
        self.log.info("Flush test passed on %s", self.id_ns)

    def test_write_zeroes(self):
        """
        Issue a write-zeroes command on the namespace and verify success.

        Requires the device to advertise 'Write Zeroes Supported' in id-ctrl.

        Steps:
          1. Validate capability.
          2. Validate namespace block device is accessible.
          3. Verify namespace is in 'live' state.
          4. Issue: nvme write-zeroes <ns>
          5. Validate return code is 0 (success).
          6. Optionally verify data is zeroed by reading back one block.
        """
        if "Write Zeroes Supported" not in self.id_ctrl:
            self.cancel("Write Zeroes is not supported on this device")

        self._validate_ns_accessible()
        if not self._ns_is_healthy():
            self.cancel(f"Namespace {self.id_ns} is not healthy; "
                        "skipping I/O test")

        cmd = f"{self.binary} write-zeroes {self.id_ns}"
        self.log.info("Write-zeroes command: %s", cmd)
        ret = process.system(cmd, ignore_status=True, shell=True)
        if ret:
            self.fail(f"NVMe write-zeroes failed on {self.id_ns} "
                      f"(exit code {ret})")

        # Validation: read back one block — it must succeed (data integrity
        # check beyond return code is best handled by upper-layer tools).
        verify_cmd = f"{self.binary} read {self.id_ns} -z {self.block_size}"
        ret = process.system(verify_cmd, timeout=60, ignore_status=True,
                             shell=True)
        if ret:
            self.fail(f"Read-back after write-zeroes failed on {self.id_ns} "
                      f"(exit code {ret})")
        self.log.info("Write-zeroes test passed on %s", self.id_ns)

    def test_write_uncorrectable(self):
        """
        Issue a write-uncorrectable command on the namespace and verify
        success.

        Requires the device to advertise 'Write Uncorrectable Supported' in
        id-ctrl.

        Steps:
          1. Validate capability.
          2. Validate namespace block device is accessible.
          3. Verify namespace is in 'live' state.
          4. Issue: nvme write-uncor <ns>
          5. Validate return code is 0 (success).
        """
        if "Write Uncorrectable Supported" not in self.id_ctrl:
            self.cancel("Write Uncorrectable is not supported on this device")

        self._validate_ns_accessible()
        if not self._ns_is_healthy():
            self.cancel(f"Namespace {self.id_ns} is not healthy; "
                        "skipping I/O test")

        cmd = f"{self.binary} write-uncor {self.id_ns}"
        self.log.info("Write-uncorrectable command: %s", cmd)
        ret = process.system(cmd, ignore_status=True, shell=True)
        if ret:
            self.fail(f"NVMe write-uncorrectable failed on {self.id_ns} "
                      f"(exit code {ret})")
        self.log.info("Write-uncorrectable test passed on %s", self.id_ns)
