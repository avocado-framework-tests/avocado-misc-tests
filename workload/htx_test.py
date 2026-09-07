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
# Copyright: 2017 IBM
# Author: Praveen K Pandey <praveen@linux.vnet.ibm.com>
#         Naresh Bannoth <nbannoth@in.ibm.com>
#         Maram Srimannarayana Murthy <msmurthy@linux.vnet.ibm.com>
#         Priyanka Behera <Priyanka.Behera2@ibm.com>
#

"""
HTX Test

Stress-tests IBM Power hardware using the HTX (Hardware Test eXecutive)
framework.  Supports generic MDT-based runs (CPU, memory, pmem, isst) as
well as targeted IO device stress via the respective YAML
parameters.

"""

import os
import re
import shutil
import time

from avocado import Test
from avocado.utils import disk
from avocado.utils import distro
from avocado.utils import multipath
from avocado.utils import process
from avocado.utils.software_manager.manager import SoftwareManager

HTX_INSTALL_PATH = '/usr/lpp/htx'


class HtxTest(Test):
    """
    HTX [Hardware Test eXecutive] is a test tool suite.  The goal of HTX is
    to stress test the system by exercising all hardware components
    concurrently in order to uncover any hardware design flaws and
    hardware-hardware or hardware-software interaction issues.

    :see: https://github.com/open-power/HTX.git
    """

    def setUp(self):
        """
        Setup
        """
        self.detected_distro = distro.detect()
        if 'ppc64' not in self.detected_distro.arch:
            self.cancel("Supported only on Power Architecture")

        self.mdt_file = self.params.get('mdt_file', default='mdt.mem')
        self.time_limit = int(self.params.get('time_interval', default=2)) * 60
        self.htx_disks = self.params.get('htx_disks', default=None)
        self.run_all = self.params.get('all', default=False)
        self.rpm_link = self.params.get('htx_rpm_link', default=None)
        self.dist_name = None

        self.block_device = ''
        if self.htx_disks and not self.run_all:
            self.block_device = self._resolve_block_devices(self.htx_disks)

        current_test = str(self.name.name).split('.')[-1]

        if current_test == 'test_start':
            self.setup_htx()

        # LVM and RAID tests create their own virtual devices;
        # the base MDT file is not required before they run.
        _no_mdt_check = (
            'test_lvm_create',
            'test_software_raid_create',
            'test_htx_on_software_raid_lvm',
        )
        if current_test not in _no_mdt_check:
            if not os.path.exists(f'{HTX_INSTALL_PATH}/mdt/{self.mdt_file}'):
                self.cancel(f"MDT file {self.mdt_file} not found")

    @staticmethod
    def _resolve_block_devices(raw_devices):
        """
        Resolve raw device names or paths to bare basenames for htxcmdline.
        DM multipath devices are mapped to their ``mpathX`` name.

        :param raw_devices: Whitespace-separated device names or paths.
        :returns: Space-separated string of resolved device basenames.
        :rtype: str
        """
        resolved = []
        for dev in raw_devices.split():
            dev_path = disk.get_absolute_disk_path(dev)
            dev_base = os.path.basename(os.path.realpath(dev_path))
            if 'dm' in dev_base:
                dev_base = multipath.get_mpath_from_dm(dev_base)
            resolved.append(dev_base)
        return ' '.join(resolved)

    def install_latest_htx_rpm(self):
        """
        Search for the latest htx-version for the intended distro and
        install the same.
        """
        if self.rpm_link.endswith('.rpm'):
            latest_htx_rpm = os.path.basename(self.rpm_link)
            cmd = f'curl -kL {self.rpm_link} -o /tmp/{latest_htx_rpm}'
        else:
            distro_pattern = f'{self.dist_name}{self.detected_distro.version}'
            temp_string = process.getoutput(
                f'curl --silent -kL {self.rpm_link}',
                verbose=False, shell=True, ignore_status=True)
            matching_htx_versions = re.findall(
                r'(?<=\>)htx\w*[-]\d*[-]\w*[.]\w*[.]\w*', str(temp_string))
            distro_specific_htx_versions = [
                r for r in matching_htx_versions if distro_pattern in r]
            distro_specific_htx_versions.sort(reverse=True)
            if not distro_specific_htx_versions:
                self.cancel(
                    f"No HTX RPM found for {distro_pattern}"
                    f" at {self.rpm_link}")
            latest_htx_rpm = distro_specific_htx_versions[0]
            cmd = (f'curl -kL {self.rpm_link}/{latest_htx_rpm}'
                   f' -o /tmp/{latest_htx_rpm}')

        if process.system(cmd, shell=True, ignore_status=True):
            self.cancel(f"RPM download failed: {latest_htx_rpm}")

        tmp_rpm = f'/tmp/{latest_htx_rpm}'

        if process.system(
                f'rpm -ivh --nodeps --force {tmp_rpm}',
                shell=True, ignore_status=True):
            self.cancel(f"RPM installation failed: {tmp_rpm}")

        self.log.info("HTX RPM %s installed successfully", latest_htx_rpm)
        process.run(f'rm -rf {tmp_rpm}', ignore_status=True)

    def _get_distro_packages(self):
        """
        Return the list of distro-specific packages required to build HTX.

        :returns: List of package name strings.
        :rtype: list
        :raises: Cancels the test if the distro is unsupported.
        """
        # ndctl is required only for pmem MDT runs; on SuSE it may not be
        # available in the default repos (e.g. NVMf-only setups).  It is
        # handled as a best-effort install in setup_htx() rather than a
        # hard dependency here.
        packages = ['gcc', 'make']
        name = self.detected_distro.name
        if name in ['centos', 'fedora', 'rhel', 'redhat']:
            packages.extend(['gcc-c++', 'ncurses-devel', 'tar', 'ndctl'])
        elif name == 'Ubuntu':
            packages.extend(['libncurses5', 'g++',
                             'ncurses-dev', 'libncurses-dev', 'tar', 'ndctl'])
        elif name == 'SuSE':
            packages.extend(['libncurses5', 'gcc-c++', 'ncurses-devel', 'tar'])
        else:
            self.cancel(f"Test not supported in {name}")
        return packages

    def _install_htx_rpm_if_needed(self, smm):
        """
        Install the HTX RPM if the correct version is not already present.
        Removes any mismatched existing installation first.

        :param smm: SoftwareManager instance used for RPM checks.
        """
        rpm_check = f'htx{self.dist_name}{self.detected_distro.version}'
        ins_htx = process.system_output(
            'rpm -qa | grep htx', shell=True,
            ignore_status=True).decode().strip()

        if ins_htx:
            if smm.check_installed(rpm_check):
                self.log.info("Using existing HTX RPM: %s", rpm_check)
                return
            self.log.info("Clearing existing HTX RPM: %s", ins_htx)
            process.system(f'rpm -e {ins_htx}',
                           shell=True, ignore_status=True)
            if os.path.exists(HTX_INSTALL_PATH):
                shutil.rmtree(HTX_INSTALL_PATH)

        self.rpm_link = self.params.get('htx_rpm_link', default=None)
        if self.rpm_link:
            self.install_latest_htx_rpm()
        else:
            self.cancel("htx_rpm_link is required for RPM install")

    def setup_htx(self):
        """
        Builds HTX
        """
        smm = SoftwareManager()
        for pkg in self._get_distro_packages():
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel(f"Cannot install {pkg}")

        # ndctl is optional: needed for pmem MDT runs but not for block/NVMf.
        # Log a warning if unavailable rather than cancelling.
        if not smm.check_installed('ndctl') and not smm.install('ndctl'):
            self.log.info("ndctl not available; pmem MDT runs will fail "
                          "but block/NVMf tests are unaffected")

        self.dist_name = self.detected_distro.name.lower()
        if self.dist_name == 'suse':
            self.dist_name = 'sles'
        self._install_htx_rpm_if_needed(smm)

        self.log.info("Stopping any existing HXE exerciser process")
        hxe_pid = process.getoutput('pgrep -f hxe', ignore_status=True)
        if hxe_pid.strip():
            self.log.info("HXE running with PID %s; shutting down",
                          hxe_pid.strip())
            process.run('hcl -shutdown', ignore_status=True)
            time.sleep(20)

        self._ensure_daemon_running()

        self.log.info("Creating HTX MDT files")
        process.run('htxcmdline -createmdt', ignore_status=True)
        mdt_path = f'{HTX_INSTALL_PATH}/mdt/{self.mdt_file}'
        if not os.path.exists(mdt_path):
            self.log.info("MDT %s not found; retrying named creation",
                          self.mdt_file)
            process.run(f'htxcmdline -createmdt -mdt {self.mdt_file}',
                        ignore_status=True)
            if not os.path.exists(mdt_path):
                self.cancel(f"MDT file {self.mdt_file} could not be created")

    def _get_daemon_state(self):
        """
        Query and return the current HTX daemon status string.
        """
        return process.system_output(
            f'{HTX_INSTALL_PATH}/etc/scripts/htx.d status',
            ignore_status=True).decode('utf-8').strip()

    def _ensure_daemon_running(self):
        """
        Start the HTX daemon only if it is not already running.
        """
        self.log.info("Checking HTX daemon state")
        if self._get_daemon_state().split()[-1:] != ['running']:
            self.log.info("HTXD is not running; starting it")
            process.run(f'{HTX_INSTALL_PATH}/etc/scripts/htxd_run',
                        ignore_status=True)
            time.sleep(5)
        else:
            self.log.info("HTXD is already running")

    def _stop_daemon(self):
        """
        Shut down the HTX daemon if it is currently running.
        """
        if self._get_daemon_state().split()[-1:] == ['running']:
            self.log.info("Shutting down HTX daemon")
            process.system(
                f'{HTX_INSTALL_PATH}/etc/scripts/htxd_shutdown',
                ignore_status=True)

    def is_block_device_in_mdt(self, block_device=None, mdt_file=None):
        """
        Return True if all specified block devices appear in the MDT.
        """
        if block_device is None:
            block_device = self.block_device
        if mdt_file is None:
            mdt_file = self.mdt_file
        self.log.info("Checking block devices in MDT %s", mdt_file)
        output = process.system_output(
            f'htxcmdline -query -mdt {mdt_file}',
            ignore_status=True).decode('utf-8')
        missing = [dev for dev in block_device.split() if dev not in output]
        if missing:
            self.log.info("Devices not in MDT %s: %s", mdt_file, missing)
            return False
        self.log.info("All block devices present in MDT %s", mdt_file)
        return True

    def suspend_all_block_device(self, mdt_file=None):
        """
        Suspend all block devices in the MDT.
        """
        if mdt_file is None:
            mdt_file = self.mdt_file
        self.log.info("Suspending all block devices in MDT %s", mdt_file)
        process.system(f'htxcmdline -suspend all -mdt {mdt_file}',
                       ignore_status=True)

    def is_block_device_active(self, block_device=None, mdt_file=None):
        """
        Return True if all specified block devices show ACTIVE.
        """
        if block_device is None:
            block_device = self.block_device
        if mdt_file is None:
            mdt_file = self.mdt_file
        self.log.info("Checking ACTIVE state for: %s", block_device)
        output = process.system_output(
            f'htxcmdline -query {block_device} -mdt {mdt_file}',
            ignore_status=True).decode('utf-8').split('\n')
        device_list = block_device.split()
        active_devices = [
            dev for line in output for dev in device_list
            if dev in line and 'ACTIVE' in line
        ]
        non_active = list(set(device_list) - set(active_devices))
        if non_active:
            self.log.info("Devices not ACTIVE: %s", non_active)
            return False
        self.log.info("All block devices ACTIVE: %s", block_device)
        return True

    def test_start(self):
        """
        Execute HTX with appropriate parameters.
        """
        self.log.info("Selecting MDT file: %s", self.mdt_file)
        process.system(f'htxcmdline -select -mdt {self.mdt_file}',
                       ignore_status=True)

        if self.run_all or not self.htx_disks:
            # No specific devices — activate everything in the MDT.
            self.log.info("Activating MDT: %s", self.mdt_file)
            process.system(f'htxcmdline -activate -mdt {self.mdt_file}',
                           ignore_status=True)
        else:
            # Specific devices requested — verify presence then activate.
            if not self.is_block_device_in_mdt():
                self.log.warning(
                    "Block devices %s not found in MDT %s; "
                    "skipping device-specific activation",
                    self.block_device, self.mdt_file)
            else:
                self.suspend_all_block_device()
                self.log.info("Activating block device(s): %s",
                              self.block_device)
                process.system(
                    f'htxcmdline -activate {self.block_device}'
                    f' -mdt {self.mdt_file}',
                    ignore_status=True)
                if not self.is_block_device_active():
                    self.fail(
                        f"Block devices {self.block_device}"
                        f" failed to reach ACTIVE state")

        self.log.info("Configuring HTX_DR_TEST environment variable")
        process.system('hcl -get_htx_env HTX_DR_TEST', ignore_status=True)
        process.system('hcl -set_htx_env HTX_DR_TEST 1', ignore_status=True)
        process.system('hcl -get_htx_env HTX_DR_TEST', ignore_status=True)

        self.log.info("Starting HTX run on MDT: %s", self.mdt_file)
        process.system(f'htxcmdline -run -mdt {self.mdt_file}',
                       ignore_status=True)

    # ------------------------------------------------------------------
    # Helpers: device release + LVM portability
    # (RHEL / SLES / Ubuntu, FC / vSCSI / NVMe / NVMf)
    # ------------------------------------------------------------------

    def _release_htx_devices(self):
        """
        Suspend all MDT devices and shut down the HTX run.

        When the test suite is run as a single job (test_start → test_lvm_create
        → …), test_start leaves HTX actively running on the raw block devices.
        Any attempt to run pvcreate / mdadm --create on those devices while HTX
        holds them open will fail with "Can't open exclusively / device has a
        signature".  This helper suspends all devices and shuts down the MDT
        run so the raw disks are released before LVM or RAID touches them.
        It is a no-op when HTX is not running.
        """
        self.log.info("Releasing HTX devices before LVM/RAID operations")
        process.system(f'htxcmdline -suspend all -mdt {self.mdt_file}',
                       ignore_status=True)
        process.system(f'htxcmdline -shutdown -mdt {self.mdt_file}',
                       timeout=60, ignore_status=True)
        time.sleep(3)
        # Remove any DM (LVM/RAID) holders sitting on the raw disks from a
        # previous test run before wiping — otherwise wipefs/dd/pvcreate
        # cannot open the devices exclusively.
        if self.htx_disks:
            self._remove_dm_holders(self.htx_disks.split())
        # Wipe signatures so pvcreate / mdadm get a clean device.
        if self.htx_disks:
            for d in self.htx_disks.split():
                dp = d if d.startswith('/') else f'/dev/{d}'
                process.system(f'wipefs -a --force {dp}',
                               shell=True, ignore_status=True)
                process.system(f'dd if=/dev/zero of={dp} bs=4M count=10',
                               shell=True, ignore_status=True)
            process.system('udevadm settle', shell=True, ignore_status=True)
            time.sleep(2)

    def _remove_dm_holders(self, dev_list):
        """
        Remove any device-mapper (LVM VG/LV, dm-X) holders sitting on top of
        the given raw block devices.

        A previous test_lvm_create or test_htx_on_software_raid_lvm run may
        have left a VG/LV intact (e.g. if the process was killed).  While a
        dm holder exists, pvcreate cannot open the underlying device
        exclusively.  This helper tears down the VG/LV stack cleanly before
        the caller wipes or recreates the device.

        :param dev_list: List of raw device paths (e.g. ['/dev/nvme4n8', …]).
        """
        for d in dev_list:
            dp = d if d.startswith('/') else f'/dev/{d}'
            dev_base = os.path.basename(dp)
            holders_dir = f'/sys/block/{dev_base}/holders'
            if not os.path.isdir(holders_dir):
                continue
            for holder in os.listdir(holders_dir):
                holder_path = f'/dev/{holder}'
                self.log.info("Removing DM holder %s on %s", holder_path, dp)
                # Try LVM teardown first (covers dm-X that is an LV)
                process.system(f'dmsetup info {holder_path}',
                               shell=True, ignore_status=True)
                process.system(f'dmsetup remove --force {holder_path}',
                               shell=True, ignore_status=True)
        # Also tear down any leftover htx_vg regardless of holder detection
        process.system('lvremove -f /dev/htx_vg/htx_lv',
                       shell=True, ignore_status=True)
        process.system('vgremove -f htx_vg',
                       shell=True, ignore_status=True)
        process.system('udevadm settle', shell=True, ignore_status=True)

    # ------------------------------------------------------------------
    # Helpers: LVM portability (RHEL / SLES / Ubuntu, FC / vSCSI / NVMe)
    # ------------------------------------------------------------------

    def _lvm_devices_file_remove(self):
        """
        Remove /etc/lvm/devices/system.devices if present.

        SLES 16+ (lvm2 >= 2.03) keeps this file as a whitelist of known PVs.
        Any device absent from it is silently rejected by pvcreate/vgcreate.
        Removing it makes LVM fall back to the global filter (accept all),
        which is required for freshly provisioned NVMe/NVMf/FC/vSCSI devices.
        LVM recreates the file automatically on the next successful pvcreate.
        On RHEL/Ubuntu the file does not exist, so this is a no-op.
        """
        devices_file = '/etc/lvm/devices/system.devices'
        if os.path.exists(devices_file):
            self.log.info("Removing LVM devices whitelist %s to allow new "
                          "block devices (NVMe/FC/vSCSI)", devices_file)
            os.remove(devices_file)

    def _pvcreate(self, dev_path):
        """
        Run pvcreate on *dev_path* in a distro-portable way.

        Older RHEL/multipath stacks need ``--config devices/allow_multipath=1``
        so LVM does not refuse dm devices.  Newer LVM2 (SLES 16+, RHEL 9+)
        no longer recognises that config key.  Try plain pvcreate first; fall
        back with the multipath config flag so both old and new stacks work.
        """
        if process.system(f'pvcreate -ff -y {dev_path}',
                          shell=True, ignore_status=True) == 0:
            return True
        self.log.info("Plain pvcreate failed on %s; retrying with "
                      "devices/allow_multipath=1 (multipath setup)", dev_path)
        return process.system(
            f"pvcreate -ff -y --config 'devices/allow_multipath=1' {dev_path}",
            shell=True, ignore_status=True) == 0

    # ------------------------------------------------------------------
    # Test: HTX on LVM
    # ------------------------------------------------------------------

    def test_lvm_create(self):
        """
        HTX on LVM:
          - Take htx_disks from YAML (first disk used).
          - Create LVM (pvcreate / vgcreate / lvcreate) on that disk.
          - Run HTX on the resulting dm device.
          - Stop HTX and clean up LVM (lvremove / vgremove / pvremove).

        Portable across RHEL/SLES/Ubuntu and FC/vSCSI/NVMe/NVMf devices.
        """
        if not self.htx_disks:
            self.cancel("htx_disks not set; skipping test_lvm_create")

        disk = self.htx_disks.split()[0]
        disk_path = disk if disk.startswith('/') else f'/dev/{disk}'
        vg_name = 'htx_vg'
        lv_name = 'htx_lv'
        lv_path = f'/dev/{vg_name}/{lv_name}'
        mdt_path = f'{HTX_INSTALL_PATH}/mdt/{self.mdt_file}'
        lvm_created = False

        try:
            # --- Release HTX before touching raw devices ---
            # test_start may have left HTX running on these disks; shut it
            # down so pvcreate can open the devices exclusively.
            self._release_htx_devices()
            # --- Create LVM ---
            # Remove the LVM devices whitelist (SLES 16+) so that NVMe/FC/
            # vSCSI devices not yet known to LVM are not silently rejected.
            self._lvm_devices_file_remove()
            self.log.info("Creating PV on %s", disk_path)
            if not self._pvcreate(disk_path):
                self.fail(f"pvcreate failed on {disk_path}")
            if process.system(f'vgcreate {vg_name} {disk_path}',
                              shell=True, ignore_status=True):
                self.fail(f"vgcreate failed for {vg_name}")
            if process.system(
                    f'lvcreate -l 100%FREE -n {lv_name} {vg_name}',
                    shell=True, ignore_status=True):
                self.fail(f"lvcreate failed for {vg_name}/{lv_name}")
            lvm_created = True
            lv_device = 'dm-' + os.path.basename(
                os.path.realpath(lv_path)).replace('dm-', '')
            self.log.info("LVM device resolved to: %s", lv_device)

            # --- Run HTX ---
            self._ensure_daemon_running()
            if not os.path.exists(mdt_path):
                process.run('htxcmdline -createmdt', ignore_status=True)
                for _ in range(12):
                    if os.path.exists(mdt_path):
                        break
                    time.sleep(5)
            process.system(f'htxcmdline -shutdown -mdt {self.mdt_file}',
                           timeout=60, ignore_status=True)
            time.sleep(3)
            process.system(f'htxcmdline -select -mdt {self.mdt_file}',
                           ignore_status=True)
            stanza = (f'\n{lv_device}:\n'
                      f'\tHE_name = "hxestorage"\n'
                      f'\tadapt_desc = "scsi"\n'
                      f'\tdevice_desc = "disk"\n'
                      f'\treg_rules = "hxestorage/default.hdd"\n'
                      f'\temc_rules = "hxestorage/default.hdd"\n\n')
            with open(mdt_path, 'r') as fh:
                content = fh.read()
            if f'{lv_device}:' not in content:
                with open(mdt_path, 'a') as fh:
                    fh.write(stanza)
            self.suspend_all_block_device()
            process.system(
                f'htxcmdline -activate {lv_device} -mdt {self.mdt_file}',
                ignore_status=True)
            process.system('htxcmdline -clrerrlog', ignore_status=True)
            process.run('truncate -s 0 /tmp/htxerr', ignore_status=True)
            self.log.info("Starting HTX on LVM device %s", lv_device)
            process.system(f'htxcmdline -run -mdt {self.mdt_file}',
                           ignore_status=True)
            time.sleep(5)

            # --- HTX check ---
            for _ in range(0, self.time_limit, 60):
                process.system('htxcmdline -geterrlog', ignore_status=True)
                if os.path.exists('/tmp/htxerr') and \
                        os.stat('/tmp/htxerr').st_size != 0:
                    self.fail("HTX errors detected; check /tmp/htxerr")
                process.system(
                    f'htxcmdline -query {lv_device} -mdt {self.mdt_file}',
                    ignore_status=True)
                time.sleep(60)

            # --- Stop HTX ---
            self.log.info("Stopping HTX on LVM device %s", lv_device)
            self.suspend_all_block_device()
            process.system(f'htxcmdline -shutdown -mdt {self.mdt_file}',
                           timeout=120, ignore_status=True)

        finally:
            # --- Clean up LVM ---
            if lvm_created:
                process.system(f'lvremove -f /dev/{vg_name}/{lv_name}',
                               shell=True, ignore_status=True)
                process.system(f'vgremove -f {vg_name}',
                               shell=True, ignore_status=True)
                process.system(f'pvremove -ff -y {disk_path}',
                               shell=True, ignore_status=True)
                process.system(f'wipefs -a --force {disk_path}',
                               shell=True, ignore_status=True)
                process.system('udevadm settle', shell=True, ignore_status=True)

    # ------------------------------------------------------------------
    # Test: HTX on Software RAID
    # ------------------------------------------------------------------

    def test_software_raid_create(self):
        """
        HTX on Software RAID:
          - Take htx_disks from YAML.
          - Create software RAID (level from htx_raid_level, default 1).
          - Validate the RAID array.
          - Run HTX on the md device.
          - Stop HTX and clean up RAID (mdadm --stop + zero superblocks).
        """
        if not self.htx_disks:
            self.cancel(
                "htx_disks not set; skipping test_software_raid_create")

        raid_level = int(self.params.get('htx_raid_level', default=1))
        mdt_path = f'{HTX_INSTALL_PATH}/mdt/{self.mdt_file}'
        md_device = None

        # Ensure mpath devices exist before resolving slaves.
        # A previous test may have flushed them with multipath -f.
        process.system('multipath', shell=True, ignore_status=True)
        process.system('udevadm settle', shell=True, ignore_status=True)

        dev_paths = []
        for d in self.htx_disks.split():
            dp = d if d.startswith('/') else f'/dev/{d}'
            if '/dev/mapper/' in dp:
                dm_dev = os.path.basename(os.path.realpath(dp))
                slaves_dir = f'/sys/block/{dm_dev}/slaves'
                if os.path.isdir(slaves_dir):
                    slaves = sorted(os.listdir(slaves_dir))
                    if slaves:
                        dp = f'/dev/{slaves[0]}'
            dev_paths.append(dp)

        try:
            # --- Release HTX before touching raw devices ---
            self._release_htx_devices()
            # --- Create RAID ---
            process.system(
                'for md in /dev/md/* /dev/md[0-9]*; do '
                '  [ -b "$md" ] && mdadm --stop "$md" 2>/dev/null; '
                'done', shell=True, ignore_status=True)
            process.system('udevadm settle', shell=True, ignore_status=True)
            time.sleep(3)
            # Flush only the test mpath devices before touching the raw disks
            # so that pvremove/wipefs can actually clear signatures.
            # Do NOT use dmsetup remove_all — it destroys root LVM devices.
            for d in self.htx_disks.split():
                mpath_name = os.path.basename(
                    d if d.startswith('/') else f'/dev/{d}')
                process.system(f'multipath -f {mpath_name}',
                               shell=True, ignore_status=True)
            process.system('udevadm settle', shell=True, ignore_status=True)
            time.sleep(2)
            for dp in dev_paths:
                # Remove any LVM/signature metadata left from previous test
                process.system(f'pvremove -ff -y {dp}',
                               shell=True, ignore_status=True)
                process.system(f'mdadm --zero-superblock --force {dp}',
                               shell=True, ignore_status=True)
                process.system(f'wipefs -a --force {dp}',
                               shell=True, ignore_status=True)
                process.system('udevadm settle',
                               shell=True, ignore_status=True)
            process.system('udevadm settle', shell=True, ignore_status=True)
            time.sleep(2)
            if raid_level == 1 and len(dev_paths) > 2:
                dev_paths = dev_paths[:2]
            n_disks = len(dev_paths)
            devs_str = ' '.join(dev_paths)
            cmd = (f'mdadm --create /dev/md/htx_md --run --force '
                   f'--metadata=0.90 --assume-clean '
                   f'--level={raid_level} --raid-devices={n_disks} '
                   f'{devs_str}')
            if process.system(cmd, shell=True, ignore_status=True):
                self.fail("mdadm --create failed")
            md_device = '/dev/md/htx_md'
            md_name = (os.path.basename(os.path.realpath(md_device))
                       if os.path.exists(md_device) else 'htx_md')
            for _ in range(12):
                time.sleep(5)
                state = process.system_output(
                    f'cat /sys/block/{md_name}/md/array_state',
                    shell=True, ignore_status=True).decode().strip()
                if state in ('clean', 'active'):
                    break

            # --- Validate RAID ---
            self.log.info("Validating RAID array %s", md_device)
            output = process.system_output(
                f'mdadm --detail {md_device}',
                shell=True, ignore_status=True).decode('utf-8')
            for line in output.splitlines():
                if 'State :' in line:
                    state = line.split(':', 1)[-1].strip().lower()
                    self.log.info("RAID state: %s", state)
                    if 'active' not in state and 'clean' not in state:
                        self.fail(f"RAID array not active: {state}")
                    break

            # --- Run HTX ---
            md_basename = os.path.basename(md_device)
            self._ensure_daemon_running()
            if not os.path.exists(mdt_path):
                process.run('htxcmdline -createmdt', ignore_status=True)
                for _ in range(12):
                    if os.path.exists(mdt_path):
                        break
                    time.sleep(5)
            process.system(f'htxcmdline -shutdown -mdt {self.mdt_file}',
                           timeout=60, ignore_status=True)
            time.sleep(3)
            process.system(f'htxcmdline -select -mdt {self.mdt_file}',
                           ignore_status=True)
            stanza = (f'\n{md_basename}:\n'
                      f'\tHE_name = "hxestorage"\n'
                      f'\tadapt_desc = "scsi"\n'
                      f'\tdevice_desc = "disk"\n'
                      f'\treg_rules = "hxestorage/default.hdd"\n'
                      f'\temc_rules = "hxestorage/default.hdd"\n\n')
            with open(mdt_path, 'r') as fh:
                content = fh.read()
            if f'{md_basename}:' not in content:
                with open(mdt_path, 'a') as fh:
                    fh.write(stanza)
            self.suspend_all_block_device()
            process.system(
                f'htxcmdline -activate {md_basename} -mdt {self.mdt_file}',
                ignore_status=True)
            process.system('htxcmdline -clrerrlog', ignore_status=True)
            process.run('truncate -s 0 /tmp/htxerr', ignore_status=True)
            self.log.info("Starting HTX on RAID device %s", md_basename)
            process.system(f'htxcmdline -run -mdt {self.mdt_file}',
                           ignore_status=True)
            time.sleep(5)

            # --- HTX check ---
            for _ in range(0, self.time_limit, 60):
                process.system('htxcmdline -geterrlog', ignore_status=True)
                if os.path.exists('/tmp/htxerr') and \
                        os.stat('/tmp/htxerr').st_size != 0:
                    self.fail("HTX errors detected; check /tmp/htxerr")
                process.system(
                    f'htxcmdline -query {md_basename} -mdt {self.mdt_file}',
                    ignore_status=True)
                time.sleep(60)

            # --- Stop HTX ---
            self.log.info("Stopping HTX on RAID device %s", md_basename)
            self.suspend_all_block_device()
            process.system(f'htxcmdline -shutdown -mdt {self.mdt_file}',
                           timeout=120, ignore_status=True)

        finally:
            # --- Clean up RAID ---
            if md_device:
                process.system(f'mdadm --stop {md_device}',
                               shell=True, ignore_status=True)
                process.system(f'mdadm --remove {md_device}',
                               shell=True, ignore_status=True)
                for dp in dev_paths:
                    process.system(
                        f'mdadm --zero-superblock --force {dp}',
                        shell=True, ignore_status=True)

    # ------------------------------------------------------------------
    # Test: HTX on Software RAID + LVM
    # ------------------------------------------------------------------

    def test_htx_on_software_raid_lvm(self):
        """
        HTX on Software RAID + LVM:
          - Take htx_disks from YAML.
          - Create software RAID and validate it.
          - Create LVM on top of the RAID device.
          - Run HTX on the resulting dm device.
          - Stop HTX, clean up LVM then RAID.
        """
        if not self.htx_disks:
            self.cancel(
                "htx_disks not set; skipping test_htx_on_software_raid_lvm")

        raid_level = int(self.params.get('htx_raid_level', default=1))
        mdt_path = f'{HTX_INSTALL_PATH}/mdt/{self.mdt_file}'
        md_device = None
        vg_name = 'htx_vg'
        lv_name = 'htx_lv'
        lvm_created = False

        # Ensure mpath devices exist before resolving slaves.
        # A previous test may have flushed them with multipath -f.
        process.system('multipath', shell=True, ignore_status=True)
        process.system('udevadm settle', shell=True, ignore_status=True)

        dev_paths = []
        for d in self.htx_disks.split():
            dp = d if d.startswith('/') else f'/dev/{d}'
            if '/dev/mapper/' in dp:
                dm_dev = os.path.basename(os.path.realpath(dp))
                slaves_dir = f'/sys/block/{dm_dev}/slaves'
                if os.path.isdir(slaves_dir):
                    slaves = sorted(os.listdir(slaves_dir))
                    if slaves:
                        dp = f'/dev/{slaves[0]}'
            dev_paths.append(dp)

        try:
            # --- Release HTX before touching raw devices ---
            self._release_htx_devices()
            # --- Create RAID ---
            process.system(
                'for md in /dev/md/* /dev/md[0-9]*; do '
                '  [ -b "$md" ] && mdadm --stop "$md" 2>/dev/null; '
                'done', shell=True, ignore_status=True)
            process.system('udevadm settle', shell=True, ignore_status=True)
            time.sleep(3)
            # Flush multipath and DM devices before touching the raw disks
            # so that pvremove/wipefs can actually clear signatures.
            for d in self.htx_disks.split():
                mpath_name = os.path.basename(
                    d if d.startswith('/') else f'/dev/{d}')
                process.system(f'multipath -f {mpath_name}',
                               shell=True, ignore_status=True)
            # Do NOT use dmsetup remove_all — it destroys root LVM devices.
            process.system('udevadm settle', shell=True, ignore_status=True)
            time.sleep(2)
            for dp in dev_paths:
                # Remove any LVM/signature metadata left from previous test
                process.system(f'pvremove -ff -y {dp}',
                               shell=True, ignore_status=True)
                process.system(f'mdadm --zero-superblock --force {dp}',
                               shell=True, ignore_status=True)
                process.system(f'wipefs -a --force {dp}',
                               shell=True, ignore_status=True)
                process.system('udevadm settle',
                               shell=True, ignore_status=True)
            process.system('udevadm settle', shell=True, ignore_status=True)
            time.sleep(2)
            if raid_level == 1 and len(dev_paths) > 2:
                dev_paths = dev_paths[:2]
            n_disks = len(dev_paths)
            devs_str = ' '.join(dev_paths)
            cmd = (f'mdadm --create /dev/md/htx_md --run --force '
                   f'--metadata=0.90 --assume-clean '
                   f'--level={raid_level} --raid-devices={n_disks} '
                   f'{devs_str}')
            if process.system(cmd, shell=True, ignore_status=True):
                self.fail("mdadm --create failed")
            md_device = '/dev/md/htx_md'
            md_name = (os.path.basename(os.path.realpath(md_device))
                       if os.path.exists(md_device) else 'htx_md')
            for _ in range(12):
                time.sleep(5)
                state = process.system_output(
                    f'cat /sys/block/{md_name}/md/array_state',
                    shell=True, ignore_status=True).decode().strip()
                if state in ('clean', 'active'):
                    break

            # --- Validate RAID ---
            self.log.info("Validating RAID array %s", md_device)
            output = process.system_output(
                f'mdadm --detail {md_device}',
                shell=True, ignore_status=True).decode('utf-8')
            for line in output.splitlines():
                if 'State :' in line:
                    state = line.split(':', 1)[-1].strip().lower()
                    self.log.info("RAID state: %s", state)
                    if 'active' not in state and 'clean' not in state:
                        self.fail(f"RAID array not active: {state}")
                    break

            # --- Create LVM on RAID ---
            self.log.info("Creating LVM on RAID device %s", md_device)
            self._lvm_devices_file_remove()
            if not self._pvcreate(md_device):
                self.fail(f"pvcreate failed on {md_device}")
            if process.system(f'vgcreate {vg_name} {md_device}',
                              shell=True, ignore_status=True):
                self.fail(f"vgcreate failed for {vg_name}")
            if process.system(
                    f'lvcreate -l 100%FREE -n {lv_name} {vg_name}',
                    shell=True, ignore_status=True):
                self.fail(f"lvcreate failed for {vg_name}/{lv_name}")
            lvm_created = True
            lv_path = f'/dev/{vg_name}/{lv_name}'
            lv_device = 'dm-' + os.path.basename(
                os.path.realpath(lv_path)).replace('dm-', '')
            self.log.info("LVM device resolved to: %s", lv_device)

            # --- Run HTX ---
            self._ensure_daemon_running()
            if not os.path.exists(mdt_path):
                process.run('htxcmdline -createmdt', ignore_status=True)
                for _ in range(12):
                    if os.path.exists(mdt_path):
                        break
                    time.sleep(5)
            process.system(f'htxcmdline -shutdown -mdt {self.mdt_file}',
                           timeout=60, ignore_status=True)
            time.sleep(3)
            process.system(f'htxcmdline -select -mdt {self.mdt_file}',
                           ignore_status=True)
            stanza = (f'\n{lv_device}:\n'
                      f'\tHE_name = "hxestorage"\n'
                      f'\tadapt_desc = "scsi"\n'
                      f'\tdevice_desc = "disk"\n'
                      f'\treg_rules = "hxestorage/default.hdd"\n'
                      f'\temc_rules = "hxestorage/default.hdd"\n\n')
            with open(mdt_path, 'r') as fh:
                content = fh.read()
            if f'{lv_device}:' not in content:
                with open(mdt_path, 'a') as fh:
                    fh.write(stanza)
            self.suspend_all_block_device()
            process.system(
                f'htxcmdline -activate {lv_device} -mdt {self.mdt_file}',
                ignore_status=True)
            process.system('htxcmdline -clrerrlog', ignore_status=True)
            process.run('truncate -s 0 /tmp/htxerr', ignore_status=True)
            self.log.info("Starting HTX on LVM-over-RAID device %s", lv_device)
            process.system(f'htxcmdline -run -mdt {self.mdt_file}',
                           ignore_status=True)
            time.sleep(5)

            # --- HTX check ---
            for _ in range(0, self.time_limit, 60):
                process.system('htxcmdline -geterrlog', ignore_status=True)
                if os.path.exists('/tmp/htxerr') and \
                        os.stat('/tmp/htxerr').st_size != 0:
                    self.fail("HTX errors detected; check /tmp/htxerr")
                process.system(
                    f'htxcmdline -query {lv_device} -mdt {self.mdt_file}',
                    ignore_status=True)
                time.sleep(60)

            # --- Stop HTX ---
            self.log.info("Stopping HTX on LVM-over-RAID device %s", lv_device)
            self.suspend_all_block_device()
            process.system(f'htxcmdline -shutdown -mdt {self.mdt_file}',
                           timeout=120, ignore_status=True)

        finally:
            # --- Clean up LVM ---
            if lvm_created:
                process.system(f'lvremove -f /dev/{vg_name}/{lv_name}',
                               shell=True, ignore_status=True)
                process.system(f'vgremove -f {vg_name}',
                               shell=True, ignore_status=True)
                if md_device:
                    process.system(f'pvremove -ff -y {md_device}',
                                   shell=True, ignore_status=True)
            # --- Clean up RAID ---
            if md_device:
                process.system(f'mdadm --stop {md_device}',
                               shell=True, ignore_status=True)
                process.system(f'mdadm --remove {md_device}',
                               shell=True, ignore_status=True)
                for dp in dev_paths:
                    process.system(
                        f'mdadm --zero-superblock --force {dp}',
                        shell=True, ignore_status=True)

    def test_check(self):
        """
        Checks if HTX is running, and if no errors.
        """
        # Clear any stale errors written by previous LVM/RAID tests that ran
        # in the same job.  Those tests shut down their own HTX run and clean
        # up their devices, but may leave error entries referencing devices
        # (e.g. /dev/htx_md) that no longer exist.  test_check only cares
        # about errors produced during its own polling window.
        process.system('htxcmdline -clrerrlog', ignore_status=True)
        process.run('truncate -s 0 /tmp/htxerr', ignore_status=True)
        # Re-select the MDT so HTX reflects the currently running devices only
        # (LVM/RAID tests may have added stanzas for devices they already
        # removed; re-selecting regenerates the active device list).
        process.system(f'htxcmdline -select -mdt {self.mdt_file}',
                       ignore_status=True)
        for _ in range(0, self.time_limit, 60):
            self.log.info("Checking HTX error log")
            process.system('htxcmdline -geterrlog', ignore_status=True)
            if os.stat('/tmp/htxerr').st_size != 0:
                self.fail("HTX errors detected; check /tmp/htxerr")

            if self.htx_disks or self.run_all:
                cmd = (f'htxcmdline -query {self.block_device}'
                       f' -mdt {self.mdt_file}')
            else:
                cmd = f'htxcmdline -query -mdt {self.mdt_file}'
            process.system(cmd, ignore_status=True)
            time.sleep(60)

    def test_stop(self):
        """
        Shutdown the MDT and the HTX daemon.
        """
        self.stop_htx()

    def stop_htx(self):
        """
        Stop the HTX Run
        """
        self.suspend_all_block_device()

        self.log.info("Shutting down MDT: %s", self.mdt_file)
        process.system(f'htxcmdline -shutdown -mdt {self.mdt_file}',
                       timeout=120, ignore_status=True)

        process.system('umount /htx_pmem*', shell=True, ignore_status=True)

        self._stop_daemon()
