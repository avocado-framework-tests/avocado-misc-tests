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

import json
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
        self.htx_disks = self.params.get('htx_disks', default=None)
        self.vpmem = self.params.get('vpmem', default=False)

        _time_limit = self.params.get('time_limit', default=None)
        if _time_limit is not None:
            _unit = self.params.get('time_unit', default='m')
            _multiplier = 3600 if str(_unit).strip().lower() == 'h' else 60
            self.time_limit = int(_time_limit) * _multiplier
        else:
            self.time_limit = int(self.params.get('time_interval', default=2)) * 60
        self.run_all = self.params.get('all', default=False)
        self.rpm_link = self.params.get('htx_rpm_link', default=None)
        self.dist_name = None

        self.block_device = ''
        if self.htx_disks and not self.run_all:
            self.block_device = self._resolve_block_devices(self.htx_disks)

        if self.vpmem:
            self._ensure_ndctl_installed()
            self._validate_vpmem_devices()

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

    def _ensure_ndctl_installed(self):
        """
        Ensure ``ndctl`` is available on the system.

        Called unconditionally when ``vpmem: True`` so that both the
        pre-run validation and the post-run distribution check can use
        ``ndctl list``.  This is separate from :meth:`_get_distro_packages`
        which is only invoked during :meth:`setup_htx`.
        """
        smm = SoftwareManager()
        if not smm.check_installed('ndctl') and not smm.install('ndctl'):
            self.cancel(
                "Cannot install ndctl — required for vPMEM validation")
        self.log.info("ndctl is available")

    def _validate_vpmem_devices(self):
        """
        Pre-run vPMEM sanity checks.

        Performs three sequential steps:

        1. **Region existence** — runs ``ndctl list -Ru`` and verifies that
           at least one NVDIMM region is present.  On IBM Power these are
           created by the ``papr_scm`` driver when vPMEM is configured in
           the partition profile.  The test is cancelled (not failed) when
           no region is found because this indicates a missing firmware or
           driver configuration, not a product regression.

        2. **Namespace provisioning** — for each region that has no
           namespace, runs ``ndctl create-namespace -r <region>`` to
           provision one.  This is the normal path on IBM Power where
           namespaces are not created automatically by the firmware.
           The test is failed if namespace creation cannot be completed.

        3. **dmesg health** — scans the kernel ring buffer for lines
           associated with the vPMEM driver stack (``papr_scm``,
           ``libnvdimm``, ``nd_pmem``, ``pmem``) and fails the test if
           any of those lines contain error/fault indicators.

        :raises: Cancels the test when no vPMEM region is found.
        :raises: Fails the test when namespace creation fails or dmesg
                 reports vPMEM-related errors.
        """
        self.log.info("=== vPMEM pre-run validation ===")

        # ── 1. Region existence ──────────────────────────────────────────────
        # Use -Ru (regions only, human-readable sizes) first — namespaces
        # may not exist yet and their absence must not be a hard stop here.
        region_out = process.system_output(
            'ndctl list -Ru', shell=True,
            ignore_status=True).decode('utf-8', errors='replace').strip()
        self.log.info("ndctl list -Ru output:\n%s", region_out)

        if not region_out:
            self.cancel("ndctl list -Ru returned no output — "
                        "no vPMEM regions found; ensure papr_scm is "
                        "loaded and vPMEM is configured in the LPAR profile")

        try:
            region_data = json.loads(region_out)
        except json.JSONDecodeError as exc:
            self.cancel(f"Failed to parse ndctl region JSON output: {exc}")

        regions = (region_data
                   if isinstance(region_data, list) else [region_data])
        region_count = len(regions)
        self.log.info("vPMEM regions found: %d", region_count)

        if region_count == 0:
            self.cancel("No vPMEM regions detected — "
                        "ensure papr_scm is loaded and vPMEM is "
                        "configured in the LPAR profile")

        for region in regions:
            region_name = region.get('dev', 'unknown')
            region_size = region.get('size', 0)
            region_state = region.get('state', 'unknown')
            self.log.info(
                "  region=%-12s  size=%s  state=%s",
                region_name, region_size, region_state)

        # ── 2. Namespace provisioning ────────────────────────────────────────
        # Re-query with -RNu to discover existing namespaces per region.
        # ndctl list -RNu can return three different JSON shapes depending on
        # the kernel/ndctl version and number of regions:
        #   (a) bare list of region objects:  [{...}, ...]
        #   (b) single region object dict:    {"dev": "region0", ...}
        #   (c) wrapper dict with regions key: {"regions": [{...}, ...]}
        # Normalise all three into a flat list before building the ns_map.
        ndctl_out = process.system_output(
            'ndctl list -RNu', shell=True,
            ignore_status=True).decode('utf-8', errors='replace').strip()
        self.log.info("ndctl list -RNu output:\n%s", ndctl_out)

        try:
            ndctl_data = json.loads(ndctl_out) if ndctl_out else []
        except json.JSONDecodeError as exc:
            self.cancel(f"Failed to parse ndctl JSON output: {exc}")

        # Normalise to a flat list of region dicts.
        if isinstance(ndctl_data, list):
            rlist = ndctl_data
        elif isinstance(ndctl_data, dict):
            if 'regions' in ndctl_data:
                # shape (c): {"regions": [...]}
                rlist = ndctl_data['regions']
            else:
                # shape (b): single region object
                rlist = [ndctl_data]
        else:
            rlist = []

        ns_map = {r.get('dev'): r.get('namespaces', []) for r in rlist}

        for region in regions:
            region_name = region.get('dev', 'unknown')
            existing_ns = ns_map.get(region_name, [])
            # available_size is 0 when the region is fully allocated — use
            # the raw (non -u) region data from step 1 to get an integer.
            # The -Ru query returns size as a human string, so compare to
            # the string "0" as well as the integer 0 for robustness.
            avail = region.get('available_size', 0)
            region_full = (avail == 0 or avail == '0' or avail == '0 B')

            if not existing_ns and not region_full:
                self.log.info(
                    "No namespaces on %s and space is available — "
                    "creating one via ndctl", region_name)
                ret = process.system(
                    f'ndctl create-namespace -r {region_name}',
                    shell=True, ignore_status=True)
                if ret != 0:
                    self.fail(
                        f"ndctl create-namespace failed for region "
                        f"{region_name} (exit code {ret})")
                self.log.info(
                    "Namespace created successfully on %s", region_name)
            elif not existing_ns and region_full:
                self.fail(
                    f"Region {region_name} has no namespaces and "
                    f"available_size is 0 — region may be misconfigured")
            else:
                for ns in existing_ns:
                    ns_name = ns.get('dev', 'unknown')
                    ns_mode = ns.get('mode', 'unknown')
                    ns_size = ns.get('size', 0)
                    ns_state = ns.get('state', 'enabled')
                    self.log.info(
                        "  region=%-12s  ns=%-14s  mode=%-8s  "
                        "size=%s  state=%s",
                        region_name, ns_name, ns_mode, ns_size, ns_state)
                    if ns_state == 'disabled':
                        self.fail(
                            f"vPMEM namespace {ns_name} in region "
                            f"{region_name} is in 'disabled' state "
                            f"before HTX run")

        # ── 3. dmesg health check ────────────────────────────────────────────
        dmesg_out = process.system_output(
            'dmesg', shell=True,
            ignore_status=True).decode('utf-8', errors='replace')

        vpmem_drivers = ('papr_scm', 'libnvdimm', 'nd_pmem', 'pmem', 'nfit')
        error_patterns = re.compile(
            r'\b(error|fail(?:ed|ure)?|bug|oops|panic|corrupt|warn(?:ing)?)\b',
            re.IGNORECASE)

        vpmem_errors = []
        for line in dmesg_out.splitlines():
            line_lower = line.lower()
            if any(drv in line_lower for drv in vpmem_drivers):
                if error_patterns.search(line):
                    vpmem_errors.append(line.strip())

        if vpmem_errors:
            for err_line in vpmem_errors:
                self.log.error("dmesg vPMEM error: %s", err_line)
            self.fail(
                f"dmesg contains {len(vpmem_errors)} vPMEM-related "
                f"error/warning line(s) — check log for details")

        self.log.info(
            "vPMEM pre-run validation PASSED — "
            "%d region(s) present, namespaces provisioned, dmesg clean",
            region_count)

    def _check_vpmem_namespace_distribution(self):
        """
        Post-HTX vPMEM namespace distribution check.

        After an HTX ``mdt.mem_all`` run, verifies that:

        * Every detected region still has at least one active namespace
          (confirming the memory was distributed into multiple chunks as
          expected by the PowerVM vPMEM implementation).
        * No namespace has transitioned to a ``disabled`` or unhealthy state
          during the HTX run.
        * Logs the full per-region namespace map for post-run analysis.

        :raises: Fails the test on any distribution or health anomaly.
        """
        self.log.info("=== vPMEM post-HTX namespace distribution check ===")

        ndctl_out = process.system_output(
            'ndctl list -RNu', shell=True,
            ignore_status=True).decode('utf-8', errors='replace').strip()
        self.log.info("Post-HTX ndctl list -RNu output:\n%s", ndctl_out)

        if not ndctl_out:
            self.fail("ndctl list -RNu returned no output after HTX run")

        try:
            ndctl_data = json.loads(ndctl_out)
        except json.JSONDecodeError as exc:
            self.fail(f"Failed to parse post-HTX ndctl JSON output: {exc}")

        # Normalise to a flat list of region dicts — same three shapes as
        # in _validate_vpmem_devices: bare list, single dict, or wrapper dict.
        if isinstance(ndctl_data, list):
            regions = ndctl_data
        elif isinstance(ndctl_data, dict) and 'regions' in ndctl_data:
            regions = ndctl_data['regions']
        else:
            regions = [ndctl_data]
        total_namespaces = 0
        distribution_errors = []

        for region in regions:
            region_name = region.get('dev', 'unknown')
            region_size = region.get('size', 0)
            ns_list = region.get('namespaces', [])

            self.log.info(
                "Region: %-12s  size=%s  namespaces=%d",
                region_name, region_size, len(ns_list))

            # Each region must have at least one active namespace after the
            # HTX run — this confirms memory chunks (one per region minimum)
            # survived the workload intact.
            if not ns_list:
                distribution_errors.append(
                    f"Region {region_name} has no namespaces after "
                    f"HTX run — expected at least one chunk per region")
                continue

            for ns in ns_list:
                ns_name = ns.get('dev', 'unknown')
                ns_mode = ns.get('mode', 'unknown')
                ns_size = ns.get('size', 0)
                ns_state = ns.get('state', 'enabled')
                ns_uuid = ns.get('uuid', 'n/a')
                total_namespaces += 1

                self.log.info(
                    "  ns=%-14s  mode=%-8s  size=%-12s  "
                    "state=%-10s  uuid=%s",
                    ns_name, ns_mode, ns_size, ns_state, ns_uuid)

                if ns_state == 'disabled':
                    distribution_errors.append(
                        f"Namespace {ns_name} in region {region_name} "
                        f"is disabled after HTX run")

        self.log.info(
            "Post-HTX summary: %d region(s), %d total namespace(s)",
            len(regions), total_namespaces)

        if distribution_errors:
            for err in distribution_errors:
                self.log.error("vPMEM distribution error: %s", err)
            self.fail(
                f"vPMEM post-HTX check found {len(distribution_errors)} "
                f"distribution/health error(s) — check log for details")

        self.log.info(
            "vPMEM post-HTX namespace distribution check PASSED — "
            "%d namespace(s) across %d region(s), all active",
            total_namespaces, len(regions))

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

        When ``vpmem: True``, also runs a post-HTX namespace distribution
        check to verify that vPMEM memory remained chunked and healthy
        across the entire HTX run.
        """
        self.stop_htx()
        if self.vpmem:
            self._check_vpmem_namespace_distribution()

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
