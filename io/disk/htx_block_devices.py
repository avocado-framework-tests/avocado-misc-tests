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
# Author: Naresh Bannoth<nbannoth@in.ibm.com>
#         Maram Srimannarayana Murthy<msmurthy@linux.vnet.ibm.com>
# this script run IO stress on block devices for give time.

"""
HTX Test

Provides two public symbols:

``HtxHelper``
    A plain Python class (no Avocado dependency) that encapsulates every
    HTX orchestration operation.  Designed to be instantiated by any
    Avocado test that needs HTX functionality without inheriting from
    ``HtxTest``.  All methods that previously called ``self.fail()`` or
    ``self.cancel()`` now raise ``RuntimeError`` or ``EnvironmentError``
    respectively so callers can map them to the appropriate Avocado
    outcome.

``HtxTest``
    The original Avocado test class.  It instantiates ``HtxHelper`` in
    ``setUp()`` and delegates every operation to it, keeping the public
    method signatures and YAML parameter names completely unchanged.
"""

import os
import re
import shutil
import time

from avocado import Test
from avocado.utils import archive
from avocado.utils import build
from avocado.utils import disk
from avocado.utils import distro
from avocado.utils import multipath
from avocado.utils import process
from avocado.utils.software_manager.manager import SoftwareManager

HTX_INSTALL_PATH = '/usr/lpp/htx'


class HtxHelper:
    """
    HTX orchestration helper — no Avocado ``Test`` inheritance.

    Encapsulates HTX installation, MDT lifecycle, device activation,
    error polling, and teardown.  Constructor arguments are used as
    defaults when method parameters are omitted.
    """

    def __init__(
        self,
        log,
        fetch_asset=None,
        teststmpdir=None,
        block_device='',
        mdt_file='mdt.hd',
        time_limit=60,
        dist_name='',
        dist_version='',
        run_type='',
        rpm_link=None,
        run_all=False,
    ):
        self.log = log
        self.fetch_asset = fetch_asset
        self.teststmpdir = teststmpdir
        self.block_device = block_device
        self.mdt_file = mdt_file
        self.time_limit = time_limit
        self.dist_name = dist_name
        self.dist_version = dist_version
        self.run_type = run_type
        self.rpm_link = rpm_link
        self.run_all = run_all

    @staticmethod
    def resolve_block_devices(raw_devices):
        """
        Resolve raw device names/paths to bare basenames for htxcmdline.
        DM multipath devices are mapped to their mpathX name.
        :param raw_devices: Whitespace-separated device names or paths.
        :return: Space-separated string of resolved device basenames.
        """
        resolved = []
        for dev in raw_devices.split():
            dev_path = disk.get_absolute_disk_path(dev)
            dev_base = os.path.basename(os.path.realpath(dev_path))
            if 'dm' in dev_base:
                dev_base = multipath.get_mpath_from_dm(dev_base)
            resolved.append(dev_base)
        return ' '.join(resolved)

    def setup_htx(self, dist_name=None, dist_version=None, run_type=None):
        """
        Install build-tool prerequisites and HTX for the given distro.
        :param dist_name: Distribution name (default: self.dist_name).
        :param dist_version: Distro version (default: self.dist_version).
        :param run_type: ``"git"`` for source build; else RPM install.
        :raises EnvironmentError: On unsupported distro or install failure.
        """
        if dist_name is None:
            dist_name = self.dist_name
        if dist_version is None:
            dist_version = self.dist_version
        if run_type is None:
            run_type = self.run_type

        packages = ['git', 'gcc', 'make']
        if dist_name in ['centos', 'fedora', 'rhel', 'redhat']:
            packages.extend(['gcc-c++', 'ncurses-devel', 'tar'])
        elif dist_name == 'Ubuntu':
            packages.extend(['libncurses5', 'g++', 'ncurses-dev',
                             'libncurses-dev', 'tar'])
        elif dist_name == 'SuSE':
            packages.extend(['libncurses5', 'gcc-c++', 'ncurses-devel', 'tar'])
        else:
            raise EnvironmentError(
                'HTX setup_htx: unsupported distro %s' % dist_name)

        smm = SoftwareManager()
        for pkg in packages:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                raise EnvironmentError(
                    'HTX setup_htx: cannot install package %s' % pkg)

        if run_type == 'git':
            self._build_htx_from_git(dist_name)
        else:
            self._install_htx_rpm_auto(dist_name, dist_version)

    def _build_htx_from_git(self, dist_name):
        """
        Build and install HTX from the open-power GitHub source tree.

        :param dist_name: Distribution name (for logging only).
        :raises RuntimeError: If the HTX installer exits non-zero.
        """
        if self.fetch_asset is None:
            raise EnvironmentError(
                'HtxHelper: fetch_asset callable is required for git builds')
        if self.teststmpdir is None:
            raise EnvironmentError(
                'HtxHelper: teststmpdir must be set for git builds')

        self.log.info('Building HTX from GitHub source (distro: %s)',
                      dist_name)
        url = 'https://github.com/open-power/HTX/archive/master.zip'
        tarball = self.fetch_asset('htx.zip', locations=[url], expire='7d')
        archive.extract(tarball, self.teststmpdir)
        htx_path = os.path.join(self.teststmpdir, 'HTX-master')
        os.chdir(htx_path)

        exercisers = ['hxecapi_afu_dir', 'hxedapl', 'hxecapi', 'hxeocapi']
        for exerciser in exercisers:
            process.run(
                "sed -i 's/%s,//g' %s/bin/Makefile" % (exerciser, htx_path),
                ignore_status=True, shell=True)

        build.make(htx_path, extra_args='all')
        build.make(htx_path, extra_args='tar')
        process.run('tar --touch -xvzf htx_package.tar.gz')
        os.chdir('htx_package')
        if process.system('./installer.sh -f'):
            raise RuntimeError(
                'HTX installation from source failed; see job.log')

    def _install_htx_rpm_auto(self, dist_name, dist_version):
        """
        Install the distro-specific HTX RPM; reuse if already matching.

        :param dist_name: Distribution name.
        :param dist_version: Distribution major-version string.
        """
        if dist_name.lower() == 'suse':
            dist_name = 'sles'

        rpm_check = 'htx%s%s' % (dist_name, dist_version)
        smm = SoftwareManager()
        skip_install = False

        ins_htx = process.system_output(
            'rpm -qa | grep htx', shell=True,
            ignore_status=True).decode().strip()

        if ins_htx:
            if smm.check_installed(rpm_check):
                self.log.info('Existing HTX RPM %s matches; reusing',
                              rpm_check)
                skip_install = True
            else:
                self.log.info('Removing mismatched HTX RPM: %s', ins_htx)
                process.system('rpm -e %s' % ins_htx,
                               shell=True, ignore_status=True)
                if os.path.exists(HTX_INSTALL_PATH):
                    shutil.rmtree(HTX_INSTALL_PATH)

        if not skip_install and self.rpm_link:
            self.install_htx_rpm(self.rpm_link, dist_name, dist_version)

    def install_htx_rpm(self, rpm_link=None, dist_name=None,
                        dist_version=None):
        """
        Download and install the latest HTX RPM for the given distro.
        :param rpm_link: Direct .rpm URL or repo URL (default: self.rpm_link).
        :param dist_name: Distro name to filter RPMs (default: self.dist_name).
        :param dist_version: Distro version (default: self.dist_version).
        :raises EnvironmentError: If the RPM cannot be downloaded or installed.
        """
        if rpm_link is None:
            rpm_link = self.rpm_link
        if dist_name is None:
            dist_name = self.dist_name
        if dist_version is None:
            dist_version = self.dist_version

        if rpm_link.endswith('.rpm'):
            latest_htx_rpm = os.path.basename(rpm_link)
            tmp_dir_rpm = '/tmp/' + latest_htx_rpm
            cmd = 'curl -kL %s -o %s' % (rpm_link, tmp_dir_rpm)
            if process.system(cmd, shell=True, ignore_status=True):
                raise EnvironmentError(
                    'Download of HTX RPM %s failed from %s'
                    % (latest_htx_rpm, rpm_link))
        else:
            distro_pattern = '%s%s' % (dist_name, dist_version)
            temp_string = process.getoutput(
                'curl --silent -kL %s' % rpm_link,
                verbose=False, shell=True, ignore_status=True)
            matching_htx_versions = re.findall(
                r'(?<=\>)htx\w*[-]\d*[-]\w*[.]\w*[.]\w*', str(temp_string))
            distro_specific_htx_versions = [
                r for r in matching_htx_versions if distro_pattern in r]
            distro_specific_htx_versions.sort(reverse=True)
            if not distro_specific_htx_versions:
                raise EnvironmentError(
                    'No HTX RPM found for %s at %s'
                    % (distro_pattern, rpm_link))
            latest_htx_rpm = distro_specific_htx_versions[0]
            tmp_dir_rpm = '/tmp/' + latest_htx_rpm
            cmd = 'curl -kL %s/%s -o %s' % (rpm_link, latest_htx_rpm,
                                            tmp_dir_rpm)
            if process.system(cmd, shell=True, ignore_status=True):
                raise EnvironmentError(
                    'Download of HTX RPM %s failed from %s'
                    % (latest_htx_rpm, rpm_link))

        if process.system('rpm -ivh --nodeps %s --force' % tmp_dir_rpm,
                          shell=True, ignore_status=True):
            raise EnvironmentError(
                'Installation of HTX RPM %s failed' % tmp_dir_rpm)

        self.log.info('HTX RPM %s installed successfully', latest_htx_rpm)

    def ensure_daemon_running(self):
        """
        Start the HTX daemon via htxd_run if it is not already running.

        A 5-second settle delay is applied after starting the daemon.
        """
        daemon_state = process.system_output(
            '%s/etc/scripts/htx.d status' % HTX_INSTALL_PATH,
            ignore_status=True).decode('utf-8').strip()
        if daemon_state.split()[-1:] != ['running']:
            self.log.info('htxd is not running; starting it')
            process.run('%s/etc/scripts/htxd_run' % HTX_INSTALL_PATH,
                        ignore_status=True)
            time.sleep(5)

    def stop_daemon(self):
        """
        Shut down the HTX daemon if it is currently running.
        """
        daemon_state = process.system_output(
            '%s/etc/scripts/htx.d status' % HTX_INSTALL_PATH,
            ignore_status=True).decode('utf-8').strip()
        if daemon_state.split()[-1:] == ['running']:
            process.system('%s/etc/scripts/htxd_shutdown' % HTX_INSTALL_PATH,
                           ignore_status=True)

    def start_htx(self, block_device=None, mdt_file=None):
        """
        Install HTX, select MDT, activate devices, and start the run.
        :param block_device: Device basenames; None uses self.block_device.
        :param mdt_file: HTX MDT filename (default: self.mdt_file).
        :raises RuntimeError: If MDT creation or device activation fails.
        """
        if block_device is None:
            block_device = self.block_device
        if mdt_file is None:
            mdt_file = self.mdt_file

        self.setup_htx()

        self.log.info('Stopping existing HXE process')
        hxe_pid = process.getoutput('pgrep -f hxe', ignore_status=True)
        if hxe_pid.strip():
            self.log.info('HXE is running with PID %s; shutting down',
                          hxe_pid.strip())
            process.run('hcl -shutdown', ignore_status=True)
            time.sleep(20)

        self.ensure_daemon_running()

        self.log.info('Creating the HTX mdt files')
        process.run('htxcmdline -createmdt', ignore_status=True)

        mdt_path = '%s/mdt/%s' % (HTX_INSTALL_PATH, mdt_file)
        if not os.path.exists(mdt_path):
            process.run('htxcmdline -createmdt -mdt %s' % mdt_file,
                        ignore_status=True)
            if not os.path.exists(mdt_path):
                raise RuntimeError('MDT file %s creation failed' % mdt_file)

        self.log.info('Selecting the MDT file: %s', mdt_file)
        process.system('htxcmdline -select -mdt %s' % mdt_file,
                       ignore_status=True)

        if not self.run_all:
            if not self.is_block_device_in_mdt(block_device, mdt_file):
                raise RuntimeError(
                    'Block devices %s are not available in %s'
                    % (block_device, mdt_file))

        self.suspend_all_block_device(mdt_file)

        self.log.info('Activating %s', block_device)
        process.system('htxcmdline -activate %s -mdt %s'
                       % (block_device, mdt_file), ignore_status=True)

        if not self.run_all:
            if not self.is_block_device_active(block_device, mdt_file):
                raise RuntimeError('Block devices failed to activate')

        self.log.info('Running HTX on %s', block_device)
        process.system('htxcmdline -run -mdt %s' % mdt_file,
                       ignore_status=True)

    def check_htx(self, block_device=None, mdt_file=None, time_limit=None):
        """
        Poll HTX error log and device status every 60 s for time_limit seconds.
        :param block_device: Device basenames; None uses self.block_device.
        :param mdt_file: MDT filename; None uses self.mdt_file.
        :param time_limit: Poll duration in seconds; None uses self.time_limit.
        :raises RuntimeError: If /tmp/htxerr is non-empty at any poll interval.
        """
        if block_device is None:
            block_device = self.block_device
        if mdt_file is None:
            mdt_file = self.mdt_file
        if time_limit is None:
            time_limit = self.time_limit

        for _ in range(0, time_limit, 60):
            self.log.info('HTX Error logs')
            process.run('htxcmdline -geterrlog', ignore_status=True)
            if os.stat('/tmp/htxerr').st_size != 0:
                raise RuntimeError(
                    'HTX errors detected; check /tmp/htxerr for details')
            self.log.info('Status of block devices after every 60 sec')
            process.system('htxcmdline -query %s -mdt %s'
                           % (block_device, mdt_file), ignore_status=True)
            time.sleep(60)

    def is_block_device_in_mdt(self, block_device=None, mdt_file=None):
        """
        Return True if all block devices appear in the MDT query output.
        :param block_device: Device basenames; None uses self.block_device.
        :param mdt_file: HTX MDT filename (default: self.mdt_file).
        :return: True if all present, False if any device is missing.
        """
        if block_device is None:
            block_device = self.block_device
        if mdt_file is None:
            mdt_file = self.mdt_file

        self.log.info(
            'Checking if block devices are present in %s', mdt_file)
        output = process.system_output(
            'htxcmdline -query -mdt %s' % mdt_file,
            ignore_status=True).decode('utf-8')
        missing = [dev for dev in block_device.split() if dev not in output]
        if missing:
            self.log.info(
                'Block devices %s are not available in %s', missing, mdt_file)
            return False
        self.log.info('Block devices %s are available in %s',
                      block_device, mdt_file)
        return True

    def suspend_all_block_device(self, mdt_file=None):
        """
        Suspend all active block devices in the MDT.

        :param mdt_file: HTX MDT filename.  Defaults to ``self.mdt_file``.
        """
        if mdt_file is None:
            mdt_file = self.mdt_file

        self.log.info('Suspending all block devices in MDT %s', mdt_file)
        process.system('htxcmdline -suspend all -mdt %s' % mdt_file,
                       ignore_status=True)

    def is_block_device_active(self, block_device=None, mdt_file=None):
        """
        Return True if all specified block devices show ACTIVE in the MDT.
        :param block_device: Device basenames; None uses self.block_device.
        :param mdt_file: HTX MDT filename (default: self.mdt_file).
        :return: True if all ACTIVE, False if any device is not active.
        """
        if block_device is None:
            block_device = self.block_device
        if mdt_file is None:
            mdt_file = self.mdt_file

        self.log.info('Checking whether all block devices are active')
        output = process.system_output(
            'htxcmdline -query %s -mdt %s' % (block_device, mdt_file),
            ignore_status=True).decode('utf-8').split('\n')
        device_list = block_device.split()
        active_devices = [
            dev for line in output for dev in device_list
            if dev in line and 'ACTIVE' in line
        ]
        non_active = list(set(device_list) - set(active_devices))
        if non_active:
            self.log.info('Devices not active: %s', non_active)
            return False
        self.log.info('All block devices are ACTIVE: %s', block_device)
        return True

    def stop_htx(self, block_device=None, mdt_file=None):
        """
        Suspend all devices, shut down the MDT, and stop the HTX daemon.

        :param block_device: Space-separated device basenames;
            defaults to self.block_device.
        :param mdt_file: HTX MDT filename; defaults to self.mdt_file.
        """
        if block_device is None:
            block_device = self.block_device
        if mdt_file is None:
            mdt_file = self.mdt_file

        self.log.info('Suspending block devices before HTX shutdown')
        self.suspend_all_block_device(mdt_file)
        self.log.info('Shutting down HTX MDT: %s', mdt_file)
        process.system('htxcmdline -shutdown -mdt %s' % mdt_file,
                       timeout=120, ignore_status=True)
        self.stop_daemon()


class HtxTest(Test):
    """
    HTX [Hardware Test eXecutive] is a test tool suite.  The goal of HTX is
    to stress test the system by exercising all hardware components
    concurrently in order to uncover hardware design flaws and
    hardware/software interaction issues.

    :see: https://github.com/open-power/HTX.git

    YAML parameters
    ---------------
    htx_disks
        Space-separated block device names/paths to stress-test.
    mdt_file
        HTX MDT filename (default: ``mdt.hd``).
    time_limit
        Stress duration in **hours** (default: ``1``).
    all
        Set to ``true`` to exercise *all* devices in the selected MDT
        rather than the explicit ``htx_disks`` list.
    run_type
        Set to ``"git"`` to build HTX from GitHub source.
    htx_rpm_link
        Base URL or direct URL for a pre-built HTX RPM package.
    """

    def setUp(self):
        """
        Validate platform, parse YAML parameters, resolve device names,
        and instantiate :class:`HtxHelper`.
        """
        if 'ppc64' not in distro.detect().arch:
            self.cancel('Platform does not support HTX')

        self.mdt_file = self.params.get('mdt_file', default='mdt.hd')
        self.time_limit = int(self.params.get('time_limit', default=1)) * 60
        self.block_devices = self.params.get('htx_disks', default=None)
        self.all = self.params.get('all', default=False)
        self.run_type = self.params.get('run_type', default='')

        detected_distro = distro.detect()

        if not self.all and self.block_devices is None:
            self.cancel('Needs the block devices to run the HTX')

        if self.all:
            block_device = ''
        else:
            block_device = HtxHelper.resolve_block_devices(self.block_devices)

        self._htx = HtxHelper(
            log=self.log,
            fetch_asset=self.fetch_asset,
            teststmpdir=self.teststmpdir,
            block_device=block_device,
            mdt_file=self.mdt_file,
            time_limit=self.time_limit,
            dist_name=detected_distro.name,
            dist_version=detected_distro.version,
            run_type=self.run_type,
            rpm_link=self.params.get('htx_rpm_link', default=None),
            run_all=self.all,
        )
        # Keep self.block_device for backward compatibility with any
        # subclasses or external callers that read the attribute directly.
        self.block_device = block_device

    def setup_htx(self, dist_name=None, dist_version=None, run_type=None):
        """
        Install or build HTX for the current or specified distro.

        :param dist_name: Distro name; defaults to the detected distro.
        :param dist_version: Distro version string; defaults to detected.
        :param run_type: ``"git"`` for source build; else RPM install.
        """
        try:
            self._htx.setup_htx(dist_name, dist_version, run_type)
        except EnvironmentError as err:
            self.cancel(str(err))

    def install_htx_rpm(self, rpm_link=None, dist_name=None,
                        dist_version=None):
        """
        Download and install the latest HTX RPM for the given distro.

        :param rpm_link: Base URL or direct ``.rpm`` URL.
        :param dist_name: Distribution name.
        :param dist_version: Distribution version string.
        """
        try:
            self._htx.install_htx_rpm(rpm_link, dist_name, dist_version)
        except EnvironmentError as err:
            self.cancel(str(err))

    def start_htx(self, block_device=None, mdt_file=None):
        """
        Bring up HTX: install, configure MDT, activate devices, and run.

        :param block_device: Space-separated device basename string.
        :param mdt_file: HTX MDT filename.
        """
        try:
            self._htx.start_htx(block_device, mdt_file)
        except EnvironmentError as err:
            self.cancel(str(err))
        except RuntimeError as err:
            self.fail(str(err))

    def test_start(self):
        """
        Execute HTX with parameters from the YAML configuration.
        """
        self.start_htx()

    def check_htx(self, block_device=None, mdt_file=None, time_limit=None):
        """
        Poll the HTX error log and device status for the full run duration.

        :param block_device: Space-separated device basename string.
        :param mdt_file: HTX MDT filename.
        :param time_limit: Total polling duration in seconds.
        """
        try:
            self._htx.check_htx(block_device, mdt_file, time_limit)
        except RuntimeError as err:
            self.fail(str(err))

    def test_check(self):
        """
        Check whether HTX is running and free of errors.
        """
        self.check_htx()

    def is_block_device_in_mdt(self, block_device=None, mdt_file=None):
        """
        Verify the presence of given block devices in the selected MDT.

        :param block_device: Space-separated device basename string.
        :param mdt_file: HTX MDT filename.
        :return: ``True`` if all devices are present, ``False`` otherwise.
        :rtype: bool
        """
        return self._htx.is_block_device_in_mdt(block_device, mdt_file)

    def suspend_all_block_device(self, mdt_file=None):
        """
        Suspend all active block devices in the MDT.

        :param mdt_file: HTX MDT filename.
        """
        self._htx.suspend_all_block_device(mdt_file)

    def is_block_device_active(self, block_device=None, mdt_file=None):
        """
        Verify whether all specified block devices are ACTIVE in the MDT.

        :param block_device: Space-separated device basename string.
        :param mdt_file: HTX MDT filename.
        :return: ``True`` if all devices are active, ``False`` otherwise.
        :rtype: bool
        """
        return self._htx.is_block_device_active(block_device, mdt_file)

    def test_stop(self):
        """
        Shut down the MDT and the HTX daemon.
        """
        self.stop_htx()

    def stop_htx(self, block_device=None, mdt_file=None):
        """
        Stop the HTX run gracefully.

        :param block_device: Space-separated device basename string.
        :param mdt_file: HTX MDT filename.
        """
        self._htx.stop_htx(block_device, mdt_file)
