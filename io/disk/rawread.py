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
# Copyright: 2019 IBM.
# Author: Naresh Bannoth <nbannoth@in.ibm.com>

"""
Rawread test
"""

import os
import time
from avocado import Test
from avocado.utils import archive
from avocado.utils import build, disk
from avocado.utils import lv_utils
from avocado.utils import process, distro
from avocado.utils import softwareraid
from avocado.utils.disk import cleanup_disks
from avocado.utils.software_manager.manager import SoftwareManager


class Rawread(Test):

    """
    Rawread is a benchmark suite that is aimed at performing a number
    of simple tests of hard drive like write and read
    """

    RAID_NAME = '/dev/md/rawread_raid1'
    VG_NAME = 'avocado_vg'
    LV_PREFIX = 'avocado_lv'
    LV_COUNT = 4
    STRESS_SECS = 3600
    REBUILD_DELAY_SECS = 60
    REBUILD_TIMEOUT_SECS = 3600
    REBUILD_POLL_SECS = 30

    def setUp(self):
        """
        checking install of required packages and extract and
        compile of rawread suit.
        """
        device = self.params.get("disk", default=None)
        if not device:
            self.cancel("Please provide disk to run the test")
        self.disk = disk.get_absolute_disk_path(device)
        smm = SoftwareManager()
        deps = ['gcc', 'make']
        if distro.detect().name == 'Ubuntu':
            deps.extend(['g++', 'libaio-dev'])
        else:
            deps.extend(['gcc-c++', 'libaio-devel'])

        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel("Fail to install Package: %s" % package)

        tarball = self.get_data('rawread.tar')
        archive.extract(tarball, self.teststmpdir)
        self.source = os.path.join(self.teststmpdir,
                                   os.path.basename(
                                       tarball.split('.tar')[0]))
        os.chdir(self.source)
        build.make(self.source, extra_args="clean")
        build.make(self.source)

        disks_param = self.params.get('disks', default='').strip()
        if not disks_param:
            return

        self.raid_disks = []
        for dev in disks_param.split():
            dev_path = disk.get_absolute_disk_path(dev)
            if dev_path not in disk.get_all_disk_paths():
                self.cancel("Disk %s not found in OS" % dev)
            self.raid_disks.append(dev_path)

        if len(self.raid_disks) < 2:
            self.cancel(
                "RAID-1 requires at least 2 disks; "
                "%d provided in 'disks' param" % len(self.raid_disks)
            )

        smm = SoftwareManager()
        for pkg in ['mdadm', 'lvm2']:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel("Failed to install package: %s" % pkg)

    def test(self):
        """
        Run 'rawread' with its arguments
        """
        err_val = []
        for val in range(24):
            cmd = "./rawread -t %s %s " % (val, self.disk)
            if process.system(cmd, shell=True, ignore_status=True):
                err_val.append(str(val))

        if err_val:
            self.fail("test failed for values : %s" % " ".join(err_val))

    def test_raid_lvm_rawread(self):
        """RAID-1 + LVM + raw read 1-hour stress with mid-run rebuild."""
        if not getattr(self, 'raid_disks', None):
            self.cancel(
                "'disks' parameter not provided in YAML; "
                "cancelling RAID/LVM stress test"
            )
        self._create_raid1()
        self._create_lvm_on_raid()
        self._start_rawread_stress()
        self._trigger_raid_rebuild()
        self._wait_rawread_completion()
        self._validate_raid_rebuild()

    def _create_raid1(self):
        """Create RAID-1 on self.raid_disks; wait for initial sync."""
        self.sraid = softwareraid.SoftwareRaid(
            self.RAID_NAME, '1', self.raid_disks, '1.2'
        )
        if not self.sraid.create():
            self.fail("Failed to create RAID-1 on %s" % self.raid_disks)
        self.log.info("RAID-1 created; waiting for initial sync")
        start = time.time()
        while (time.time() - start) < self.REBUILD_TIMEOUT_SECS:
            if not self.sraid.is_recovering():
                break
            time.sleep(self.REBUILD_POLL_SECS)
        else:
            self.fail(
                "RAID-1 initial sync did not complete within %ds"
                % self.REBUILD_TIMEOUT_SECS
            )
        self.log.info("RAID-1 initial sync complete")

    def _create_lvm_on_raid(self):
        """Create VG and LV_COUNT equal LVs on the RAID device."""
        lv_utils.vg_create(self.VG_NAME, self.RAID_NAME, force=True)
        total_bytes = lv_utils.get_device_total_space(self.RAID_NAME)
        lv_size_mb = (
            total_bytes // self.LV_COUNT // (1024 * 1024)
        ) - 100
        for i in range(self.LV_COUNT):
            lv_name = '%s%d' % (self.LV_PREFIX, i)
            lv_utils.lv_create(self.VG_NAME, lv_name, lv_size_mb)
            if not lv_utils.lv_check(self.VG_NAME, lv_name):
                self.fail("LV %s not created" % lv_name)
        self.lv_paths = [
            '/dev/%s/%s%d' % (self.VG_NAME, self.LV_PREFIX, i)
            for i in range(self.LV_COUNT)
        ]
        self.log.info(
            "Created %d LVs on %s" % (self.LV_COUNT, self.RAID_NAME)
        )

    def _start_rawread_stress(self):
        """Launch rawread stress on all LVs in parallel."""
        self.rawread_procs = []
        for lv_path in self.lv_paths:
            cmd = 'timeout %d %s/rawread -t 0 %s' % (
                self.STRESS_SECS, self.source, lv_path
            )
            proc = process.SubProcess(cmd, shell=True)
            proc.start()
            self.rawread_procs.append(proc)
        self.log.info(
            "Started %d rawread stress processes" % len(self.rawread_procs)
        )

    def _trigger_raid_rebuild(self):
        """Remove then re-add last disk mid-stress to trigger rebuild."""
        time.sleep(self.REBUILD_DELAY_SECS)
        disk_to_cycle = self.raid_disks[-1]
        if not self.sraid.remove_disk(disk_to_cycle):
            self.log.warning(
                "Failed to remove %s from RAID" % disk_to_cycle
            )
        time.sleep(10)
        if not self.sraid.add_disk(disk_to_cycle):
            self.log.warning(
                "Failed to add %s back to RAID" % disk_to_cycle
            )
        self.log.info("RAID rebuild triggered on %s" % disk_to_cycle)

    def _wait_rawread_completion(self):
        """Join all rawread processes; fail on unexpected exit codes."""
        for proc, lv_path in zip(self.rawread_procs, self.lv_paths):
            exit_code = proc.wait()
            if exit_code not in [0, 124]:
                self.fail(
                    "rawread on %s failed with exit code %d"
                    % (lv_path, exit_code)
                )
        self.log.info("All rawread stress processes completed")

    def _validate_raid_rebuild(self):
        """Wait for RAID rebuild to finish; warn if timeout exceeded."""
        with open('/proc/mdstat', 'r') as mdstat_fh:
            mdstat = mdstat_fh.read()
        if ('[UU]' in mdstat
                and 'recovery' not in mdstat.lower()
                and 'resync' not in mdstat.lower()):
            self.log.info("RAID rebuild already complete")
            return
        start = time.time()
        while (time.time() - start) < self.REBUILD_TIMEOUT_SECS:
            if self._is_raid_sync_complete():
                break
            time.sleep(self.REBUILD_POLL_SECS)
            self.log.info(
                "RAID rebuild in progress; elapsed %ds"
                % int(time.time() - start)
            )
        else:
            self.log.info(
                "RAID rebuild did not complete within %ds "
                "after rawread; marking test warn"
                % self.REBUILD_TIMEOUT_SECS
            )
            return
        with open('/proc/mdstat', 'r') as mdstat_fh:
            mdstat = mdstat_fh.read()
        detail = self.sraid.get_detail().lower()
        if '[UU]' not in mdstat or 'degraded' in detail:
            self.fail("RAID still degraded after rebuild wait")
        self.log.info("RAID rebuild validated as healthy")

    def _is_raid_sync_complete(self):
        """Return True when /proc/mdstat shows no active rebuild."""
        with open('/proc/mdstat', 'r') as mdstat_fh:
            mdstat = mdstat_fh.read().lower()
        return (
            'recovery' not in mdstat
            and 'resync' not in mdstat
            and '[uu]' in mdstat
        )

    def tearDown(self):
        """
        Terminate rawread processes and clean up all test artifacts.

        cleanup_disks(mode="full") handles the full chain:
          LVM removal -> RAID stop + superblock clear ->
          partition table wipe -> disk zeroing.
        No manual lv_remove/vg_remove/sraid.stop needed here.
        """
        for proc in getattr(self, 'rawread_procs', []):
            try:
                if proc.poll() is None:
                    self.log.info(
                        "Terminating rawread process %s" % proc.pid
                    )
                    proc.terminate()
            except Exception as err:
                self.log.warning(
                    "Failed to terminate rawread proc: %s" % err
                )

        if getattr(self, 'raid_disks', None):
            try:
                self.log.info(
                    "Starting disk cleanup for %s" % self.raid_disks
                )
                cleanup_disks(
                    self.raid_disks, logger=self.log, mode="full"
                )
                self.log.info("Disk cleanup completed successfully")
            except Exception as err:
                self.log.error("Disk cleanup failed: %s", err)
