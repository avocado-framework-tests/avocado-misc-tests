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
#
# Copyright: 2016 IBM
# Author: Venkat Rao B <vrbagal1@linux.vnet.ibm.com>
# Author: Narasimhan V <sim@linux.vnet.ibm.com>


"""
RAID devices are virtual devices created from two or more real block devices.
This allows multiple devices (typically disk drives or partitions thereof) to
be combined into a single device to hold (for example) a single filesystem.
Some RAID levels include redundancy and so can survive some degree of device
failure.

test()             -- For each configured RAID level (driven by yaml mux),
                      creates a RAID array, then on top of it:
                        PV → VG → LV → format (ext4/xfs/btrfs from mux) →
                        mount (mount_dir from yaml) → dd I/O → unmount →
                        remove LV → remove VG → remove PV → stop RAID →
                        wipefs all member disks.
                      Disks are completely clean before the next mux variant.

test_raid_rebuild() -- Creates a RAID array from the main disk list, then:
                        fail one member disk (fail_disk from yaml) →
                        remove the failed disk from the array →
                        add the spare disk (spare_disk from yaml) →
                        wait for full resync →
                        verify array is healthy →
                        full cleanup.
"""

import os
import time

from avocado import Test
from avocado.utils import disk
from avocado.utils import distro
from avocado.utils import lv_utils
from avocado.utils import process
from avocado.utils import softwareraid
from avocado.utils import wait
from avocado.utils.partition import Partition
from avocado.utils.partition import PartitionError
from avocado.utils.software_manager.manager import SoftwareManager


class SoftwareRaid(Test):

    """
    Creates, assembles, and stops md devices using the mdadm tool.

    test()           : full PV→VG→LV→format→mount→IO→unmount→PV/VG/LV
                       removal→RAID stop cycle for every mux combination
                       of raid_level × metadata × filesystem.

    test_raid_rebuild: disk-failure / spare-add / rebuild verification.
    """

    # ------------------------------------------------------------------ setUp
    def setUp(self):
        """
        Install required packages and read test parameters from the yaml file.
        """
        self.disks = []
        self.lv_created = False
        self.fs_mounted = False
        self.err_mesg = []

        smm = SoftwareManager()
        detected_distro = distro.detect()

        # ---- mandatory packages ----
        pkgs = ['mdadm', 'lvm2']
        self.fstype = self.params.get('fs', default='ext4').lower()
        if self.fstype == 'xfs':
            pkgs.append('xfsprogs')
        elif self.fstype == 'btrfs':
            if detected_distro.name == 'Ubuntu':
                ver = int(detected_distro.version.split('.')[0])
            else:
                ver = int(detected_distro.version)
            rel = int(detected_distro.release)
            if detected_distro.name == 'rhel':
                if (ver == 7 and rel >= 4) or ver > 7:
                    self.cancel("btrfs is not supported with RHEL 7.4 onwards")
            if detected_distro.name == 'SuSE':
                pkgs.append('btrfsprogs')
            else:
                pkgs.append('btrfs-progs')

        for pkg in pkgs:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel("Package %s could not be installed" % pkg)

        # ---- disk parameters ----
        disks_raw = (self.params.get('disks', default='').strip()).split()
        if not disks_raw:
            self.cancel('No disks given — set "disks:" in the yaml file')
        for dev in disks_raw:
            self.disks.append(disk.get_absolute_disk_path(dev))

        required_disks = self.params.get('required_disks', default=1)
        self.raidlevel = str(self.params.get('raid', default='0'))
        if len(self.disks) < required_disks:
            self.cancel("Minimum %d disks required for raid%s"
                        % (required_disks, self.raidlevel))

        # ---- spare_disk: extra disk added to array after a failure ----
        spare_disk_raw = self.params.get('spare_disk', default='')
        self.spare_disk = ''
        if spare_disk_raw:
            self.spare_disk = disk.get_absolute_disk_path(
                spare_disk_raw.strip())

        # ---- disk to be marked faulty in test_raid_rebuild ----
        fail_disk_raw = self.params.get('fail_disk', default='')
        self.fail_disk = ''
        if fail_disk_raw:
            self.fail_disk = disk.get_absolute_disk_path(fail_disk_raw.strip())

        # ---- RAID / LVM / FS / mount parameters ----
        raidname = self.params.get('raidname', default='/dev/md/sraid')
        metadata = str(self.params.get('metadata', default='1.2'))
        self.vgname = 'avocado_vg'
        self.lvname = 'avocado_lv'
        self.mount_dir = self.params.get('mount_dir', default='/mnt')

        # RAID device is also the PV/LVM backing device
        self.lv_backing_disk = raidname

        self.sraid = softwareraid.SoftwareRaid(raidname, self.raidlevel,
                                               self.disks, metadata)

        if not os.path.isdir(self.mount_dir):
            os.makedirs(self.mount_dir)

        # sweep any leftover state from a previous run
        self._pre_cleanup()

    # ------------------------------------------------------- pre-cleanup -----

    def _pre_cleanup(self):
        """
        Best-effort cleanup of leftover LVM / RAID state before the test
        starts, mirroring the pattern used in bonnie.py / ltp_fs.py.
        """
        self.log.info("Pre-cleaning leftover LVM/RAID state ...")

        lv_map_path = '/dev/mapper/%s-%s' % (self.vgname, self.lvname)
        for dev in [lv_map_path, self.lv_backing_disk] + self.disks:
            self._wipe_fs(dev)

        if lv_utils.lv_check(self.vgname, self.lvname):
            self.log.info("Found existing LV — removing it")
            self._do_delete_lvm()
        elif lv_utils.vg_check(self.vgname):
            self.log.info("Found existing VG — removing it")
            lv_utils.vg_remove(self.vgname)

        if self.sraid.exists():
            self.log.info("Found existing RAID — stopping it")
            self._do_stop_raid()

        self.log.info("Pre-cleanup done")

    def _wipe_fs(self, dev):
        """
        Unmount *dev* / mount_dir if mounted, then wipe filesystem signatures.
        Mirrors the delete_fs() helpers in bonnie.py and ltp_fs.py.
        """
        def _unmount_disk():
            process.system('umount %s' % dev, shell=True, ignore_status=True)
            return not disk.is_disk_mounted(dev)

        def _unmount_dir():
            process.system('umount %s' % self.mount_dir,
                           shell=True, ignore_status=True)
            return not disk.is_dir_mounted(self.mount_dir)

        def _wipe():
            process.system('wipefs -af %s' % dev,
                           shell=True, ignore_status=True)
            return not disk.fs_exists(dev)

        if disk.is_disk_mounted(dev):
            wait.wait_for(_unmount_disk, timeout=15)
        if disk.is_dir_mounted(self.mount_dir):
            wait.wait_for(_unmount_dir, timeout=15)
        if disk.fs_exists(dev):
            wait.wait_for(_wipe, timeout=15)

    def _do_stop_raid(self):
        """Stop the RAID array and clear superblocks on all member disks."""
        def _stopped():
            self.sraid.stop()
            self.sraid.clear_superblock()
            for d in self.disks:
                process.system('wipefs -af %s' % d,
                               shell=True, ignore_status=True)
            return not self.sraid.exists()

        if not wait.wait_for(_stopped, timeout=30):
            self.log.warning("Could not fully stop RAID %s",
                             self.lv_backing_disk)

    # --------------------------------------------------------- helper: LVM ---

    def create_lvm(self, backing_device):
        """
        Create PV → VG → LV on *backing_device*.

        Explicit pvcreate is performed first so the Physical Volume is
        properly initialised before the Volume Group is created on top of it.
        Returns the LV device path (/dev/<vgname>/<lvname>).
        Uses ~45 % of the available space.
        """
        # Step 1: Physical Volume
        self.log.info("Creating PV on %s", backing_device)
        ret = process.run('pvcreate -f %s' % backing_device,
                          shell=True, ignore_status=True)
        if ret.exit_status != 0:
            self.fail("pvcreate failed on %s: %s"
                      % (backing_device, ret.stderr_text))

        # Step 2: Volume Group
        self.log.info("Creating VG '%s' on %s", self.vgname, backing_device)
        lv_utils.vg_create(self.vgname, backing_device, force=True)
        if not lv_utils.vg_check(self.vgname):
            self.fail("VG %s was not created" % self.vgname)

        # Step 3: Logical Volume (~45 % of total space)
        total_mb = lv_utils.get_device_total_space(
            backing_device) / (1024 * 1024)
        lv_size = int(total_mb * 45 / 100) or 512
        self.log.info("Creating LV '%s' size=%dM", self.lvname, lv_size)
        lv_utils.lv_create(self.vgname, self.lvname, lv_size)
        if not lv_utils.lv_check(self.vgname, self.lvname):
            self.fail("LV %s was not created" % self.lvname)

        self.lv_created = True
        return '/dev/%s/%s' % (self.vgname, self.lvname)

    def _do_delete_lvm(self):
        """
        Internal: Remove LV → VG → PV and wipe all residual LVM metadata
        from the backing device so the disk is clean for the next RAID.
        """
        def _removed():
            if lv_utils.lv_check(self.vgname, self.lvname):
                lv_utils.lv_remove(self.vgname, self.lvname)
                time.sleep(2)
            if lv_utils.vg_check(self.vgname):
                lv_utils.vg_remove(self.vgname)
            return not lv_utils.vg_check(self.vgname)

        if not wait.wait_for(_removed, timeout=30):
            self.log.warning("VG %s removal timed out", self.vgname)

        # Remove Physical Volume label
        self.log.info("Removing PV label from %s", self.lv_backing_disk)
        process.system('pvremove -ff %s' % self.lv_backing_disk,
                       shell=True, ignore_status=True)

        # Wipe any remaining LVM2_member signature
        cmd = 'blkid -o value -s TYPE %s' % self.lv_backing_disk
        out = process.system_output(cmd, shell=True,
                                    ignore_status=True).decode('utf-8').strip()
        if out == 'LVM2_member':
            process.system('wipefs -af %s' % self.lv_backing_disk,
                           shell=True, ignore_status=True)

    def delete_lvm(self):
        """
        Public: Remove LV → VG → PV, wipe LVM metadata, reset lv_created flag.
        """
        self.log.info("Removing LV '%s', VG '%s', PV on %s",
                      self.lvname, self.vgname, self.lv_backing_disk)
        self._do_delete_lvm()
        self.lv_created = False

    # --------------------------------------------------------- helper: FS ----

    def create_fs(self, lv_path):
        """
        Format *lv_path* with self.fstype and mount it on self.mount_dir.
        fstype is read from the yaml mux (ext4 / xfs / btrfs).
        mount_dir is read from the yaml (default /mnt).
        """
        self.log.info("Formatting %s as %s", lv_path, self.fstype)
        self.part_obj = Partition(lv_path, mountpoint=self.mount_dir)
        self.part_obj.unmount()
        self.part_obj.mkfs(self.fstype)
        try:
            self.part_obj.mount()
            self.fs_mounted = True
            self.log.info("Mounted %s on %s", lv_path, self.mount_dir)
        except PartitionError:
            self.fail("Mounting %s on %s failed" % (lv_path, self.mount_dir))

    def delete_fs(self):
        """
        Unmount self.mount_dir and wipe the filesystem signature from the LV.
        """
        lv_path = '/dev/%s/%s' % (self.vgname, self.lvname)

        if self.fs_mounted:
            self.log.info("Unmounting %s", self.mount_dir)

            def _unmount_dir():
                try:
                    self.part_obj.unmount()
                except Exception:
                    process.system('umount -f %s' % self.mount_dir,
                                   shell=True, ignore_status=True)
                return not disk.is_dir_mounted(self.mount_dir)

            if not wait.wait_for(_unmount_dir, timeout=30):
                self.log.warning("Could not unmount %s cleanly",
                                 self.mount_dir)
            self.fs_mounted = False

        # wipe filesystem signatures from the LV so mkfs succeeds next time
        if disk.fs_exists(lv_path):
            process.system('wipefs -af %s' % lv_path,
                           shell=True, ignore_status=True)

    # --------------------------------------------------------- helper: IO ----

    def run_io(self):
        """
        Run a dd write + read pass on the mounted filesystem to exercise the
        RAID -> LVM -> FS stack.
        Writes 256 MiB with O_DIRECT + fsync, reads back, then removes the
        test file.
        """
        target = os.path.join(self.mount_dir, 'testfile')
        self.log.info("Running dd write I/O to %s", target)
        write_cmd = ('dd if=/dev/urandom of=%s bs=1M count=256 '
                     'oflag=direct conv=fsync' % target)
        ret = process.run(write_cmd, shell=True, ignore_status=True)
        if ret.exit_status != 0:
            self.fail("dd write failed: %s" % ret.stderr_text)

        self.log.info("Running dd read I/O from %s", target)
        read_cmd = 'dd if=%s of=/dev/null bs=1M iflag=direct' % target
        ret = process.run(read_cmd, shell=True, ignore_status=True)
        if ret.exit_status != 0:
            self.fail("dd read failed: %s" % ret.stderr_text)

        self.log.info("I/O complete — removing test file")
        os.remove(target)

    # ------------------------------------------------------- test: main ------

    def test(self):
        """
        Full cycle for one (raid_level x metadata x fs) mux combination:

          1.  Create RAID array
          2.  Create PV on the RAID device
          3.  Create VG on the PV
          4.  Create LV in the VG
          5.  Format LV with filesystem from yaml mux (ext4 / xfs / btrfs)
          6.  Mount on mount_dir from yaml (default /mnt)
          7.  Run dd I/O (write + read)
          8.  Stop I/O, unmount filesystem, wipe FS signatures
          9.  Remove LV
          10. Remove VG
          11. Remove PV
          12. Stop RAID array
          13. Zero superblocks + wipefs all member disks (disks are clean
              for the next mux iteration)

        Avocado mux drives every combination of raidlevel x metadata x fs
        automatically — no manual loop needed.
        """
        self.log.info("=== test: raid%s / metadata=%s / fs=%s ===",
                      self.raidlevel,
                      self.params.get('metadata', default='1.2'),
                      self.fstype)

        # 1. Create RAID
        if not self.sraid.create():
            self.fail("Failed to create RAID%s" % self.raidlevel)
        self.log.info("RAID%s created successfully", self.raidlevel)

        # 2-4. PV -> VG -> LV on top of the RAID device
        lv_path = self.create_lvm(self.lv_backing_disk)

        # 5-6. Format (fstype from mux) + mount (mount_dir from yaml)
        self.create_fs(lv_path)

        # 7. dd I/O
        self.run_io()

        # 8. Stop I/O (dd already returned) then unmount
        self.log.info("Stopping I/O and unmounting filesystem ...")
        self.delete_fs()

        # 9-11. Remove LV -> VG -> PV
        self.delete_lvm()

        # 12-13. Stop RAID, zero superblocks, wipefs all member disks
        self.log.info("Stopping RAID%s and clearing superblocks ...",
                      self.raidlevel)
        if not self.sraid.stop():
            self.fail("Failed to stop RAID%s" % self.raidlevel)
        self.sraid.clear_superblock()
        for d in self.disks:
            process.system('wipefs -af %s' % d,
                           shell=True, ignore_status=True)

        self.log.info("=== test: raid%s / fs=%s PASSED ===",
                      self.raidlevel, self.fstype)

    # -------------------------------------------------- test: raid_rebuild ---

    def test_raid_rebuild(self):
        """
        RAID rebuild / disk replacement validation:

          1.  Create RAID array using 'disks' from yaml
          2.  Simulate disk failure: mark 'fail_disk' (from yaml) as faulty
          3.  Remove the failed disk from the array
          4.  Add 'spare_disk' (from yaml) into the array
          5.  Wait for full resync (poll /proc/mdstat, timeout 600 s)
          6.  Verify array is healthy (mdadm --detail shows clean / active)
          7.  Stop RAID, zero superblocks, wipefs all disks

        yaml keys required for this test:
          fail_disk  : one of the disks in 'disks' that will be failed
          spare_disk : an extra disk NOT in 'disks', added after the failure

        The test cancels if:
          - fail_disk or spare_disk is not set in yaml
          - raidlevel is 0 or linear (no redundancy, rebuild impossible)
          - fail_disk is not a member of self.disks
        """
        if not self.fail_disk:
            self.cancel("'fail_disk' not set in yaml — "
                        "cannot run test_raid_rebuild")
        if not self.spare_disk:
            self.cancel("'spare_disk' not set in yaml — "
                        "cannot run test_raid_rebuild")
        if self.raidlevel in ['0', 'linear']:
            self.cancel("RAID%s does not support rebuild/redundancy"
                        % self.raidlevel)
        if self.fail_disk not in self.disks:
            self.cancel("fail_disk '%s' is not in the 'disks' list"
                        % self.fail_disk)

        self.log.info("=== test_raid_rebuild: raid%s ===", self.raidlevel)

        # 1. Create RAID (members only — no pre-built-in spare)
        if not self.sraid.create():
            self.fail("Failed to create RAID%s for rebuild test"
                      % self.raidlevel)
        self.log.info("RAID%s created for rebuild test", self.raidlevel)

        # 2. Mark fail_disk as faulty
        self.log.info("Marking %s as faulty in %s",
                      self.fail_disk, self.lv_backing_disk)
        ret = process.run(
            'mdadm %s --fail %s' % (self.lv_backing_disk, self.fail_disk),
            shell=True, ignore_status=True)
        if ret.exit_status != 0:
            self.fail("Failed to mark %s faulty: %s"
                      % (self.fail_disk, ret.stderr_text))

        # 3. Remove the failed disk from the array
        self.log.info("Removing failed disk %s from %s",
                      self.fail_disk, self.lv_backing_disk)
        ret = process.run(
            'mdadm %s --remove %s' % (self.lv_backing_disk, self.fail_disk),
            shell=True, ignore_status=True)
        if ret.exit_status != 0:
            self.fail("Failed to remove %s from array: %s"
                      % (self.fail_disk, ret.stderr_text))

        # 4. Add spare_disk to the array — triggers rebuild automatically
        self.log.info("Adding spare disk %s to %s",
                      self.spare_disk, self.lv_backing_disk)
        ret = process.run(
            'mdadm %s --add %s' % (self.lv_backing_disk, self.spare_disk),
            shell=True, ignore_status=True)
        if ret.exit_status != 0:
            self.fail("Failed to add spare %s to array: %s"
                      % (self.spare_disk, ret.stderr_text))

        # 5. Wait for resync / recovery to complete
        self.log.info("Waiting for RAID rebuild to complete ...")

        def _resync_done():
            out = process.system_output(
                'cat /proc/mdstat', shell=True,
                ignore_status=True).decode('utf-8')
            return 'resync' not in out and 'recovery' not in out

        if not wait.wait_for(_resync_done, timeout=600, step=15):
            self.fail("RAID rebuild did not complete within 600 s")

        # 6. Verify array is healthy
        detail_out = process.system_output(
            'mdadm --detail %s' % self.lv_backing_disk,
            shell=True, ignore_status=True).decode('utf-8')
        self.log.info("mdadm --detail:\n%s", detail_out)
        if 'State : clean' not in detail_out and \
                'State : active' not in detail_out:
            self.fail("RAID array not clean/active after rebuild:\n%s"
                      % detail_out)
        self.log.info("RAID rebuild verified — array is healthy")

        # 7. Stop RAID, zero superblocks, wipe all disks
        all_disks = self.disks + ([self.spare_disk] if self.spare_disk else [])
        if not self.sraid.stop():
            self.fail("Failed to stop RAID%s after rebuild test"
                      % self.raidlevel)
        self.sraid.clear_superblock()
        for d in all_disks:
            process.system('wipefs -af %s' % d,
                           shell=True, ignore_status=True)

        self.log.info("=== test_raid_rebuild: raid%s PASSED ===",
                      self.raidlevel)

    # ------------------------------------------------------- tearDown --------

    def tearDown(self):
        """
        Best-effort cleanup — always runs regardless of test outcome:
          unmount FS -> remove LV/VG/PV -> stop RAID -> wipefs all disks.
        """
        if self.fs_mounted:
            self.delete_fs()
        if self.lv_created:
            self.delete_lvm()
        if hasattr(self, 'sraid'):
            self.sraid.stop()
            self.sraid.clear_superblock()
            all_disks = self.disks + ([self.spare_disk]
                                      if self.spare_disk else [])
            for d in all_disks:
                process.system('wipefs -af %s' % d,
                               shell=True, ignore_status=True)
        if self.err_mesg:
            self.log.warning("Issues during test: %s", self.err_mesg)
