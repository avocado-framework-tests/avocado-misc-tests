#!/usr/bin/env python

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE for more details.
#
# Copyright: 2026 IBM
# Author: Priyanka Behera <priyanka.behera2@ibm.com>

"""
Software RAID Rebuild + Sync + LVM Extend Test

This test performs comprehensive testing of software RAID rebuild operations,
synchronization monitoring during rebuild, LVM setup on RAID, and logical
volume extension with automatic filesystem detection and verification.
"""

import os
import time
from avocado import Test
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils import disk
from avocado.utils import softwareraid
from avocado.utils import lv_utils
from avocado.utils import process
from avocado.utils import distro


class SwraidRebuildLVM(Test):
    """
    Test class for Software RAID rebuild with synchronization monitoring,
    LVM setup, and logical volume extension operations.
    """

    def setUp(self):
        """
        Setup test environment: install packages, validate disks, and
        initialize RAID and LVM configurations.
        """
        self.disks = []
        self.spare_disks = []
        smm = SoftwareManager()
        detected_distro = distro.detect()

        # Install required packages
        packages = ['mdadm']
        if detected_distro.name in ['Ubuntu', 'debian']:
            packages.append('lvm2')

        for pkg in packages:
            if not smm.check_installed(pkg):
                self.log.info("Installing %s...", pkg)
                if not smm.install(pkg):
                    self.cancel("Unable to install %s" % pkg)

        # Automatically detect and install filesystem utilities
        self.fs_name = self._detect_filesystem()
        self._install_filesystem_utils(detected_distro)

        # Parse disk configuration
        disks_param = (self.params.get('disks', default='').strip()).split()
        if not disks_param:
            self.cancel('No disks provided for RAID creation')

        for dev in disks_param:
            self.disks.append(disk.get_absolute_disk_path(dev))

        # RAID configuration
        self.raidlevel = str(self.params.get('raid', default='1'))
        required_disks = self.params.get('required_disks', default=2)

        if len(self.disks) < required_disks:
            self.cancel("Minimum %s disks required for RAID%s" %
                        (required_disks, self.raidlevel))

        # Parse spare disks
        spare_disks_param = self.params.get('spare_disks', default='')
        if spare_disks_param:
            for dev in spare_disks_param.split():
                self.spare_disks.append(disk.get_absolute_disk_path(dev))

        self.raid_name = self.params.get('raidname',
                                         default='/dev/md/test_raid')
        self.metadata = str(self.params.get('metadata', default='1.2'))

        # LVM configuration
        self.vg_name = self.params.get('vg_name', default='test_vg')
        self.lv_name = self.params.get('lv_name', default='test_lv')
        self.mount_loc = os.path.join(self.workdir, 'mountpoint')

        if not os.path.isdir(self.mount_loc):
            os.makedirs(self.mount_loc)

        # Determine rebuild disk (last disk in the array)
        self.rebuild_disk = None
        if self.raidlevel not in ['0', 'linear']:
            if len(self.disks) >= required_disks:
                self.rebuild_disk = self.disks[-1]

        # Initialize software RAID object
        self.sraid = softwareraid.SoftwareRaid(
            self.raid_name,
            self.raidlevel,
            self.disks,
            self.metadata,
            self.spare_disks
        )

        self.log.info("=" * 70)
        self.log.info("Test Configuration:")
        self.log.info("  RAID Level: %s", self.raidlevel)
        self.log.info("  RAID Name: %s", self.raid_name)
        self.log.info("  Devices: %s", len(self.disks))
        self.log.info("  Spare Disks: %s", len(self.spare_disks))
        self.log.info("  Filesystem: %s", self.fs_name)
        self.log.info("  VG Name: %s", self.vg_name)
        self.log.info("  LV Name: %s", self.lv_name)
        self.log.info("=" * 70)

    def _detect_filesystem(self):
        """
        Automatically detect the best filesystem to use based on OS.
        Priority: ext4 > xfs > ext3 > btrfs
        """
        detected_distro = distro.detect()

        # RHEL/CentOS prefer XFS
        if detected_distro.name in ['rhel', 'centos', 'fedora']:
            return 'xfs'

        # Default to ext4 for most distributions
        return 'ext4'

    def _install_filesystem_utils(self, detected_distro):
        """
        Install filesystem utilities based on detected filesystem.
        """
        smm = SoftwareManager()
        fs_packages = {
            'ext4': 'e2fsprogs',
            'ext3': 'e2fsprogs',
            'xfs': 'xfsprogs',
            'btrfs': ('btrfs-progs' if detected_distro.name not in
                      ['Ubuntu', 'debian'] else 'btrfs-tools')
        }

        if self.fs_name in fs_packages:
            fs_pkg = fs_packages[self.fs_name]
            if not smm.check_installed(fs_pkg):
                self.log.info("Installing filesystem utility %s...", fs_pkg)
                if not smm.install(fs_pkg):
                    self.log.warning("Unable to install %s, trying fallback",
                                     fs_pkg)
                    # Fallback to ext4 if preferred fs tools can't be installed
                    if self.fs_name != 'ext4':
                        self.fs_name = 'ext4'
                        if not smm.check_installed('e2fsprogs'):
                            if not smm.install('e2fsprogs'):
                                self.cancel(
                                    "Unable to install any filesystem "
                                    "utilities")

    def wait_for_sync(self, timeout=600):
        """
        Wait for RAID synchronization to complete.

        Args:
            timeout: Maximum time to wait in seconds (default: 600)

        Returns:
            bool: True if sync completed successfully, False otherwise
        """
        self.log.info("Waiting for RAID synchronization to complete...")
        self.log.info("Timeout: %d seconds", timeout)
        start_time = time.time()
        last_progress = None

        while time.time() - start_time < timeout:
            try:
                result = process.run("mdadm --detail %s" % self.raid_name,
                                     shell=True, ignore_status=True)
                output = result.stdout_text

                # Check if RAID is in clean/active state
                if ("State : clean" in output or
                        ("State : active" in output and
                         "resync" not in output.lower() and
                         "recovery" not in output.lower())):
                    elapsed = time.time() - start_time
                    self.log.info("RAID synchronization completed in "
                                  "%.2f seconds", elapsed)
                    return True

                # Monitor sync progress
                for line in output.split('\n'):
                    line_lower = line.lower()
                    if ('resync' in line_lower or 'recovery' in line_lower or
                            'rebuild' in line_lower):
                        if line.strip() != last_progress:
                            self.log.info("Sync status: %s", line.strip())
                            last_progress = line.strip()

                time.sleep(5)
            except Exception as err:
                self.log.warning("Error checking sync status: %s", err)
                time.sleep(5)

        elapsed = time.time() - start_time
        self.log.error("RAID sync did not complete within %d seconds "
                       "(elapsed: %.2f)", timeout, elapsed)
        return False

    def raid_creation_and_sync(self):
        """
        Create RAID array and wait for initial synchronization.
        """
        self.log.info("\n" + "=" * 70)
        self.log.info("STEP 1: RAID Creation and Initial Synchronization")
        self.log.info("=" * 70)

        self.log.info("Creating RAID%s array: %s",
                      self.raidlevel, self.raid_name)
        if not self.sraid.create():
            self.fail("Failed to create RAID array")

        self.log.info("RAID array %s created successfully", self.raid_name)

        # Wait for initial sync
        if not self.wait_for_sync(timeout=600):
            self.fail("RAID initial synchronization failed")

        # Display RAID status
        result = process.run("mdadm --detail %s" % self.raid_name, shell=True)
        self.log.info("RAID Status:\n%s", result.stdout_text)

    def raid_rebuild_and_sync(self):
        """
        Test RAID rebuild by removing and re-adding a disk,
        then monitoring synchronization during rebuild.
        """
        if not self.rebuild_disk:
            self.log.info("Skipping rebuild test (not applicable for "
                          "RAID level %s)", self.raidlevel)
            return

        self.log.info("\n" + "=" * 70)
        self.log.info("STEP 2: RAID Rebuild and Synchronization Monitoring")
        self.log.info("=" * 70)

        self.log.info("Simulating disk failure by removing: %s",
                      self.rebuild_disk)
        if not self.sraid.remove_disk(self.rebuild_disk):
            self.fail("Failed to remove disk %s" % self.rebuild_disk)

        self.log.info("Disk %s removed successfully", self.rebuild_disk)
        time.sleep(2)

        # Show degraded RAID status
        result = process.run("mdadm --detail %s" % self.raid_name,
                             shell=True, ignore_status=True)
        self.log.info("RAID Status (degraded):\n%s", result.stdout_text)

        self.log.info("Re-adding disk to trigger rebuild: %s",
                      self.rebuild_disk)
        if not self.sraid.add_disk(self.rebuild_disk):
            self.fail("Failed to add disk %s" % self.rebuild_disk)

        self.log.info("Disk %s added successfully, rebuild started",
                      self.rebuild_disk)

        # Monitor rebuild synchronization
        if not self.wait_for_sync(timeout=900):
            self.fail("RAID rebuild/sync failed")

        self.log.info("RAID rebuild completed successfully")

        # Display final RAID status
        result = process.run("mdadm --detail %s" % self.raid_name, shell=True)
        self.log.info("RAID Status (after rebuild):\n%s", result.stdout_text)

    def lvm_setup_on_raid(self):
        """
        Setup LVM on RAID device: create PV, VG, LV, and filesystem.
        """
        self.log.info("\n" + "=" * 70)
        self.log.info("STEP 3: LVM Setup on RAID")
        self.log.info("=" * 70)

        # Clean up existing VG if present
        if lv_utils.vg_check(self.vg_name):
            self.log.warning("Volume group %s already exists, cleaning up...",
                             self.vg_name)
            lv_utils.vg_remove(self.vg_name)

        # Create Physical Volume
        self.log.info("Creating Physical Volume on %s...", self.raid_name)
        process.run("pvcreate -ff -y %s" % self.raid_name, shell=True)

        # Create Volume Group
        self.log.info("Creating Volume Group %s...", self.vg_name)
        process.run("vgcreate %s %s" % (self.vg_name, self.raid_name),
                    shell=True)

        if not lv_utils.vg_check(self.vg_name):
            self.fail("Volume group %s creation failed" % self.vg_name)

        vg_info = process.run("vgdisplay %s" % self.vg_name, shell=True)
        self.log.info("Volume Group Info:\n%s", vg_info.stdout_text)

        # Create Logical Volume (50% of VG)
        self.log.info("Creating Logical Volume %s (50%% of VG)...",
                      self.lv_name)
        process.run("lvcreate -y -l 50%%VG -n %s %s" %
                    (self.lv_name, self.vg_name), shell=True)

        if not lv_utils.lv_check(self.vg_name, self.lv_name):
            self.fail("Logical volume %s creation failed" % self.lv_name)

        lv_path = "/dev/%s/%s" % (self.vg_name, self.lv_name)

        # Create filesystem
        self.log.info("Creating %s filesystem on %s...", self.fs_name, lv_path)
        self._create_filesystem(lv_path)

        # Mount filesystem
        self.log.info("Mounting filesystem at %s...", self.mount_loc)
        process.run("mount %s %s" % (lv_path, self.mount_loc), shell=True)

        # Display mounted filesystems
        result = process.run("df -h %s" % self.mount_loc, shell=True)
        self.log.info("Mounted filesystem:\n%s", result.stdout_text)

    def _create_filesystem(self, device):
        """
        Create filesystem on the specified device.

        Args:
            device: Device path to create filesystem on
        """
        if self.fs_name == 'ext4':
            process.run("mkfs.ext4 -F %s" % device, shell=True)
        elif self.fs_name == 'ext3':
            process.run("mkfs.ext3 -F %s" % device, shell=True)
        elif self.fs_name == 'xfs':
            process.run("mkfs.xfs -f %s" % device, shell=True)
        elif self.fs_name == 'btrfs':
            process.run("mkfs.btrfs -f %s" % device, shell=True)
        else:
            self.fail("Unsupported filesystem type: %s" % self.fs_name)

    def lvm_extend_and_verify(self):
        """
        Extend LVM logical volume, resize filesystem, and verify size increase.
        """
        self.log.info("\n" + "=" * 70)
        self.log.info("STEP 4: LVM Extension and Size Verification")
        self.log.info("=" * 70)

        lv_path = "/dev/%s/%s" % (self.vg_name, self.lv_name)

        # Display current LV info
        result = process.run("lvdisplay %s" % lv_path, shell=True)
        self.log.info("Current LV Info:\n%s", result.stdout_text)

        # Get filesystem size before extend
        df_before = process.run("df -B1 %s | tail -1" % self.mount_loc,
                                shell=True)
        size_before = int(df_before.stdout_text.split()[1])
        self.log.info("Filesystem size before extend: %d bytes (%.2f MB)",
                      size_before, size_before / (1024 * 1024))

        # Extend Logical Volume
        self.log.info("Extending Logical Volume by 20%% of VG...")
        try:
            process.run("lvextend -l +20%%VG %s" % lv_path, shell=True)
        except process.CmdError as err:
            self.fail("Failed to extend logical volume: %s" % err)

        self.log.info("Logical Volume extended successfully")

        # Resize filesystem
        self.log.info("Resizing %s filesystem...", self.fs_name)
        self._resize_filesystem(lv_path)

        # Display extended LV info
        result = process.run("lvdisplay %s" % lv_path, shell=True)
        self.log.info("Extended LV Info:\n%s", result.stdout_text)

        # Get filesystem size after extend
        df_after = process.run("df -B1 %s | tail -1" % self.mount_loc,
                               shell=True)
        size_after = int(df_after.stdout_text.split()[1])
        self.log.info("Filesystem size after extend: %d bytes (%.2f MB)",
                      size_after, size_after / (1024 * 1024))

        # Verify size increase
        if size_after <= size_before:
            self.fail("Filesystem size did not increase after extend. "
                      "Before: %d bytes, After: %d bytes" %
                      (size_before, size_after))

        size_increase = size_after - size_before
        size_increase_mb = size_increase / (1024 * 1024)
        size_increase_percent = (size_increase / size_before) * 100

        self.log.info("=" * 70)
        self.log.info("SIZE VERIFICATION SUCCESSFUL")
        self.log.info("  Size increase: %d bytes", size_increase)
        self.log.info("  Size increase: %.2f MB", size_increase_mb)
        self.log.info("  Percentage increase: %.2f%%", size_increase_percent)
        self.log.info("=" * 70)

        # Display final filesystem info
        result = process.run("df -h %s" % self.mount_loc, shell=True)
        self.log.info("Final filesystem status:\n%s", result.stdout_text)

    def _resize_filesystem(self, device):
        """
        Resize filesystem after LV extension.

        Args:
            device: Device path of the filesystem to resize
        """
        try:
            if self.fs_name in ['ext4', 'ext3']:
                process.run("resize2fs %s" % device, shell=True)
            elif self.fs_name == 'xfs':
                process.run("xfs_growfs %s" % self.mount_loc, shell=True)
            elif self.fs_name == 'btrfs':
                process.run("btrfs filesystem resize max %s" % self.mount_loc,
                            shell=True)
        except process.CmdError as err:
            self.fail("Failed to resize filesystem: %s" % err)

        self.log.info("Filesystem resized successfully")

    def test(self):
        """
        Main test execution: orchestrates all test steps.
        """
        self.log.info("\n" + "=" * 70)
        self.log.info("SOFTWARE RAID REBUILD + SYNC + LVM EXTEND TEST")
        self.log.info("=" * 70 + "\n")

        # Execute test steps
        self.raid_creation_and_sync()
        self.raid_rebuild_and_sync()
        self.lvm_setup_on_raid()
        self.lvm_extend_and_verify()

        self.log.info("\n" + "=" * 70)
        self.log.info("ALL TESTS COMPLETED SUCCESSFULLY!")
        self.log.info("=" * 70 + "\n")

    def tearDown(self):
        """
        Cleanup test environment: unmount filesystem, remove LVM and RAID.
        """
        self.log.info("\n" + "=" * 70)
        self.log.info("Cleaning up test environment...")
        self.log.info("=" * 70)

        # Unmount filesystem
        try:
            result = process.run("umount %s" % self.mount_loc,
                                 shell=True, ignore_status=True)
            if result.exit_status == 0:
                self.log.info("Filesystem unmounted successfully")
        except Exception as err:
            self.log.warning("Error unmounting filesystem: %s", err)

        # Remove Logical Volume
        try:
            if lv_utils.lv_check(self.vg_name, self.lv_name):
                lv_utils.lv_remove(self.vg_name, self.lv_name)
                self.log.info("Logical Volume removed successfully")
        except Exception as err:
            self.log.warning("Error removing LV: %s", err)

        # Remove Volume Group
        try:
            if lv_utils.vg_check(self.vg_name):
                lv_utils.vg_remove(self.vg_name)
                self.log.info("Volume Group removed successfully")
        except Exception as err:
            self.log.warning("Error removing VG: %s", err)

        # Stop and clean RAID
        if hasattr(self, "sraid"):
            try:
                self.sraid.stop()
                self.sraid.clear_superblock()
                self.log.info("RAID array stopped and cleaned successfully")
            except Exception as err:
                self.log.warning("Error cleaning RAID: %s", err)

        self.log.info("Cleanup completed")
        self.log.info("=" * 70 + "\n")
