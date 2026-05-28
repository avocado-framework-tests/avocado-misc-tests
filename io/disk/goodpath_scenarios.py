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
# Author: Maram Srimannarayana Murthy <msmurthy@linux.vnet.ibm.com>

"""
Goodpath scenarios for storage stack validation combining RAID, LVM, and
workload testing to validate storage reliability under stress conditions.
"""

import os
import re
import shutil
import threading
import time

from avocado import Test
from avocado.utils import archive
from avocado.utils import build
from avocado.utils import cpu
from avocado.utils import dmesg
from avocado.utils import disk
from avocado.utils import distro
from avocado.utils import genio
from avocado.utils import multipath
from avocado.utils import process
from avocado.utils import softwareraid
from avocado.utils.disk import cleanup_disks
from avocado.utils import wait
from avocado.utils.partition import Partition
from avocado.utils.partition import PartitionError
from avocado.utils.software_manager.manager import SoftwareManager


class GoodpathScenarios(Test):
    """
    Storage stack validation test suite for concurrent workload testing.

    Test Case: Concurrent RAID rebuild, filesystem stress, and FIO testing
    """

    RAID_NAME = '/dev/md/sraid'
    MIN_DISKS_REQUIRED = 4

    MONITORING_INTERVAL_SEC = 300
    TEST_DURATION_SEC = 3600

    HTX_STRESS_DURATION_MIN = 30
    HTX_MDT_FILE = 'mdt.hd'

    # irqbalance + SMT + HTX stress test constants
    IRQ_HTX_STRESS_DURATION_MIN = 60
    SMT_CHANGE_INTERVAL_SEC = 60
    SMT_LEVELS = ['off', 1, 2, 4, 8, 'on']
    DMESG_ERROR_PATTERNS = [
        'WARNING: CPU:', 'Oops', 'Segfault', 'soft lockup', 'hard LOCKUP',
        'Unable to handle paging request', 'rcu_sched detected stalls',
        'NMI backtrace for cpu', 'Call Trace:',
    ]
    HTX_INSTALL_PATH = '/usr/lpp/htx'

    def setUp(self):
        """
        Initialize test environment and install dependencies.
        """
        self.err_messages = []

        disks_param = self.params.get('disks', default='').strip()
        if not disks_param:
            self.cancel('No disks provided in YAML configuration')

        self.disks = []
        for dev in disks_param.split():
            disk_path = disk.get_absolute_disk_path(dev)
            if disk_path not in disk.get_all_disk_paths():
                self.cancel(f"Disk {dev} not found in system")
            self.disks.append(disk_path)

        if len(self.disks) < self.MIN_DISKS_REQUIRED:
            self.cancel(f"Minimum {self.MIN_DISKS_REQUIRED} disks required")

        self.detected_distro = distro.detect()

        smm = SoftwareManager()
        base_packages = [
            'mdadm', 'lvm2', 'fio', 'gcc', 'make',
            'gcc-c++', 'libaio-devel', 'autoconf', 'automake',
        ]
        dist_name = self.detected_distro.name
        if dist_name in ['rhel', 'redhat']:
            base_packages.append('sos')
        elif dist_name == 'SuSE':
            base_packages.append('supportutils')

        for pkg in base_packages:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel(f"Failed to install {pkg}")

        self.log.info("All base dependencies installed successfully")

        self.raid_name = self.RAID_NAME
        self.monitoring_interval = self.MONITORING_INTERVAL_SEC
        self.test_duration = self.TEST_DURATION_SEC

        self.log.info("Pre-cleanup: Removing existing RAID/LVM configurations")
        self.pre_cleanup()

    def pre_cleanup(self):
        """
        Remove existing RAID and LVM configurations before the test run.
        """
        self.log.info("Pre-cleanup: Running cleanup_disks in full mode")
        try:
            cleanup_disks(self.disks, logger=self.log, mode="full")
        except Exception as err:
            self.log.warning("Pre-cleanup disk cleanup failed: %s", err)

    def _read_mdstat(self):
        """
        Read and return /proc/mdstat contents.

        :return: Contents of /proc/mdstat, empty string on error
        """
        try:
            with open('/proc/mdstat', 'r') as f:
                return f.read()
        except IOError as e:
            self.log.warning(f"Failed to read /proc/mdstat: {e}")
            return ""

    def _check_raid_health(self):
        """
        Check RAID health and return status dictionary.

        :return: Dictionary with health status information
        """
        mdstat = self._read_mdstat()
        return {
            'healthy': '[UU]' in mdstat and 'recovery' not in mdstat.lower(),
            'degraded': '[U_]' in mdstat or '[_U]' in mdstat,
            'rebuilding': ('recovery' in mdstat.lower() or
                           'resync' in mdstat.lower()),
            'status_text': mdstat
        }

    def _create_raid_with_rebuild(self):
        """
        Create RAID1 and trigger rebuild by removing and adding disk.
        """
        raid_disks = [self.disks[0], self.disks[1]]
        self.log.info(f"Creating RAID1 on: {raid_disks}")

        self.sraid = softwareraid.SoftwareRaid(self.raid_name, '1',
                                               raid_disks, '1.2')
        if not self.sraid.create():
            self.fail("Failed to create RAID1")

        def raid_sync_complete():
            return not self.sraid.is_recovering()

        self.log.info("Waiting for initial RAID sync")
        wait.wait_for(raid_sync_complete, timeout=1800, step=30)

        self.log.info(f"Triggering rebuild by removing {self.disks[1]}")
        if not self.sraid.remove_disk(self.disks[1]):
            self.fail("Failed to remove disk from RAID")

        def disk_removed():
            with open('/proc/mdstat', 'r') as f:
                return self.disks[1] not in f.read()

        self.log.info("Waiting for disk removal to complete")
        wait.wait_for(disk_removed, timeout=10, step=1)

        self.log.info(f"Adding {self.disks[1]} back to trigger rebuild")
        if not self.sraid.add_disk(self.disks[1]):
            self.fail("Failed to add disk back to RAID")

        def check_rebuild_activity():
            with open('/proc/mdstat', 'r') as f:
                mdstat = f.read()
                return ('recovery' in mdstat.lower() or
                        'resync' in mdstat.lower() or
                        '[UU]' in mdstat)

        self.log.info("Monitoring RAID rebuild activity (up to 60s)")
        try:
            wait.wait_for(check_rebuild_activity, timeout=60, step=5)
            self.log.info("RAID rebuild activity detected")
        except Exception:
            self.log.warning("No RAID rebuild activity detected after 60s")

    def _setup_filesystem(self):
        """
        Create and mount ext4 filesystem on third disk.

        :return: Mount point path
        """
        fs_disk = self.disks[2]
        fs_mount = os.path.join(self.workdir, 'fsstress_mount')
        os.makedirs(fs_mount, exist_ok=True)

        self.log.info(f"Creating ext4 filesystem on {fs_disk}")
        self.part_obj = Partition(fs_disk, mountpoint=fs_mount)
        self.part_obj.unmount()
        self.part_obj.mkfs('ext4')

        try:
            self.part_obj.mount()
        except PartitionError:
            self.fail(f"Failed to mount {fs_disk} on {fs_mount}")

        self.log.info(f"Filesystem mounted at {fs_mount}")
        return fs_mount

    def _build_ltp(self):
        """
        Download and build LTP for fsstress.

        :return: Path to fsstress directory
        """
        self.log.info("Downloading and building LTP")
        url = "https://github.com/linux-test-project/ltp/archive/master.zip"
        tarball = self.fetch_asset(
            "ltp-master.zip", locations=[url], expire='7d')
        archive.extract(tarball, self.teststmpdir)
        ltp_dir = os.path.join(self.teststmpdir, "ltp-master")

        os.chdir(ltp_dir)
        build.make(ltp_dir, extra_args='autotools')
        process.system('./configure', ignore_status=True)
        build.make(ltp_dir)
        build.make(ltp_dir, extra_args='install')

        fsstress_dir = os.path.join(
            ltp_dir, 'testcases/kernel/fs/fsstress')
        return fsstress_dir

    def _start_fsstress(self, fs_mount):
        """
        Start LTP fsstress in background.

        :param fs_mount: Filesystem mount point
        :return: SubProcess object
        """
        self.log.info("Starting LTP fsstress in background")
        fsstress_cmd = f"./fsstress -d {fs_mount} -n 250 -p 250 -l 1"
        fsstress_proc = process.SubProcess(fsstress_cmd)
        fsstress_proc.start()
        self.log.info("fsstress started")
        return fsstress_proc

    def _start_fio(self):
        """
        Start FIO I/O test in background on fourth disk.

        :return: SubProcess object
        """
        fio_disk = self.disks[3]
        self.log.info(f"Starting FIO on {fio_disk} in background")

        fio_job = os.path.join(self.workdir, 'fio_test.job')
        with open(fio_job, 'w') as job_file:
            job_file.write(f"""[global]
name=fio-test
rw=randrw
bs=4k
direct=1
ioengine=libaio
iodepth=32
runtime={self.test_duration}
time_based=1

[job1]
filename={fio_disk}
""")

        fio_cmd = f"fio {fio_job}"
        fio_proc = process.SubProcess(fio_cmd)
        fio_proc.start()
        self.log.info("FIO started")
        return fio_proc

    def _monitor_concurrent_operations(self, fsstress_proc, fio_proc):
        """
        Monitor RAID and process status during concurrent operations.

        :param fsstress_proc: fsstress SubProcess object
        :param fio_proc: FIO SubProcess object
        """
        self.log.info(f"Monitoring for {self.test_duration} seconds")
        start_time = time.time()

        while (time.time() - start_time) < self.test_duration:
            self.log.info("=" * 60)
            elapsed = int(time.time() - start_time)
            self.log.info(f"Monitoring check at {elapsed} seconds")

            self.log.info("Checking RAID status")
            raid_health = self._check_raid_health()
            self.log.debug(f"RAID health: {raid_health}")
            self.log.info(f"RAID status:\n{raid_health['status_text']}")
            if raid_health['degraded']:
                self.err_messages.append("RAID has failed disk")

            if fsstress_proc.poll() is not None:
                self.log.info("fsstress completed")
            if fio_proc.poll() is not None:
                self.log.info("FIO completed")

            self.log.info(f"Sleeping for {self.monitoring_interval} seconds")
            time.sleep(self.monitoring_interval)

    def _validate_test_results(self, fsstress_proc, fio_proc):
        """
        Wait for processes and validate final results.

        :param fsstress_proc: fsstress SubProcess object
        :param fio_proc: FIO SubProcess object
        """
        self.log.info("=" * 70)
        self.log.info("VALIDATING TEST RESULTS - 3 Parallel Operations")
        self.log.info("=" * 70)

        fsstress_status = "PASS"
        fio_status = "PASS"
        raid_status = "PASS"

        self.log.info("Waiting for fsstress to complete")
        fsstress_exit_code = fsstress_proc.wait()
        if fsstress_exit_code != 0:
            fsstress_status = "FAIL"
            error_msg = (f"fsstress failed with exit code "
                         f"{fsstress_exit_code}")
            self.err_messages.append(error_msg)
            self.log.error(f"[1/3] fsstress: {fsstress_status} - {error_msg}")
        else:
            self.log.info(f"[1/3] fsstress: {fsstress_status}")

        self.log.info("Waiting for FIO to complete")
        fio_exit_code = fio_proc.wait()
        if fio_exit_code not in [0, 3]:
            fio_status = "FAIL"
            error_msg = f"FIO failed with exit code {fio_exit_code}"
            self.err_messages.append(error_msg)
            self.log.error(f"[2/3] FIO: {fio_status} - {error_msg}")
        else:
            self.log.info(f"[2/3] FIO: {fio_status}")

        self.log.info("Checking final RAID status")
        raid_health = self._check_raid_health()
        self.log.debug(f"Final RAID health: {raid_health}")
        if not raid_health['healthy']:
            raid_status = "FAIL"
            error_msg = "RAID not in healthy state [UU]"
            self.err_messages.append(error_msg)
            self.log.error(f"[3/3] RAID Rebuild: {raid_status} - {error_msg}")
        else:
            self.log.info(f"[3/3] RAID Rebuild: {raid_status}")

        self.log.info("=" * 70)
        self.log.info("FINAL STATUS SUMMARY:")
        self.log.info(f"  fsstress:    {fsstress_status}")
        self.log.info(f"  FIO:         {fio_status}")
        self.log.info(f"  RAID Rebuild: {raid_status}")
        self.log.info("=" * 70)

    def test_swraid_fs_fio(self):
        """
        Validate concurrent storage operations with RAID rebuild.

        Creates RAID1, triggers rebuild, runs filesystem stress test and
        FIO concurrently while monitoring system health every 5 minutes.
        """
        self.log.info("Running SWRAID + fsstress + FIO test")

        self._create_raid_with_rebuild()

        fs_mount = self._setup_filesystem()

        fsstress_dir = self._build_ltp()
        os.chdir(fsstress_dir)

        fsstress_proc = self._start_fsstress(fs_mount)

        fio_proc = self._start_fio()

        self._monitor_concurrent_operations(fsstress_proc, fio_proc)

        self._validate_test_results(fsstress_proc, fio_proc)

        if self.err_messages:
            self.log.error("=" * 70)
            self.log.error("OVERALL TEST RESULT: FAIL")
            self.log.error("=" * 70)
            self.fail(f"Test failed with errors: {self.err_messages}")
        else:
            self.log.info("=" * 70)
            self.log.info("OVERALL TEST RESULT: PASS")
            self.log.info("All 3 parallel operations completed successfully")

    def _install_htx(self):
        """
        Install HTX packages required for stress testing.

        Installs build tools and HTX either from a distro RPM link (via
        ``htx_rpm_link`` YAML parameter) or from the open-power GitHub
        source tree (when ``htx_run_type`` is set to ``git``).  Mirrors
        the installation logic used in htx_block_devices.py.
        """
        dist = self.detected_distro
        dist_name = dist.name
        dist_version = dist.version

        packages = ['git', 'gcc', 'make']
        if dist_name in ['rhel', 'redhat']:
            packages.extend(['gcc-c++', 'ncurses-devel', 'tar'])
        elif dist_name == 'SuSE':
            packages.extend(['libncurses5', 'gcc-c++', 'ncurses-devel', 'tar'])
        else:
            self.cancel("HTX stress test not supported on %s" % dist_name)

        smm = SoftwareManager()
        for pkg in packages:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel("Cannot install required package: %s" % pkg)

        htx_run_type = self.params.get('htx_run_type', default='')
        if htx_run_type == 'git':
            self._install_htx_from_git()
        else:
            htx_rpm_link = self.params.get('htx_rpm_link', default=None)
            if htx_rpm_link:
                self._install_htx_rpm(htx_rpm_link, dist_name, dist_version)
            else:
                self.log.info("No htx_rpm_link provided; assuming HTX is "
                              "already installed on the system")

        if not os.path.isdir(self.HTX_INSTALL_PATH):
            self.cancel("HTX installation not found at %s" %
                        self.HTX_INSTALL_PATH)

    def _install_htx_from_git(self):
        """
        Clone the open-power HTX repository and build/install it.
        """
        self.log.info("Building HTX from GitHub source")
        url = "https://github.com/open-power/HTX/archive/master.zip"
        tarball = self.fetch_asset("htx.zip", locations=[url], expire='7d')
        archive.extract(tarball, self.teststmpdir)
        htx_path = os.path.join(self.teststmpdir, 'HTX-master')
        os.chdir(htx_path)

        exercisers = ['hxecapi_afu_dir', 'hxedapl', 'hxecapi', 'hxeocapi']
        for exerciser in exercisers:
            process.run("sed -i 's/%s,//g' %s/bin/Makefile" %
                        (exerciser, htx_path), ignore_status=True, shell=True)

        build.make(htx_path, extra_args='all')
        build.make(htx_path, extra_args='tar')
        process.run("tar --touch -xvzf htx_package.tar.gz")
        os.chdir("htx_package")
        if process.system("./installer.sh -f"):
            self.fail("HTX installation from source failed")

    def _install_htx_rpm(self, rpm_link, dist_name, dist_version):
        """
        Download and install the latest HTX RPM for this distro/version.

        :param rpm_link: Base URL hosting the HTX RPM packages.
        :param dist_name: Distribution name (e.g. ``rhel``, ``SuSE``).
        :param dist_version: Distribution major version string.
        """
        if dist_name.lower() == 'suse':
            dist_name = 'sles'

        rpm_check = "htx%s%s" % (dist_name, dist_version)
        ins_htx = process.system_output(
            "rpm -qa | grep htx", shell=True,
            ignore_status=True).decode()

        if ins_htx:
            if not SoftwareManager().check_installed(rpm_check):
                self.log.info("Removing existing HTX RPM: %s", ins_htx.strip())
                process.system("rpm -e %s" % ins_htx.strip(),
                               shell=True, ignore_status=True)
                if os.path.exists(self.HTX_INSTALL_PATH):
                    shutil.rmtree(self.HTX_INSTALL_PATH)
            else:
                self.log.info("Existing HTX RPM %s matches; reusing",
                              rpm_check)
                return

        distro_pattern = "%s%s" % (dist_name, dist_version)
        raw = process.system_output(
            "curl --silent -k %s" % rpm_link,
            shell=True, ignore_status=True).decode()
        candidates = re.findall(
            r"(?<=\>)htx\w*[-]\d*[-]\w*[.]\w*[.]\w*", raw)
        matched = sorted(
            [r for r in candidates if distro_pattern in r],
            reverse=True)
        if not matched:
            self.cancel("No HTX RPM found for %s at %s" %
                        (distro_pattern, rpm_link))

        latest_rpm = matched[0]
        tmp_rpm = "/tmp/%s" % latest_rpm
        cmd = "curl -k %s/%s -o %s" % (rpm_link, latest_rpm, tmp_rpm)
        if process.system(cmd, shell=True, ignore_status=True):
            self.cancel("Failed to download HTX RPM %s" % latest_rpm)
        if process.system("rpm -ivh --nodeps %s --force" % tmp_rpm,
                          shell=True, ignore_status=True):
            self.cancel("Failed to install HTX RPM %s" % latest_rpm)
        self.log.info("HTX RPM %s installed successfully", latest_rpm)

    def _htx_block_device_list(self):
        """
        Resolve the YAML ``disks`` list to bare device basenames accepted
        by ``htxcmdline``, handling multipath DM devices transparently.

        :return: Space-separated string of device basenames.
        """
        names = []
        for dev_path in self.disks:
            base = os.path.basename(os.path.realpath(dev_path))
            if 'dm' in base:
                base = multipath.get_mpath_from_dm(base)
            names.append(base)
        return ' '.join(names)

    def _htx_is_any_device_active(self, block_device, mdt_file):
        """
        Return True if at least one device from *block_device* is ACTIVE
        in the current HTX MDT query output.

        :param block_device: Space-separated device basename string.
        :param mdt_file: HTX MDT filename (e.g. ``mdt.hd``).
        :return: True if any device is ACTIVE, False otherwise.
        """
        cmd = "htxcmdline -query %s -mdt %s" % (block_device, mdt_file)
        output = process.system_output(
            cmd, ignore_status=True).decode('utf-8').splitlines()
        for line in output:
            for dev in block_device.split():
                if dev in line and 'ACTIVE' in line:
                    return True
        return False

    def _stop_htx(self, block_device, mdt_file):
        """
        Gracefully suspend all running HTX devices and shut down the MDT.

        :param block_device: Space-separated device basename string.
        :param mdt_file: HTX MDT filename.
        """
        self.log.info("Suspending all HTX block devices")
        process.system("htxcmdline -suspend all -mdt %s" % mdt_file,
                       ignore_status=True)
        self.log.info("Shutting down HTX MDT: %s", mdt_file)
        process.system("htxcmdline -shutdown -mdt %s" % mdt_file,
                       timeout=120, ignore_status=True)

        daemon_cmd = "%s/etc/scripts/htx.d status" % self.HTX_INSTALL_PATH
        daemon_state = process.system_output(
            daemon_cmd, ignore_status=True).decode('utf-8')
        if daemon_state.split()[-1:] == ['running']:
            process.system("%s/etc/scripts/htxd_shutdown" %
                           self.HTX_INSTALL_PATH, ignore_status=True)

    def _generate_sos_report(self, report_dir):
        """
        Generate a sos report for RHEL/redhat and log the archive path.

        Uses the legacy ``sosreport`` binary on RHEL <= 7.4; ``sos report``
        on all other supported releases.

        :param report_dir: Directory where the report archive will be written.
        """
        dist = self.detected_distro
        sos_cmd = 'sos report'
        if (dist.name == 'rhel'
                and int(dist.version) <= 7
                and int(dist.release) <= 4):
            sos_cmd = 'sosreport'

        self.log.info("Generating sos report for %s %s",
                      dist.name, dist.version)
        cmd = ("%s --batch --tmp-dir=%s "
               "--label htx-stress-goodpath" % (sos_cmd, report_dir))
        ret = process.run(cmd, sudo=True, ignore_status=True)
        if ret.exit_status not in (0, 1):
            self.fail("sos report generation failed (exit %d)" %
                      ret.exit_status)

        archives = [
            f for f in os.listdir(report_dir)
            if f.startswith('sosreport-') or f.startswith('sos-report-')
        ]
        if not archives:
            self.fail("sos report archive not found in %s" % report_dir)
        archive_path = os.path.join(report_dir, sorted(archives)[-1])
        self.log.info("sos report archive: %s", archive_path)

    def _generate_supportconfig_report(self, report_dir):
        """
        Generate a supportconfig report for SuSE and log the archive path.

        :param report_dir: Directory where the report archive will be written.
        """
        dist = self.detected_distro
        self.log.info("Generating supportconfig report for SuSE %s",
                      dist.version)
        cmd = "supportconfig -R %s" % report_dir
        ret = process.run(cmd, sudo=True, ignore_status=True)
        if ret.exit_status:
            self.fail("supportconfig failed (exit %d)" % ret.exit_status)

        archives = [
            f for f in os.listdir(report_dir)
            if f.startswith(('nts_', 'scc_'))
        ]
        if not archives:
            match = re.search(
                r"Log file tar ball:\s*(\S+)",
                ret.stdout.decode('utf-8'))
            archive_path = match.group(1) if match else report_dir
        else:
            archive_path = os.path.join(report_dir, sorted(archives)[-1])
        self.log.info("supportconfig archive: %s", archive_path)

    def _generate_diagnostic_report(self):
        """
        Generate a distribution-appropriate diagnostic report after the
        HTX stress run and record the archive path in the test log.

        - **RHEL**: uses ``sos report`` (or ``sosreport`` on RHEL <= 7.4).
        - **SuSE**: uses ``supportconfig``.

        Both tools and their packages are installed in :meth:`setUp`.

        :raises: :class:`avocado.core.exceptions.TestFail` if report
                 generation fails or the expected archive is not produced.
        """
        dist_name = self.detected_distro.name
        report_dir = os.path.join(self.workdir, 'diagnostic_report')
        os.makedirs(report_dir, exist_ok=True)

        if dist_name in ['rhel', 'redhat']:
            self._generate_sos_report(report_dir)
        elif dist_name == 'SuSE':
            self._generate_supportconfig_report(report_dir)
        else:
            self.log.warning(
                "Diagnostic report generation not supported on %s; skipping",
                dist_name)
            return

        self.log.info("Diagnostic report saved to: %s", report_dir)

    def _setup_htx_mdt(self, mdt_file, block_device):
        """
        Initialise HTX MDT, select it, and activate the target block devices.

        Kills any stale ``hxe`` process, creates the MDT file when absent,
        and activates all devices listed in *block_device*.

        :param mdt_file: HTX MDT filename (e.g. ``mdt.hd``).
        :param block_device: Space-separated device basename string.
        """
        hxe_pid = process.getoutput("pgrep -f hxe", ignore_status=True)
        if hxe_pid.strip():
            self.log.info("Stale HXE process (PID %s); shutting down",
                          hxe_pid.strip())
            process.run("hcl -shutdown", ignore_status=True)
            time.sleep(20)

        self.log.info("Creating HTX MDT files")
        process.run("htxcmdline -createmdt", ignore_status=True)

        mdt_path = "%s/mdt/%s" % (self.HTX_INSTALL_PATH, mdt_file)
        if not os.path.exists(mdt_path):
            process.run("htxcmdline -createmdt -mdt %s" % mdt_file,
                        ignore_status=True)
            if not os.path.exists(mdt_path):
                self.fail("MDT file %s creation failed" % mdt_file)

        self.log.info("Selecting MDT: %s", mdt_file)
        process.system("htxcmdline -select -mdt %s" % mdt_file,
                       ignore_status=True)
        self.log.info("Suspending any pre-existing HTX devices in MDT")
        process.system("htxcmdline -suspend all -mdt %s" % mdt_file,
                       ignore_status=True)
        self.log.info("Activating devices: %s", block_device)
        process.system("htxcmdline -activate %s -mdt %s" %
                       (block_device, mdt_file), ignore_status=True)

        if not self._htx_is_any_device_active(block_device, mdt_file):
            self.fail("None of the specified block devices became ACTIVE "
                      "in HTX MDT %s" % mdt_file)

    def _run_htx_stress_poll(self, block_device, mdt_file,
                             stress_duration_sec):
        """
        Start the HTX stress run and poll every 60 s for errors.

        Starts ``htxcmdline -run``, then polls ``/tmp/htxerr`` at
        60-second intervals for the full *stress_duration_sec*.
        After the loop, stops HTX and performs a final error-log check.

        :param block_device: Space-separated device basename string.
        :param mdt_file: HTX MDT filename.
        :param stress_duration_sec: Total stress duration in seconds.
        """
        self.log.info("Starting HTX stress run on: %s", block_device)
        process.system("htxcmdline -run -mdt %s" % mdt_file,
                       ignore_status=True)

        poll_interval_sec = 60
        elapsed = 0
        while elapsed < stress_duration_sec:
            time.sleep(poll_interval_sec)
            elapsed += poll_interval_sec
            self.log.info("HTX poll at %d / %d seconds",
                          elapsed, stress_duration_sec)

            process.run("htxcmdline -geterrlog", ignore_status=True)
            htx_err_file = '/tmp/htxerr'
            if (os.path.exists(htx_err_file)
                    and os.stat(htx_err_file).st_size != 0):
                self.log.error("HTX errors detected at %d s; see %s",
                               elapsed, htx_err_file)
                self.err_messages.append(
                    "HTX errors found at %d seconds; check %s" %
                    (elapsed, htx_err_file))

            process.system("htxcmdline -query %s -mdt %s" %
                           (block_device, mdt_file), ignore_status=True)

        self.log.info("HTX stress duration completed; stopping HTX")
        self._stop_htx(block_device, mdt_file)

        process.run("htxcmdline -geterrlog", ignore_status=True)
        if (os.path.exists('/tmp/htxerr')
                and os.stat('/tmp/htxerr').st_size != 0):
            self.err_messages.append(
                "HTX errors found in final error log; check /tmp/htxerr")

    def test_htx_stress_with_diagnostic_report(self):
        """
        Run HTX block-device stress for 30 minutes on all provided disks,
        then generate a distribution-appropriate diagnostic report.
        """
        if 'ppc64' not in self.detected_distro.arch:
            self.cancel("HTX stress test is only supported on ppc64 platforms")

        mdt_file = self.HTX_MDT_FILE
        stress_duration_min = self.HTX_STRESS_DURATION_MIN
        stress_duration_sec = stress_duration_min * 60

        self.log.info("Installing HTX")
        self._install_htx()

        block_device = self._htx_block_device_list()
        self.log.info("HTX target devices: %s", block_device)

        self._setup_htx_mdt(mdt_file, block_device)
        self._run_htx_stress_poll(block_device, mdt_file, stress_duration_sec)

        self.log.info("Generating post-stress diagnostic report")
        self._generate_diagnostic_report()

        if self.err_messages:
            self.fail("HTX stress with diagnostic report FAILED: %s" %
                      self.err_messages)

        self.log.info("HTX stress with diagnostic report: PASS")

    # ------------------------------------------------------------------
    # Helpers: IRQ / CPU affinity / SMT used by test_irqbalance_block_devices
    # ------------------------------------------------------------------

    def _get_disk_ipi_name(self, dev_path):
        """
        Return the /proc/interrupts device-name token for *dev_path*.

        NVMe controllers appear in /proc/interrupts as ``nvme0``, ``nvme1``
        etc., so we strip the namespace suffix.  All other block devices
        (sd*, vd*, …) use the bare ``basename``.

        :param dev_path: Absolute device path, e.g. ``/dev/nvme0n1`` or
                         ``/dev/sdb``.
        :return: Interrupt-table name token, e.g. ``nvme0`` or ``sdb``.
        :rtype: str
        """
        base = os.path.basename(dev_path)
        if base.startswith('nvme'):
            match = re.match(r'(nvme\d+)', base)
            if match:
                return match.group(1)
        return base

    def _get_device_irq_numbers(self, ipi_name):
        """
        Return the list of IRQ numbers associated with *ipi_name* as found
        in ``/proc/interrupts``.

        :param ipi_name: Device token used for grep in /proc/interrupts.
        :return: List of integer IRQ numbers; empty list if none found.
        :rtype: list[int]
        """
        cmd = "grep %s /proc/interrupts" % ipi_name
        output = process.run(
            cmd, shell=True, ignore_status=True).stdout.decode().strip()
        if not output:
            return []
        return [int(x.rstrip(':'))
                for x in re.findall(r'\b(\d+):', output)]

    def _set_irq_affinity_all_cpus(self, irq_number, online_cpus):
        """
        Write all online CPUs to ``/proc/irq/<irq>/smp_affinity_list`` so
        that every CPU handles interrupts for the device.

        :param irq_number: Integer IRQ number.
        :param online_cpus: List of online CPU indices returned by
                            :func:`avocado.utils.cpu.online_list`.
        :return: ``True`` on success, ``False`` on failure.
        :rtype: bool
        """
        affinity_str = '%d-%d' % (online_cpus[0], online_cpus[-1])
        affinity_path = '/proc/irq/%d/smp_affinity_list' % irq_number
        result = process.run(
            "echo %s > %s" % (affinity_str, affinity_path),
            shell=True, ignore_status=True)
        return result.exit_status == 0

    def _validate_irq_affinity_all_cpus(self, irq_number, online_cpus):
        """
        Confirm that ``/proc/irq/<irq>/smp_affinity_list`` spans all online
        CPUs (i.e. the range covers cpu[0] through cpu[-1]).

        :param irq_number: Integer IRQ number to inspect.
        :param online_cpus: List of online CPU indices.
        :raises: :class:`avocado.core.exceptions.TestFail` if the affinity
                 range read back does not match the expected span.
        """
        affinity_path = '/proc/irq/%d/smp_affinity_list' % irq_number
        current = genio.read_file(affinity_path).strip()
        expected = '%d-%d' % (online_cpus[0], online_cpus[-1])
        if current != expected:
            self.fail(
                "IRQ %d smp_affinity_list is '%s'; expected '%s' "
                "(all online CPUs)" % (irq_number, current, expected))
        self.log.info("IRQ %d affinity validated: %s", irq_number, current)

    def _setup_irq_affinity_all_disks(self):
        """
        For every disk provided in the YAML config, resolve its interrupt
        token, collect all associated IRQ numbers, and set the
        ``smp_affinity_list`` to span all online CPUs.

        :return: Flat list of (irq_number, ipi_name) tuples that were
                 successfully configured.
        :rtype: list[tuple[int, str]]
        """
        online_cpus = cpu.online_list()
        if len(online_cpus) < 2:
            self.cancel("Need at least 2 online CPUs for affinity test")

        configured = []
        for dev_path in self.disks:
            ipi_name = self._get_disk_ipi_name(dev_path)
            irq_numbers = self._get_device_irq_numbers(ipi_name)
            if not irq_numbers:
                self.log.warning(
                    "No IRQs found for device %s (%s); skipping affinity "
                    "setup for this device", dev_path, ipi_name)
                continue
            self.log.info("Device %s (%s): IRQs %s",
                          dev_path, ipi_name, irq_numbers)
            for irq in irq_numbers:
                if self._set_irq_affinity_all_cpus(irq, online_cpus):
                    self.log.info(
                        "Set affinity for IRQ %d -> CPUs %d-%d",
                        irq, online_cpus[0], online_cpus[-1])
                    configured.append((irq, ipi_name))
                else:
                    self.log.warning(
                        "Failed to set affinity for IRQ %d on %s",
                        irq, dev_path)

        if not configured:
            self.fail("Could not configure CPU affinity for any block device "
                      "IRQ; check /proc/interrupts for device names")
        return configured

    def _validate_irq_affinity_all_disks(self, configured_irqs):
        """
        Validate that every previously configured IRQ still has the expected
        full-CPU-span affinity.  Collects all failures before reporting so
        one bad IRQ does not mask the rest.

        :param configured_irqs: List of (irq_number, ipi_name) tuples from
                                :meth:`_setup_irq_affinity_all_disks`.
        """
        online_cpus = cpu.online_list()
        failures = []
        for irq, ipi_name in configured_irqs:
            affinity_path = '/proc/irq/%d/smp_affinity_list' % irq
            current = genio.read_file(affinity_path).strip()
            expected = '%d-%d' % (online_cpus[0], online_cpus[-1])
            if current != expected:
                failures.append(
                    "IRQ %d (%s): affinity '%s' != expected '%s'"
                    % (irq, ipi_name, current, expected))
            else:
                self.log.info(
                    "IRQ %d (%s) affinity OK: %s", irq, ipi_name, current)
        if failures:
            self.fail("CPU affinity mismatch after SMT/HTX stress:\n  %s"
                      % "\n  ".join(failures))

    def _check_current_smt(self):
        """
        Return the current SMT level as a string by parsing
        ``ppc64_cpu --smt`` output.

        :return: SMT level string, e.g. ``'8'`` or ``'off'``.
        :rtype: str
        """
        cmd = ("ppc64_cpu --smt | awk 'NR==1 {split($0, arr, \"=\"); "
               "split(arr[2], num, \":\"); print num[1]}'")
        return process.system_output(
            cmd, shell=True, ignore_status=True).decode('utf-8').strip()

    def _set_smt_level(self, value):
        """
        Set the system SMT level using ``ppc64_cpu --smt=<value>``.

        :param value: SMT level — an integer (1, 2, 4, 8) or the strings
                      ``'on'`` / ``'off'``.
        :return: ``True`` if the command succeeded, ``False`` otherwise.
        :rtype: bool
        """
        result = process.run(
            "ppc64_cpu --smt=%s" % value,
            shell=True, ignore_status=True)
        return result.exit_status == 0

    def _smt_cycling_worker(self, stop_event, interval_sec, smt_cycle_errors):
        """
        Background thread target: cycle through :attr:`SMT_LEVELS` every
        *interval_sec* seconds until *stop_event* is set.

        Failures are appended to *smt_cycle_errors* so the main thread can
        inspect them after the stress run.

        :param stop_event: :class:`threading.Event` used to signal the thread
                           to exit cleanly.
        :param interval_sec: Seconds to sleep between SMT level changes.
        :param smt_cycle_errors: Shared list for collecting error strings.
        """
        idx = 0
        smt_sequence = self.SMT_LEVELS
        while not stop_event.is_set():
            level = smt_sequence[idx % len(smt_sequence)]
            self.log.info("SMT cycle: setting --smt=%s", level)
            if not self._set_smt_level(level):
                msg = "ppc64_cpu --smt=%s failed during SMT cycling" % level
                self.log.warning(msg)
                smt_cycle_errors.append(msg)
            idx += 1
            stop_event.wait(timeout=interval_sec)

    def test_irqbalance_block_devices(self):
        """
        HTX block-device stress + concurrent SMT cycling + CPU affinity
        validation for all provided block devices (1-hour run).

        Validates the following goodpath scenario:
        1. HTX stress exerciser runs on all YAML-supplied block devices for
           the full stress duration (default 60 minutes).
        2. A background thread changes the SMT level every 60 seconds,
           cycling through off / 1 / 2 / 4 / 8 / on.
        3. Before the stress run, ``smp_affinity_list`` for every IRQ
           associated with each block device is set to span all online CPUs.
        4. After the stress run completes the same affinity entries are
           re-validated to confirm that the kernel has not silently narrowed
           them during SMT changes.
        5. ``dmesg`` is scanned for kernel error signatures at the end.

        YAML parameters
        ---------------
        disks
            Space-separated block device paths (required).
        htx_run_type
            Set to ``'git'`` to build HTX from GitHub source.
        htx_rpm_link
            Base URL for pre-built HTX RPM packages.
        """
        if 'ppc64' not in self.detected_distro.arch:
            self.cancel(
                "test_irqbalance_block_devices requires ppc64 platform "
                "(ppc64_cpu utility not available on %s)"
                % self.detected_distro.arch)

        mdt_file = self.HTX_MDT_FILE
        stress_duration_min = self.IRQ_HTX_STRESS_DURATION_MIN
        smt_interval = self.SMT_CHANGE_INTERVAL_SEC
        stress_duration_sec = stress_duration_min * 60

        # ------------------------------------------------------------------
        # Step 1: Record initial SMT state and bring system to max SMT so
        #         the full online_list() is available for affinity setup.
        # ------------------------------------------------------------------
        self._initial_smt = self._check_current_smt()
        self.log.info("Initial SMT level: %s", self._initial_smt)
        wait.wait_for(lambda: self._set_smt_level(8), timeout=300, step=5)
        self._cpu_list = cpu.online_list()
        self.log.info("Online CPUs at test start: %s", self._cpu_list)

        # ------------------------------------------------------------------
        # Step 2: Install HTX and activate block devices in the MDT.
        # ------------------------------------------------------------------
        self.log.info("Installing HTX")
        self._install_htx()

        block_device = self._htx_block_device_list()
        self.log.info("HTX target devices: %s", block_device)
        self._setup_htx_mdt(mdt_file, block_device)

        # ------------------------------------------------------------------
        # Step 3: Set smp_affinity_list to all CPUs for every device IRQ.
        # ------------------------------------------------------------------
        self.log.info("Setting CPU affinity for all block device IRQs")
        configured_irqs = self._setup_irq_affinity_all_disks()
        self.log.info(
            "Affinity configured for %d IRQ(s): %s",
            len(configured_irqs),
            [(irq, name) for irq, name in configured_irqs])

        # ------------------------------------------------------------------
        # Step 4: Start HTX stress run.
        # ------------------------------------------------------------------
        self.log.info(
            "Starting HTX stress run (%d min) on: %s",
            stress_duration_min, block_device)
        process.system(
            "htxcmdline -run -mdt %s" % mdt_file, ignore_status=True)

        # ------------------------------------------------------------------
        # Step 5: Launch SMT cycling thread (changes every smt_interval sec).
        # ------------------------------------------------------------------
        smt_cycle_errors = []
        stop_smt = threading.Event()
        smt_thread = threading.Thread(
            target=self._smt_cycling_worker,
            args=(stop_smt, smt_interval, smt_cycle_errors),
            daemon=True,
            name='smt-cycle')
        smt_thread.start()
        self.log.info(
            "SMT cycling thread started (interval: %d s, levels: %s)",
            smt_interval, self.SMT_LEVELS)

        # ------------------------------------------------------------------
        # Step 6: Poll HTX for errors throughout the stress duration.
        # ------------------------------------------------------------------
        poll_interval_sec = 60
        elapsed = 0
        while elapsed < stress_duration_sec:
            time.sleep(poll_interval_sec)
            elapsed += poll_interval_sec
            self.log.info(
                "HTX poll at %d / %d s", elapsed, stress_duration_sec)

            process.run("htxcmdline -geterrlog", ignore_status=True)
            htx_err_file = '/tmp/htxerr'
            if (os.path.exists(htx_err_file)
                    and os.stat(htx_err_file).st_size != 0):
                self.log.error(
                    "HTX errors detected at %d s; see %s",
                    elapsed, htx_err_file)
                self.err_messages.append(
                    "HTX errors at %d s; check %s" % (elapsed, htx_err_file))

            process.system(
                "htxcmdline -query %s -mdt %s" % (block_device, mdt_file),
                ignore_status=True)

        # ------------------------------------------------------------------
        # Step 7: Stop SMT cycling and restore maximum SMT for validation.
        # ------------------------------------------------------------------
        self.log.info("Stopping SMT cycling thread")
        stop_smt.set()
        smt_thread.join(timeout=smt_interval + 10)
        self.err_messages.extend(smt_cycle_errors)

        self.log.info("Restoring SMT to max (8) for affinity validation")
        wait.wait_for(lambda: self._set_smt_level(8), timeout=300, step=5)

        # ------------------------------------------------------------------
        # Step 8: Stop HTX and check final error log.
        # ------------------------------------------------------------------
        self._stop_htx(block_device, mdt_file)
        process.run("htxcmdline -geterrlog", ignore_status=True)
        if (os.path.exists('/tmp/htxerr')
                and os.stat('/tmp/htxerr').st_size != 0):
            self.err_messages.append(
                "HTX errors in final error log; check /tmp/htxerr")

        # ------------------------------------------------------------------
        # Step 9: Re-validate that CPU affinity for all IRQs is still intact.
        # ------------------------------------------------------------------
        self.log.info("Validating CPU affinity for all block device IRQs")
        self._validate_irq_affinity_all_disks(configured_irqs)

        # ------------------------------------------------------------------
        # Step 10: Scan dmesg for kernel error signatures.
        # ------------------------------------------------------------------
        self.log.info("Scanning dmesg for errors")
        dmesg.collect_errors_dmesg(self.DMESG_ERROR_PATTERNS)

        # ------------------------------------------------------------------
        # Final result
        # ------------------------------------------------------------------
        if self.err_messages:
            self.fail(
                "test_irqbalance_block_devices FAILED: %s"
                % self.err_messages)
        self.log.info("test_irqbalance_block_devices: PASS")

    def tearDown(self):
        """
        Clean up all test artifacts.

        Unmounts the test filesystem partition (if mounted), restores the
        SMT level to what it was at test entry (if
        test_irqbalance_block_devices ran), brings all CPUs back online, then
        delegates full disk cleanup to cleanup_disks(mode="full") which
        handles the complete dependency chain: LVM removal -> RAID stop +
        superblock clear -> partition table wipe -> metadata wipe ->
        disk zeroing.
        """
        self.log.info("Starting teardown")

        # Restore SMT to initial level recorded by
        # test_irqbalance_block_devices
        if hasattr(self, '_initial_smt') and self._initial_smt:
            self.log.info("Restoring SMT to initial level: %s",
                          self._initial_smt)
            process.system(
                "ppc64_cpu --smt=%s" % self._initial_smt,
                shell=True, ignore_status=True)

        # Bring all CPUs back online after any SMT off/cycling
        if hasattr(self, '_cpu_list') and self._cpu_list:
            self.log.info("Re-onlining all CPUs used in test")
            for cpu_id in self._cpu_list:
                cpu.online(cpu_id)

        if hasattr(self, 'part_obj') and self.part_obj:
            try:
                self.log.info("Unmounting filesystem")
                self.part_obj.unmount()
            except Exception as err:
                self.log.warning("Failed to unmount filesystem: %s", err)

        if getattr(self, 'disks', None):
            try:
                self.log.info("Starting disk cleanup for %s", self.disks)
                cleanup_disks(self.disks, logger=self.log, mode="full")
                self.log.info("Disk cleanup completed successfully")
            except Exception as err:
                self.log.error("Disk cleanup failed: %s", err)

        self.log.info("Teardown complete")
