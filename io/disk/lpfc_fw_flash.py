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
# Author: Maram Srimannarayana Murthy <msmurthy@linux.ibm.com>

"""
Broadcom (Emulex) lpfc FC HBA Firmware Flash Test.

Downloads and installs the hbacmd utility if not present, flashes new
firmware onto each specified FC HBA via hbacmd Download, verifies pending
activation status, performs DLPAR remove/add via drmgr to power-cycle the
PCIe slot, and confirms the new firmware is active by comparing pre-flash
and post-DLPAR HbaAttributes.
"""

import os
import re
import shutil
import time

from avocado import Test
from avocado.utils import distro
from avocado.utils import pci
from avocado.utils import process
from avocado.utils import wait
from avocado.utils.process import CmdError
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils.ssh import Session

HBACMD_PATH = '/opt/emulex/ocmanager/bin/hbacmd'
DLPAR_TIMEOUT = 120
PCI_WAIT_TIMEOUT = 60


class LpfcFwFlash(Test):
    """
    Broadcom lpfc FC HBA firmware flash and activation test.

    Flashes firmware via hbacmd Download, verifies staged activation
    status, performs DLPAR remove/add via drmgr to trigger a genuine
    PCIe slot power-cycle on IBM Power, and asserts the new firmware
    version is active and consistent (FW Version == Flash Firmware
    Version) in post-DLPAR HbaAttributes.
    """

    def setUp(self):
        """
        Validate architecture, read and enforce all required YAML
        parameters, install RSCT services, conditionally install
        hbacmd, and open an HMC SSH session.
        """
        if 'ppc64' not in distro.detect().arch:
            self.cancel("Supported only on ppc64 architecture")

        self.hbacmd_installed_by_test = False
        self.hmc_session = None
        self.fw_tmp_path = None
        self.hbacmd_tmp_path = None
        self.hbacmd_extract_dir = None

        self.server = self.params.get('manageSystem', default=None)
        self.hmc_user = self.params.get('hmc_username', default=None)
        self.hmc_pwd = self.params.get('hmc_pwd', default=None)
        pci_devices_raw = self.params.get('pci_devices', default=None)
        self.hbacmd_file = self.params.get('hbacmd_file', default=None)
        self.firmware_file = self.params.get('firmware_file', default=None)

        for param, value in [
            ('manageSystem', self.server),
            ('hmc_username', self.hmc_user),
            ('hmc_pwd', self.hmc_pwd),
            ('pci_devices', pci_devices_raw),
            ('hbacmd_file', self.hbacmd_file),
            ('firmware_file', self.firmware_file),
        ]:
            if not value:
                self.fail(f"Required parameter '{param}' is missing or empty")

        self.pci_list = pci_devices_raw.split()

        self._install_rsct_packages()
        self._rsct_service_start()
        self._install_hbacmd()

        hmc_ip = self._get_mcp_component("HMCIPAddr")
        if not hmc_ip:
            hmc_ip = self._get_hmc_from_mcproxy()
        if not hmc_ip:
            self.fail("Unable to determine HMC IP address")

        self.lpar_name = self._get_partition_name("Partition Name")
        if not self.lpar_name:
            self.fail("Unable to determine LPAR partition name")

        self.hmc_session = Session(hmc_ip, user=self.hmc_user,
                                   password=self.hmc_pwd)
        if not self.hmc_session.connect():
            self.fail(f"Failed to connect to HMC at {hmc_ip}")

    @staticmethod
    def _get_mcp_component(component):
        """
        Probe IBM.MCP class for the named component and return its value.
        Returns an empty string if the component is not found.
        """
        output = process.system_output(
            f'lsrsrc IBM.MCP {component}',
            ignore_status=True, shell=True, sudo=True
        ).decode('utf-8')
        for line in output.splitlines():
            if component in line:
                return line.split()[-1].strip('{}\"')
        return ''

    @staticmethod
    def _get_hmc_from_mcproxy():
        """
        Fallback HMC hostname lookup via lssrc -ls mcproxy.
        Parses lines of the form 'Hostname: <value>'.
        Returns the hostname string or empty string if not found.
        """
        output = process.system_output(
            'lssrc -ls mcproxy',
            ignore_status=True, shell=True, sudo=True
        ).decode('utf-8')
        for line in output.splitlines():
            match = re.match(r'\s*Hostname:\s*(\S+)', line)
            if match:
                return match.group(1)
        return ''

    @staticmethod
    def _get_partition_name(component):
        """
        Extract the partition name from lparstat -i output.
        Returns the value string or empty string if not found.
        """
        output = process.system_output(
            'lparstat -i',
            ignore_status=True, shell=True, sudo=True
        ).decode('utf-8')
        for line in output.splitlines():
            if component in line:
                return line.split(':')[-1].strip()
        return ''

    def _install_rsct_packages(self):
        """
        Install RSCT and supporting packages required for DLPAR
        and HMC communication. Cancels the test if any package
        cannot be installed.
        """
        smm = SoftwareManager()
        packages = ['ksh', 'src', 'rsct.basic', 'rsct.core.utils',
                    'rsct.core', 'DynamicRM', 'pciutils']
        for pkg in packages:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel(
                    f"Required package '{pkg}' could not be installed"
                )

    def _rsct_service_start(self):
        """
        Start rsct and rsct_rm service groups required for DLPAR
        operations. Cancels the test if either group fails to start
        or if any service remains inoperative.
        """
        for group in ['rsct', 'rsct_rm']:
            try:
                process.run(f'startsrc -g {group}', shell=True, sudo=True)
            except CmdError as details:
                self.cancel(f"startsrc -g {group} failed: {details}")

        output = process.system_output(
            'lssrc -a', ignore_status=True, shell=True, sudo=True
        ).decode('utf-8')
        if 'inoperative' in output:
            self.cancel("One or more RSCT services are inoperative")

    def _install_hbacmd(self):
        """
        Install the hbacmd utility from a .tgz archive if not present.
        Downloads via curl, extracts the archive, and runs install.sh.
        Sets self.hbacmd_installed_by_test = True only when this method
        performs the installation. Fails the test on any step failure.
        """
        if shutil.which('hbacmd') or os.path.exists(HBACMD_PATH):
            self.log.info("hbacmd already available, skipping installation")
            return

        basename = os.path.basename(self.hbacmd_file)
        self.hbacmd_tmp_path = f'/tmp/{basename}'

        cmd = f'curl -kL {self.hbacmd_file} -o {self.hbacmd_tmp_path}'
        if process.system(cmd, shell=True, ignore_status=True):
            self.fail(f"hbacmd download failed: {self.hbacmd_file}")

        extract_dir = '/tmp/hbacmd_extract'
        if os.path.exists(extract_dir):
            shutil.rmtree(extract_dir)
        os.makedirs(extract_dir)
        self.hbacmd_extract_dir = extract_dir

        tar_cmd = f'tar -xzf {self.hbacmd_tmp_path} -C {extract_dir}'
        if process.system(tar_cmd, shell=True, ignore_status=True):
            self.fail(
                f"Failed to extract hbacmd archive: "
                f"{self.hbacmd_tmp_path}"
            )

        install_script = os.path.join(extract_dir, 'install.sh')
        if not os.path.exists(install_script):
            found_raw = process.system_output(
                f'find {extract_dir} -name "install.sh" -maxdepth 3',
                shell=True, ignore_status=True
            ).decode('utf-8').strip()
            install_script = found_raw.splitlines()[0] if found_raw else ''

        if not install_script or not os.path.exists(install_script):
            self.fail(
                f"install.sh not found in extracted archive "
                f"under {extract_dir}"
            )

        process.run(
            f'chmod +x {install_script}', shell=True, ignore_status=True
        )
        if process.system(
            f'yes "" | sh {install_script}', shell=True, ignore_status=True
        ):
            self.fail(f"hbacmd install.sh failed: {install_script}")

        if not os.path.exists(HBACMD_PATH):
            self.fail("hbacmd binary not found after installation")

        self.hbacmd_installed_by_test = True
        self.log.info("hbacmd installed successfully via install.sh")

    def _get_wwpn_for_pci(self, pci_addr):
        """
        Resolve the first WWPN of the FC HBA at the given PCI address
        by scanning sysfs fc_host entries. Returns a colon-separated
        WWPN string (e.g. '10:00:00:10:9b:b1:8d:30'). Fails the test
        if no FC host is found for the PCI address.
        """
        fc_host_base = '/sys/class/fc_host'
        for host in sorted(os.listdir(fc_host_base)):
            host_path = os.path.join(fc_host_base, host)
            real_path = os.path.realpath(host_path)
            if pci_addr not in real_path:
                continue
            port_name_path = os.path.join(host_path, 'port_name')
            if not os.path.exists(port_name_path):
                continue
            with open(port_name_path, encoding='utf-8') as fh:
                raw = fh.read().strip().lstrip('0x')
            wwpn = ':'.join(raw[i:i + 2] for i in range(0, 16, 2))
            self.log.info("Resolved WWPN %s for PCI %s", wwpn, pci_addr)
            return wwpn
        self.fail(f"No FC host WWPN found for PCI address {pci_addr}")

    def _get_hba_attributes(self, wwpn):
        """
        Run hbacmd HbaAttributes for the given WWPN and parse the
        output into a key/value dict. Fails the test if the command
        returns a non-zero exit status or produces no parseable output.
        """
        cmd = f'{HBACMD_PATH} HbaAttributes {wwpn}'
        result = process.run(cmd, shell=True, ignore_status=True)
        if result.exit_status != 0:
            self.fail(
                f"hbacmd HbaAttributes failed for {wwpn}: "
                f"{result.stderr_text.strip()}"
            )
        attrs = {}
        for line in result.stdout_text.splitlines():
            if ' : ' in line:
                key, _, value = line.partition(' : ')
                attrs[key.strip()] = value.strip()
        if not attrs:
            self.fail(f"hbacmd HbaAttributes returned no data for {wwpn}")
        return attrs

    def _download_firmware(self):
        """
        Download the firmware image from self.firmware_file to /tmp/.
        Returns the local file path on success. Fails the test if the
        curl download returns a non-zero exit status.
        """
        basename = os.path.basename(self.firmware_file)
        local_path = f'/tmp/{basename}'
        cmd = f'curl -kL {self.firmware_file} -o {local_path}'
        if process.system(cmd, shell=True, ignore_status=True):
            self.fail(
                f"Firmware file download failed: {self.firmware_file}"
            )
        self.fw_tmp_path = local_path
        self.log.info("Firmware downloaded to %s", local_path)
        return local_path

    def _flash_firmware(self, wwpn, fw_path):
        """
        Flash firmware onto the HBA identified by wwpn using hbacmd
        Download. Captures a dmesg diff (lines appearing during the
        flash) and writes them to the Avocado log directory. Exit code
        247 is treated as success — hbacmd uses it to indicate
        'Download complete, reboot required' rather than an error.
        Fails the test only on all other non-zero exit codes.
        """
        dmesg_before = process.system_output(
            'dmesg', ignore_status=True
        ).decode('utf-8', errors='replace').splitlines()

        self.log.info("Flashing firmware %s to WWPN %s", fw_path, wwpn)
        cmd = f'{HBACMD_PATH} Download {wwpn} {fw_path}'
        result = process.run(cmd, shell=True, ignore_status=True)
        if result.exit_status not in (0, 247):
            self.fail(
                f"hbacmd Download failed for {wwpn} "
                f"(exit {result.exit_status}): "
                f"{result.stderr_text.strip()}"
            )
        self.log.info("hbacmd Download output: %s",
                      result.stdout_text.strip())

        dmesg_after = process.system_output(
            'dmesg', ignore_status=True
        ).decode('utf-8', errors='replace').splitlines()

        new_lines = [ln for ln in dmesg_after if ln not in dmesg_before]
        dmesg_log = os.path.join(self.logdir, 'lpfc_fw_flash_dmesg.log')
        with open(dmesg_log, 'a', encoding='utf-8') as fh:
            fh.write(f'\n--- dmesg during flash of {wwpn} ---\n')
            fh.write('\n'.join(new_lines) + '\n')
        self.log.info("dmesg captured to %s", dmesg_log)

    def _check_pending_activation(self, wwpn):
        """
        Verify firmware staging state after hbacmd Download. If
        'Firmware Status' reports 'Please reboot', staging is pending
        as expected. If the field is absent and FW Version already
        equals Flash Firmware Version, the card is already running the
        target firmware (e.g. activated via a sibling port on the same
        card) — log and return. Fails only when the status is absent
        and the versions are inconsistent.
        """
        attrs = self._get_hba_attributes(wwpn)
        status = attrs.get('Firmware Status', '')
        if 'Please reboot' in status:
            self.log.info(
                "Pending activation confirmed for %s: '%s'", wwpn, status
            )
            return
        fw_ver = attrs.get('FW Version', '')
        flash_ver = attrs.get('Flash Firmware Version', '')
        if fw_ver and fw_ver == flash_ver:
            self.log.info(
                "Firmware already active on %s: FW Version %s == "
                "Flash Firmware Version (activated via sibling port "
                "or same-version flash)", wwpn, fw_ver
            )
            return
        self.fail(
            f"Unexpected Firmware Status after flash on {wwpn}: "
            f"status='{status}' FW Version='{fw_ver}' "
            f"Flash Firmware Version='{flash_ver}'"
        )

    def _do_drmgr_pci(self, loc_code, operation):
        """
        Execute drmgr -c pci for the given location code and operation
        flag ('r' for remove, 'a' for add). Fails the test if drmgr
        returns a non-zero exit status.
        """
        cmd = (
            f'echo -e "\\n" | drmgr -c pci -s {loc_code} -{operation}'
        )
        if process.system(cmd, shell=True, sudo=True, ignore_status=True):
            self.fail(
                f"drmgr -c pci -{operation} failed for slot {loc_code}"
            )

    def _wait_for_pci_device(self, pci_addr, present):
        """
        Wait for a PCI device to appear or disappear from the sysfs
        PCI bus. present=True waits for the device to appear; False
        waits for it to disappear. Fails the test if the expected state
        is not reached within PCI_WAIT_TIMEOUT seconds.
        """
        sysfs_path = f'/sys/bus/pci/devices/{pci_addr}'
        state_desc = 'appear' if present else 'disappear'

        def _check():
            return os.path.exists(sysfs_path) == present

        if not wait.wait_for(_check, timeout=PCI_WAIT_TIMEOUT, step=2):
            self.fail(
                f"PCI device {pci_addr} did not {state_desc} "
                f"within {PCI_WAIT_TIMEOUT}s"
            )
        self.log.info(
            "PCI device %s confirmed %sed", pci_addr, state_desc
        )

    def _compare_hba_attributes(self, pre, post):
        """
        Compare pre-flash and post-DLPAR HbaAttributes dicts. Returns
        True when FW Version equals Flash Firmware Version (staging
        promoted to active). If both pre and post versions are already
        identical, the card was activated via a sibling port — this is
        a valid pass. Fails only when staging and active diverge.
        """
        pre_fw = pre.get('FW Version', '')
        post_fw = post.get('FW Version', '')
        post_flash_fw = post.get('Flash Firmware Version', '')

        self.log.info("Pre-flash  FW Version          : %s", pre_fw)
        self.log.info("Post-DLPAR FW Version          : %s", post_fw)
        self.log.info("Post-DLPAR Flash FW Version    : %s", post_flash_fw)

        if post_fw != post_flash_fw:
            self.log.error(
                "FW Version (%s) != Flash Firmware Version (%s) "
                "after DLPAR — staging region not promoted to active",
                post_fw, post_flash_fw
            )
            return False

        if post_fw == pre_fw:
            self.log.info(
                "FW Version already at target (%s) — firmware was "
                "activated via sibling port on the same card",
                post_fw
            )
            return True

        self.log.info(
            "Firmware activated successfully: %s -> %s "
            "(staging == active)", pre_fw, post_fw
        )
        return True

    def test_firmware_flash(self):
        """
        Orchestrate the full firmware flash and activation sequence for
        every PCI device in self.pci_list. Steps per device: WWPN
        resolution, pre-flash attribute capture, firmware download,
        flash, pending-activation check, DLPAR remove/add, and
        post-DLPAR attribute comparison.
        """
        for pci_addr in self.pci_list:
            self.log.info(
                "===== Starting firmware flash for PCI %s =====", pci_addr
            )

            wwpn = self._get_wwpn_for_pci(pci_addr)

            pre_attrs = self._get_hba_attributes(wwpn)
            self.log.info(
                "Pre-flash HbaAttributes captured for %s", wwpn
            )

            fw_path = self._download_firmware()

            self._flash_firmware(wwpn, fw_path)

            self._check_pending_activation(wwpn)

            loc_code = pci.get_slot_from_sysfs(pci_addr)
            if not loc_code:
                self.fail(
                    f"Cannot resolve PCI slot location code for {pci_addr}"
                )
            self.log.info(
                "Resolved location code %s for PCI %s", loc_code, pci_addr
            )

            self.log.info("DLPAR remove for slot %s", loc_code)
            self._do_drmgr_pci(loc_code, 'r')
            self._wait_for_pci_device(pci_addr, present=False)

            self.log.info("DLPAR add for slot %s", loc_code)
            self._do_drmgr_pci(loc_code, 'a')
            self._wait_for_pci_device(pci_addr, present=True)

            time.sleep(10)

            post_attrs = self._get_hba_attributes(wwpn)
            self.log.info(
                "Post-DLPAR HbaAttributes captured for %s", wwpn
            )

            if not self._compare_hba_attributes(pre_attrs, post_attrs):
                self.fail(
                    f"Firmware version verification failed for "
                    f"PCI {pci_addr} (WWPN {wwpn})"
                )

            self.log.info(
                "===== Firmware flash PASSED for PCI %s =====", pci_addr
            )

    def _uninstall_hbacmd(self):
        """
        Uninstall the hbacmd utility by locating uninstall.sh inside
        the extracted archive directory — mirroring the install flow.
        Checks the direct path first, then falls back to find. Runs
        uninstall.sh via chmod + sh. Logs a warning if the binary is
        still present after the uninstall attempt.
        """
        self.log.info("Uninstalling hbacmd utility installed by test")

        uninstall_script = os.path.join(
            self.hbacmd_extract_dir, 'uninstall.sh'
        )
        if not os.path.exists(uninstall_script):
            found_raw = process.system_output(
                f'find {self.hbacmd_extract_dir}'
                f' -name "uninstall.sh" -maxdepth 3',
                shell=True, ignore_status=True
            ).decode('utf-8').strip()
            uninstall_script = (
                found_raw.splitlines()[0] if found_raw else ''
            )

        if not uninstall_script or not os.path.exists(uninstall_script):
            self.log.warning(
                "uninstall.sh not found under %s; "
                "hbacmd may need manual removal",
                self.hbacmd_extract_dir
            )
            return

        process.run(
            f'chmod +x {uninstall_script}', shell=True, ignore_status=True
        )
        process.system(
            f'sh {uninstall_script}', shell=True, ignore_status=True
        )

        if os.path.exists(HBACMD_PATH):
            self.log.warning(
                "hbacmd binary still present at %s after uninstall",
                HBACMD_PATH
            )
        else:
            self.log.info(
                "hbacmd uninstalled successfully via %s", uninstall_script
            )

    def tearDown(self):
        """
        Uninstall hbacmd if installed by this test run, remove all
        temporary files created during the test, and close the HMC
        SSH session. Pre-existing hbacmd installations are not touched.
        """
        if self.hbacmd_installed_by_test:
            self._uninstall_hbacmd()
        else:
            self.log.info("hbacmd was pre-existing, skipping uninstall")

        for tmp_path in [self.hbacmd_tmp_path, self.fw_tmp_path]:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
                self.log.info("Removed temporary file %s", tmp_path)

        if self.hbacmd_extract_dir and os.path.isdir(
            self.hbacmd_extract_dir
        ):
            shutil.rmtree(self.hbacmd_extract_dir, ignore_errors=True)
            self.log.info(
                "Removed extract directory %s", self.hbacmd_extract_dir
            )

        if self.hmc_session:
            self.hmc_session.quit()
            self.log.info("HMC SSH session closed")
