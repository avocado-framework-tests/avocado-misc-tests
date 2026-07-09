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

        if str(self.name.name).endswith('test_start'):
            self.setup_htx()

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
        packages = ['gcc', 'make', 'ndctl']
        name = self.detected_distro.name
        if name in ['centos', 'fedora', 'rhel', 'redhat']:
            packages.extend(['gcc-c++', 'ncurses-devel', 'tar'])
        elif name == 'Ubuntu':
            packages.extend(['libncurses5', 'g++',
                             'ncurses-dev', 'libncurses-dev', 'tar'])
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

        if self.htx_disks or self.run_all:
            if not self.run_all:
                if not self.is_block_device_in_mdt():
                    self.fail(
                        f"Block devices {self.block_device} not found"
                        f" in MDT {self.mdt_file}")

            self.suspend_all_block_device()

            self.log.info("Activating block device(s): %s", self.block_device)
            process.system(
                f'htxcmdline -activate {self.block_device}'
                f' -mdt {self.mdt_file}',
                ignore_status=True)

            if not self.run_all:
                if not self.is_block_device_active():
                    self.fail(
                        f"Block devices {self.block_device}"
                        f" failed to reach ACTIVE state")
        else:
            self.log.info("Activating MDT: %s", self.mdt_file)
            process.system(f'htxcmdline -activate -mdt {self.mdt_file}',
                           ignore_status=True)

        self.log.info("Configuring HTX_DR_TEST environment variable")
        process.system('hcl -get_htx_env HTX_DR_TEST', ignore_status=True)
        process.system('hcl -set_htx_env HTX_DR_TEST 1', ignore_status=True)
        process.system('hcl -get_htx_env HTX_DR_TEST', ignore_status=True)

        self.log.info("Starting HTX run on MDT: %s", self.mdt_file)
        process.system(f'htxcmdline -run -mdt {self.mdt_file}',
                       ignore_status=True)

    def test_check(self):
        """
        Checks if HTX is running, and if no errors.
        """
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
