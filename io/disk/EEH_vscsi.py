#!/usr/bin/env python
# pylint: disable=too-many-lines,invalid-name

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
VIOS-Level EEH Error Injection and Recovery Test for vSCSI (ibmvscsi)
adapters on IBM PowerVM LPAR.

Connects to the VIOS, correlates the target virtual SCSI disk with its
backing hdisk, captures the pre-injection state of the VIOS physical
adapter and hdisk, triggers EEH error injection via eeh_tool Op 3, waits
for VIOS recovery, then asserts the post-recovery states match the
pre-injection states. eeh_tool must be run as root via oem_setup_env.
errinjct is NOT supported on VIOS.
"""

import os
import re
import struct
import time

from avocado import Test
from avocado.utils import distro
from avocado.utils import genio
from avocado.utils import process
from avocado.utils import wait
from avocado.utils.ssh import Session

INJECT_CONFIRM_SECS = 60

EEH_TOOL_PATH = '/home/padmin/eeh_tool'

EEH_FUNC_MEM_LOAD_DATA = 1
EEH_FUNC_IO_LOAD_DATA = 3
EEH_FUNC_ODM_DEFAULT = 1

EEH_FUNC_NVME_INJECT = 6
EEH_MASK_NVME = "0xfffff000"
EEH_OP_ENABLE = 4
EEH_OP_ENABLE_FUNC = 1


class EEHVscsi(Test):  # pylint: disable=too-many-instance-attributes
    """
    VIOS-Level EEH Error Injection and Recovery test for vSCSI devices.
    """

    def setUp(self):  # pylint: disable=invalid-name
        """
        Validate environment, load YAML inputs, connect to the VIOS,
        map the client virtual disk to the underlying physical VIOS hdisk,
        and capture the pre-injection device state for post-recovery
        comparison.
        """
        self.log.info("========= Starting vSCSI EEH Test Setup =========")

        if 'ppc' not in distro.detect().arch:
            self.cancel(
                "This test requires a ppc64/ppc64le architecture"
            )

        if 'PowerNV' in genio.read_file("/proc/cpuinfo").strip():
            self.cancel(
                "This test targets PowerVM LPAR, not bare-metal PowerNV"
            )

        self.disk_input = self.params.get('disk', default=None)
        self.vios_ip = self.params.get('vios_ip', default=None)
        self.vios_username = self.params.get(
            'vios_username', default='padmin'
        )
        self.vios_pwd = self.params.get('vios_pwd', default=None)
        self.eeh_tool_url = self.params.get('eeh_tool_url', default=None)

        if not self.disk_input:
            self.fail(
                "disk parameter is required in the YAML configuration"
            )
        if not self.vios_ip:
            self.fail(
                "vios_ip parameter is required in the YAML configuration"
            )
        if not self.vios_pwd:
            self.fail(
                "vios_pwd parameter is required in the YAML configuration"
            )

        self.vios_session = Session(
            self.vios_ip,
            user=self.vios_username,
            password=self.vios_pwd,
        )
        self.vios_session.cleanup_master()
        self.log.info("Connecting to VIOS at %s...", self.vios_ip)
        if not wait.wait_for(self.vios_session.connect, timeout=30):
            self.fail(
                f"Failed to establish SSH connection to VIOS at {self.vios_ip}"
            )
        self.log.info("Connected to VIOS successfully")

        if not os.path.exists(self.disk_input):
            self.cancel(
                f"Target disk input {self.disk_input} does not exist "
                f"on client LPAR"
            )
        self.disk_name = os.path.basename(
            os.path.realpath(self.disk_input)
        )
        self.log.info("Resolved client disk name: %s", self.disk_name)

        self.inquiry_id = self._get_client_inquiry_id()
        if not self.inquiry_id:
            self.fail(
                f"Failed to resolve SCSI Inquiry identifier for "
                f"device {self.disk_name}"
            )
        self.log.info(
            "Resolved client SCSI Inquiry ID: %s", self.inquiry_id
        )

        self._discover_vios_devices()

        self._fetch_eeh_tool_on_vios()

        self.pre_eeh_states = self._get_vios_device_states()
        self.log.info(
            "Pre-EEH VIOS device states captured: %s",
            self.pre_eeh_states
        )

        self.log.info(
            "========= vSCSI EEH Test Setup Complete ========="
        )

    def test_eeh_vscsi(self):
        """
        Validate EEH error injection and recovery on the VIOS.

        1. Log pre-EEH state (captured in setUp).
        2. Inject EEH on the physical adapter and wait for recovery.
        3. Capture post-recovery device states.
        4. Warn on unexpected non-EEH VIOS error log entries.
        5. Compare pre- and post-EEH states; fail on any mismatch.
        """
        self.log.info(
            "--- Step 1: Pre-EEH device states ---\n%s",
            self._format_states(self.pre_eeh_states)
        )

        self.log.info("--- Step 2: EEH Error Injection on VIOS ---")
        self._inject_eeh_on_vios()
        self.log.info(
            "EEH injection complete — waiting for VIOS devices "
            "to recover..."
        )

        self.log.info("--- Step 3: Post-EEH device states ---")
        post_eeh_states = self._wait_and_get_post_eeh_states()
        self.log.info(
            "Post-EEH device states:\n%s",
            self._format_states(post_eeh_states)
        )

        self.log.info(
            "--- Step 4: Checking VIOS error log for unexpected entries ---"
        )
        self._check_vios_logs_for_unexpected()

        self.log.info(
            "--- Step 5: Comparing pre-EEH and post-EEH device states ---"
        )
        mismatches = []
        for dev, pre_state in self.pre_eeh_states.items():
            post_state = post_eeh_states.get(dev, "<not found>")
            if pre_state != post_state:
                mismatches.append(
                    f"  {dev}: pre='{pre_state}' post='{post_state}'"
                )
            else:
                self.log.info(
                    "Device %-20s state matches pre/post EEH: '%s'",
                    dev, pre_state
                )

        if mismatches:
            self.fail(
                "Post-EEH device state mismatch on VIOS — "
                "recovery did not restore original state:\n"
                + "\n".join(mismatches)
            )

        self.log.info(
            "All VIOS device states match pre-EEH baseline — "
            "EEH recovery validated successfully"
        )

    def _get_client_inquiry_id(self):  # pylint: disable=too-many-nested-blocks
        """
        Retrieve the unique SCSI Inquiry identifier for the client disk
        via sysfs inquiry file, with lsscsi as a fallback.
        """
        inquiry_paths = [
            f"/sys/block/{self.disk_name}/device/inquiry",
            f"/sys/class/block/{self.disk_name}/device/inquiry"
        ]
        for path in inquiry_paths:
            if os.path.exists(path):
                try:
                    with open(path, "rb") as fh:
                        raw_data = fh.read()
                    data = raw_data.decode(
                        "utf-8", errors="ignore"
                    ).strip()
                    clean_id = re.sub(r'[\x00-\x1f\x7f-\xff]', '', data)
                    parts = clean_id.split()
                    if len(parts) >= 3:
                        return parts[-1]
                    if len(clean_id) > 8:
                        return clean_id[-8:]
                    return clean_id
                except (OSError, UnicodeDecodeError):
                    continue

        res = process.run("lsscsi -vl", ignore_status=True, shell=True)
        if res.exit_status == 0:
            output = res.stdout.decode("utf-8")
            match = re.search(
                rf"\[\d+:\d+:\d+:\d+\].*{self.disk_name}", output
            )
            if match:
                for line in output.splitlines():
                    if "dir" in line and self.disk_name in line:
                        dir_path = line.split()[-1].strip("[]")
                        inquiry_file = os.path.join(
                            dir_path, "inquiry"
                        )
                        if os.path.exists(inquiry_file):
                            try:
                                return genio.read_file(
                                    inquiry_file
                                ).split()[2].strip(
                                    b'0001'
                                ).decode("utf-8")
                            except (OSError, IndexError,
                                    UnicodeDecodeError):
                                pass
        return None

    @staticmethod
    def _client_id_matches(client_id, lpar_id_hex):
        """
        Return True when client_id and lpar_id_hex represent the same
        integer partition ID, False otherwise (including on ValueError).
        """
        try:
            return int(client_id, 16) == int(lpar_id_hex, 16)
        except ValueError:
            return False

    def _get_vios_vhost_mappings(self):
        """
        Read LPAR partition ID from device tree and parse 'ioscli lsmap -all'
        output on VIOS to discover vhost adapters and their backing devices.

        :return: tuple of (lpar_id_hex, vhosts_data dict)
        """
        lpar_id_hex = None
        part_no_path = "/proc/device-tree/ibm,partition-no"
        if os.path.exists(part_no_path):
            try:
                with open(part_no_path, "rb") as fh:
                    part_no_bytes = fh.read()
                partition_id = struct.unpack(">I", part_no_bytes)[0]
                lpar_id_hex = f"0x{partition_id:08x}"
                self.log.info(
                    "Resolved LPAR Partition ID: %d (%s)",
                    partition_id, lpar_id_hex
                )
            except OSError as exc:
                self.log.debug(
                    "Failed to read partition-no from device-tree: %s",
                    exc
                )

        self.log.info("Querying lsmap -all on VIOS to parse mappings...")
        res = self.vios_session.cmd("ioscli lsmap -all")
        if res.exit_status != 0:
            self.fail(
                f"Failed to execute 'ioscli lsmap -all' on VIOS: "
                f"{res.stderr_text}"
            )

        vhosts_data = {}
        current_vhost = None

        for line in res.stdout_text.splitlines():
            line_str = line.strip()
            if not line_str:
                continue

            if line_str.startswith("vhost") or (
                line_str.split() and
                line_str.split()[0].startswith("vhost")
            ):
                parts = line_str.split()
                current_vhost = parts[0]
                current_client_id = (
                    parts[-1] if len(parts) >= 3 else None
                )
                vhosts_data[current_vhost] = {
                    "client_id": current_client_id,
                    "devices": []
                }
                continue

            if "VTD" in line_str:
                vtd_name = line_str.split()[-1]
                vhosts_data[current_vhost]["devices"].append(
                    {"vtd": vtd_name, "hdisk": None}
                )
            elif (
                "Backing device" in line_str and
                current_vhost and
                vhosts_data[current_vhost]["devices"]
            ):
                backing_dev = line_str.split()[-1]
                vhosts_data[current_vhost]["devices"][-1][
                    "hdisk"
                ] = backing_dev

        self.log.debug("Parsed VIOS vhost mappings: %s", vhosts_data)
        return lpar_id_hex, vhosts_data

    def _match_vios_backing_device(self, vhosts_data, lpar_id_hex):
        """
        Match candidate backing device on VIOS against client inquiry ID,
        falling back to partition-ID-only match if inquiry matching fails.

        :param vhosts_data: dict of parsed vhost mappings
        :param lpar_id_hex: hexadecimal string representing LPAR partition ID
        :return: tuple of (matched_vhost, matched_hdisk, matched_vtd)
        """
        inq_core = self.inquiry_id.split('.')[0]
        inq_core_clean = re.sub(r'[^a-zA-Z0-9]', '', inq_core).lower()
        self.log.info(
            "Resilient core Inquiry ID for matching: %s",
            inq_core_clean
        )

        for vhost, data in vhosts_data.items():
            client_id = data["client_id"]
            if lpar_id_hex and client_id:
                if not self._client_id_matches(client_id, lpar_id_hex):
                    self.log.debug(
                        "Skipping vhost %s (client_id %s != "
                        "LPAR %s)", vhost, client_id, lpar_id_hex
                    )
                    continue

            for dev_info in data["devices"]:
                hdisk = dev_info["hdisk"]
                if not hdisk:
                    continue

                self.log.info(
                    "Checking candidate backing device %s on "
                    "vhost %s...", hdisk, vhost
                )
                attr_cmd = f"ioscli lsdev -dev {hdisk} -attr"
                attr_res = self.vios_session.cmd(attr_cmd)
                attr_text_clean = re.sub(
                    r'[^a-zA-Z0-9]', '', attr_res.stdout_text
                ).lower()

                if inq_core_clean in attr_text_clean:
                    self.log.info(
                        "Found exact backing hdisk match! "
                        "dev: %s, vhost: %s, VTD: %s",
                        hdisk, vhost, dev_info["vtd"]
                    )
                    return vhost, hdisk, dev_info["vtd"]

                lsattr_cmd = f"/usr/sbin/lsattr -El {hdisk}"
                lsattr_res = self.vios_session.cmd(lsattr_cmd)
                lsattr_clean = re.sub(
                    r'[^a-zA-Z0-9]', '', lsattr_res.stdout_text
                ).lower()
                if inq_core_clean in lsattr_clean:
                    self.log.info(
                        "Found exact backing hdisk match via lsattr! "
                        "dev: %s, vhost: %s, VTD: %s",
                        hdisk, vhost, dev_info["vtd"]
                    )
                    return vhost, hdisk, dev_info["vtd"]

        if lpar_id_hex:
            self.log.warning(
                "Inquiry ID matching failed. Searching fallback via "
                "partition ID %s...", lpar_id_hex
            )
            for vhost, data in vhosts_data.items():
                client_id = data["client_id"]
                if client_id and self._client_id_matches(
                    client_id, lpar_id_hex
                ):
                    if data["devices"]:
                        hdisk = data["devices"][0]["hdisk"]
                        vtd = data["devices"][0]["vtd"]
                        self.log.warning(
                            "Fallback matched first device "
                            "%s (VTD: %s) on vhost %s",
                            hdisk, vtd, vhost
                        )
                        return vhost, hdisk, vtd

        return None, None, None

    def _discover_vios_devices(self):
        """
        Auto-discover vhost adapter and backing hdisk on the VIOS using
        LPAR partition ID and disk Inquiry ID.
        """
        lpar_id_hex, vhosts_data = self._get_vios_vhost_mappings()
        vhost, hdisk, vtd = self._match_vios_backing_device(
            vhosts_data, lpar_id_hex
        )

        if not hdisk:
            self.fail(
                f"Failed to find physical backing hdisk on VIOS "
                f"matching disk {self.disk_name} and Inquiry ID "
                f"{self.inquiry_id}"
            )

        self.vhost = vhost
        self.vios_hdisk = hdisk
        self.vtd = vtd

    def _get_physical_devs(self):
        """
        Return (parent_dev, physical_hdisk) for the current vSCSI path.
        Shared by state-query, polling, and log-check methods to avoid
        redundant resolution calls.
        """
        return (
            self._resolve_parent_adapter(),
            self._resolve_physical_hdisk(self.vios_hdisk),
        )

    def _get_vios_device_states(self):
        """
        Query and return the current state of all three VIOS devices
        in the vSCSI path: physical adapter, physical hdisk, and VTD.

        Uses ``ioscli lsdev`` for physical devices and
        ``ioscli lsmap -vadapter`` for the VTD status.
        Returns {device_key: status_string}; status is 'Available'
        or '<unavailable>'/'<unknown>' on failure.
        """
        parent_dev, physical_hdisk = self._get_physical_devs()
        states = {}

        for dev in (parent_dev, physical_hdisk):
            res = self.vios_session.cmd(f"ioscli lsdev -dev {dev}")
            if res.exit_status != 0:
                self.log.warning(
                    "Could not retrieve lsdev status for %s", dev
                )
                states[dev] = "<unavailable>"
                continue
            match = re.search(
                r'^\S+\s+(\w+)', res.stdout_text, re.MULTILINE
            )
            states[dev] = match.group(1) if match else "<unknown>"
            self.log.info(
                "Physical device %-10s status: %s", dev, states[dev]
            )

        vtd_state = self._get_vtd_status()
        states[self.vtd] = vtd_state
        self.log.info(
            "Virtual device  %-10s status: %s", self.vtd, vtd_state
        )

        return states

    def _get_vtd_status(self):
        """
        Read the Status field for self.vtd from
        ``ioscli lsmap -vadapter self.vhost``.
        Returns the status word (e.g. 'Available') or '<unavailable>'
        if the command fails or the VTD is not found in the output.
        """
        res = self.vios_session.cmd(
            f"ioscli lsmap -vadapter {self.vhost}"
        )
        if res.exit_status != 0:
            self.log.warning(
                "Could not query lsmap for vhost %s", self.vhost
            )
            return "<unavailable>"

        lines = res.stdout_text.splitlines()
        for idx, line in enumerate(lines):
            if re.search(r'\bVTD\b', line) and self.vtd in line:
                for next_line in lines[idx + 1:]:
                    status_match = re.match(
                        r'\s*Status\s+(\S+)', next_line
                    )
                    if status_match:
                        return status_match.group(1)
                break

        self.log.warning(
            "VTD %s not found in lsmap output for %s",
            self.vtd, self.vhost
        )
        return "<unavailable>"

    def _fetch_eeh_tool_on_vios(self):
        """
        Download eeh_tool to EEH_TOOL_PATH on the VIOS when
        eeh_tool_url is provided in the YAML configuration.
        Skips if binary already exists. Tries curl first, then wget.
        Applies chmod 755 after download. Fails if both downloaders
        fail or if chmod fails.
        """
        if not self.eeh_tool_url:
            self.log.info(
                "eeh_tool_url not set — assuming eeh_tool is "
                "already present at %s on VIOS", EEH_TOOL_PATH
            )
            return

        self.log.info(
            "eeh_tool_url provided — checking if %s already exists "
            "on VIOS...", EEH_TOOL_PATH
        )
        check_res = self.vios_session.cmd(
            f"test -x {EEH_TOOL_PATH} && echo EXISTS || echo ABSENT"
        )
        if "EXISTS" in check_res.stdout_text:
            self.log.info(
                "eeh_tool already present and executable at %s — "
                "skipping download", EEH_TOOL_PATH
            )
            return

        self.log.info(
            "Downloading eeh_tool from %s to %s on VIOS...",
            self.eeh_tool_url, EEH_TOOL_PATH
        )

        curl_cmd = f"curl -fsSL -o {EEH_TOOL_PATH} '{self.eeh_tool_url}'"
        dl_res = self.vios_session.cmd(curl_cmd)

        if dl_res.exit_status != 0:
            self.log.warning(
                "curl download failed (exit %d) — trying wget...",
                dl_res.exit_status
            )
            wget_cmd = (
                f"wget -q -O {EEH_TOOL_PATH} '{self.eeh_tool_url}'"
            )
            dl_res = self.vios_session.cmd(wget_cmd)

        if dl_res.exit_status != 0:
            self.fail(
                f"Failed to download eeh_tool from {self.eeh_tool_url} "
                f"to {EEH_TOOL_PATH} on VIOS {self.vios_ip} — both "
                f"curl and wget failed (exit {dl_res.exit_status}).\n"
                f"Output: {dl_res.stdout_text.strip()}"
            )

        chmod_res = self.vios_session.cmd(
            f"chmod 755 {EEH_TOOL_PATH}"
        )
        if chmod_res.exit_status != 0:
            self.fail(
                f"Downloaded eeh_tool to {EEH_TOOL_PATH} but chmod 755 "
                f"failed on VIOS {self.vios_ip}.\n"
                f"Output: {chmod_res.stdout_text.strip()}"
            )

        self.log.info(
            "eeh_tool downloaded and made executable at %s on "
            "VIOS %s", EEH_TOOL_PATH, self.vios_ip
        )

    def _run_as_root(self, cmd):
        """
        Execute a command as root on the VIOS via oem_setup_env.
        oem_setup_env reads one command from stdin and executes it as
        root. Double quotes within cmd are backslash-escaped so they
        survive embedding in the outer echo argument.
        """
        escaped_cmd = cmd.replace('"', '\\"')
        pipe_cmd = f'echo "{escaped_cmd}" | oem_setup_env'
        return self.vios_session.cmd(pipe_cmd)

    _PCI_ADAPTER_PREFIXES = (
        'nvme', 'scsi', 'fscsi', 'vscsi', 'pci', 'sissas', 'sisfc',
    )

    def _resolve_physical_hdisk(self, dev):
        """
        Resolve the underlying physical hdisk for a VIOS device.
        When the backing device is a Logical Volume (LV), uses
        'lslv -l <lv>' to find the first physical volume (hdisk).
        Returns dev unchanged if it is already a raw hdisk or non-LV
        device. Calls self.fail() if lslv cannot resolve a PV.
        """
        type_res = self._run_as_root(f"lsdev -Cl {dev}")
        if type_res.exit_status != 0:
            return dev

        if 'Logical volume' not in type_res.stdout_text:
            return dev

        self.log.info(
            "%s is a Logical Volume — resolving underlying hdisk "
            "via lslv -l...", dev
        )
        lslv_res = self._run_as_root(f"lslv -l {dev}")
        if lslv_res.exit_status != 0 or not lslv_res.stdout_text.strip():
            self.fail(
                f"Cannot resolve physical hdisk for LV {dev} on VIOS "
                f"{self.vios_ip} — lslv -l returned: "
                f"{lslv_res.stderr_text.strip()}"
            )

        for line in lslv_res.stdout_text.strip().splitlines():
            parts = line.split()
            if parts and parts[0].startswith('hdisk'):
                self.log.info(
                    "Resolved LV %s -> physical hdisk %s",
                    dev, parts[0]
                )
                return parts[0]

        self.fail(
            f"lslv -l {dev} returned no hdisk PV line on VIOS "
            f"{self.vios_ip}.\nOutput: "
            f"{lslv_res.stdout_text.strip()}"
        )
        return None

    def _resolve_parent_adapter(self):
        """
        Resolve the physical PCI adapter device name for self.vios_hdisk.
        First resolves any LV to its underlying physical hdisk, then
        walks the lsdev -Cl parent chain up to 8 levels until a PCI
        adapter prefix (nvme*, scsi*, fscsi*, etc.) is found.
        Calls self.fail() if the adapter cannot be resolved.
        """
        physical_dev = self._resolve_physical_hdisk(self.vios_hdisk)
        current = physical_dev
        max_depth = 8

        for depth in range(max_depth):
            parent_res = self._run_as_root(
                f"lsdev -Cl {current} -F parent"
            )
            if parent_res.exit_status != 0 or \
                    not parent_res.stdout_text.strip():
                self.fail(
                    f"Could not resolve parent adapter for device "
                    f"{current} (walked from {physical_dev}, depth "
                    f"{depth}) on VIOS — lsdev -Cl returned: "
                    f"{parent_res.stderr_text.strip()}"
                )

            parent_dev = parent_res.stdout_text.strip().splitlines()[0]
            self.log.info(
                "Device tree walk depth %d: %s -> %s",
                depth, current, parent_dev
            )

            if parent_dev.startswith(self._PCI_ADAPTER_PREFIXES):
                self.log.info(
                    "Resolved PCI adapter for %s: %s (depth %d)",
                    self.vios_hdisk, parent_dev, depth
                )
                return parent_dev

            current = parent_dev

        self.fail(
            f"Could not resolve a PCI adapter for backing device "
            f"{self.vios_hdisk} on VIOS after walking {max_depth} "
            f"levels up the device tree. Last device reached: {current}"
        )
        return None

    def _is_nvme_adapter(self, parent_dev):
        """
        Return True if parent_dev is an NVMe adapter on the VIOS.
        NVMe-backed vSCSI disks require Op 4 enable before Op 3 inject,
        function 6, and the bus address from kdb rather than Op 5.
        """
        return bool(re.match(r'^nvme\d+$', parent_dev))

    def _get_nvme_bus_address(self, nvme_dev):
        """
        Retrieve the PCI bus address for an NVMe adapter via AIX kdb.
        Required as the -a argument for eeh_tool Op 3 on NVMe adapters.
        eeh_tool Op 5 does not return usable addresses for NVMe adapters.
        Returns the bus address as a hex string or None if parsing fails.
        Calls self.fail() only if kdb exits with a fatal error.
        """
        self.log.info(
            "Querying NVMe PCI bus address for %s via kdb...", nvme_dev
        )
        kdb_cmd = (
            f'echo "nvme {nvme_dev}" | kdb -script | grep busaddr'
        )
        kdb_res = self._run_as_root(kdb_cmd)

        if kdb_res.exit_status not in (0, 1):
            self.fail(
                f"kdb failed to query bus address for NVMe adapter "
                f"{nvme_dev} on VIOS {self.vios_ip} "
                f"(exit {kdb_res.exit_status}). Ensure kdb is available "
                f"in the root PATH under oem_setup_env.\n"
                f"Output: {kdb_res.stdout_text.strip()}"
            )

        output = kdb_res.stdout_text
        self.log.info(
            "kdb busaddr output for %s:\n%s", nvme_dev, output
        )

        match = re.search(r'busaddr:\s*(0x[0-9a-fA-F]+)', output)
        if not match:
            self.log.warning(
                "Could not parse 'busaddr' from kdb output for %s. "
                "EEH injection with -a flag will not be performed; "
                "eeh_tool will attempt ODM default address.",
                nvme_dev
            )
            return None

        bus_addr = match.group(1)
        self.log.info(
            "NVMe PCI bus address for %s: %s", nvme_dev, bus_addr
        )
        return bus_addr

    def _check_eeh_enabled(self, parent_dev):
        """
        Verify EEH error injection is enabled for parent_dev using
        eeh_tool Op 1 (Query Slot Capabilities). Fails if EEH is not
        enabled (slot_capabilities=0) or if the tool cannot be executed
        (exit 255 indicates machine DD open failure).
        """
        self.log.info(
            "Checking eeh_tool availability at %s on VIOS...",
            EEH_TOOL_PATH
        )
        avail_res = self._run_as_root(
            f"test -x {EEH_TOOL_PATH} && echo AVAILABLE || echo MISSING"
        )
        if "MISSING" in avail_res.stdout_text or \
                "AVAILABLE" not in avail_res.stdout_text:
            self.fail(
                f"eeh_tool binary not found or not executable at "
                f"{EEH_TOOL_PATH} on VIOS {self.vios_ip}. Place "
                f"eeh_tool at that path with execute permission."
            )

        self.log.info(
            "Querying EEH slot capabilities for adapter %s "
            "via eeh_tool Op 1...", parent_dev
        )
        query_res = self._run_as_root(f"{EEH_TOOL_PATH} {parent_dev} 1")

        if query_res.exit_status == 255:
            self.fail(
                f"eeh_tool could not open the AIX machine device driver "
                f"on VIOS {self.vios_ip} (errno=13 / EACCES). The binary "
                f"must be run as root. Ensure oem_setup_env provides root "
                f"context or set the SUID bit: chmod 4750 {EEH_TOOL_PATH}"
            )

        output = query_res.stdout_text
        self.log.info(
            "eeh_tool Op 1 output for %s:\n%s", parent_dev, output
        )

        cap_match = re.search(
            r'[Ss]lot[\s_][Cc]apabilities\s*[=:]\s*(\d+)', output
        )
        if cap_match:
            slot_cap = int(cap_match.group(1))
            if slot_cap == 0:
                self.fail(
                    f"ERROR injection is not enabled: eeh_tool reports "
                    f"slot_capabilities=0 for adapter {parent_dev} on "
                    f"VIOS {self.vios_ip}. EEH must be enabled on this "
                    f"slot before this test can run."
                )
            self.log.info(
                "EEH enabled confirmed: slot_capabilities=%d for "
                "adapter %s", slot_cap, parent_dev
            )
        else:
            self.log.warning(
                "Could not parse 'slot_capabilities' from eeh_tool "
                "Op 1 output for %s. Proceeding with injection; "
                "verify eeh_tool output manually if injection fails.",
                parent_dev
            )

    def _get_eeh_bus_addresses(self, parent_dev):
        """
        Retrieve PCI bus addresses for parent_dev via eeh_tool Op 5.
        Not applicable for NVMe adapters; use _get_nvme_bus_address()
        instead. Returns (bus_mem_addr, bus_io_addr) as hex strings or
        (None, None) if Op 5 cannot return usable addresses.
        """
        self.log.info(
            "Querying PCI bus addresses for %s via eeh_tool Op 5...",
            parent_dev
        )
        info_res = self._run_as_root(f"{EEH_TOOL_PATH} {parent_dev} 5")

        if info_res.exit_status == 255:
            self.log.warning(
                "eeh_tool Op 5 returned exit 255 for %s — "
                "machine DD open failed; will use ODM defaults for "
                "address/mask in Op 3.", parent_dev
            )
            return None, None

        output = info_res.stdout_text
        self.log.info(
            "eeh_tool Op 5 output for %s:\n%s", parent_dev, output
        )

        mem_match = re.search(
            r'Bus\s+mem\s+addr\s*:\s*(0x[0-9a-fA-F]+)', output
        )
        io_match = re.search(
            r'Bus\s+IO\s+addr\s*:\s*(0x[0-9a-fA-F]+)', output
        )

        bus_mem_addr = mem_match.group(1) if mem_match else None
        bus_io_addr = io_match.group(1) if io_match else None

        self.log.info(
            "Parsed bus addresses — mem: %s  io: %s",
            bus_mem_addr if bus_mem_addr else "<not found>",
            bus_io_addr if bus_io_addr else "<not found>"
        )
        return bus_mem_addr, bus_io_addr

    def _build_eeh_inject_cmd_scsi(self, parent_dev, bus_mem_addr,
                                   bus_io_addr):
        """
        Construct the eeh_tool Op 3 command for EEH error injection on
        SCSI/FC parent adapters (non-NVMe path).
        Uses EEH_FUNC_MEM_LOAD_DATA(1) with mem addr when available,
        EEH_FUNC_IO_LOAD_DATA(3) with I/O addr as fallback, or
        EEH_FUNC_ODM_DEFAULT(1) without -a/-m when no address exists.
        Returns the complete command string.
        """
        mask = "0xfffff000"

        mem_val = int(bus_mem_addr, 16) if bus_mem_addr else 0
        io_val = int(bus_io_addr, 16) if bus_io_addr else 0

        if mem_val != 0:
            cmd = (
                f"{EEH_TOOL_PATH} {parent_dev} 3 "
                f"{EEH_FUNC_MEM_LOAD_DATA} -a {bus_mem_addr} -m {mask}"
            )
            self.log.info(
                "EEH inject command (mem addr, func %d — recoverable "
                "Load Memory Data parity / TLP ECRC): %s",
                EEH_FUNC_MEM_LOAD_DATA, cmd
            )
        elif io_val != 0:
            cmd = (
                f"{EEH_TOOL_PATH} {parent_dev} 3 "
                f"{EEH_FUNC_IO_LOAD_DATA} -a {bus_io_addr} -m {mask}"
            )
            self.log.info(
                "EEH inject command (I/O addr, func %d — recoverable "
                "Load I/O Data parity / TLP ECRC): %s",
                EEH_FUNC_IO_LOAD_DATA, cmd
            )
        else:
            cmd = (
                f"{EEH_TOOL_PATH} {parent_dev} 3 {EEH_FUNC_ODM_DEFAULT}"
            )
            self.log.info(
                "EEH inject command (ODM default addr, func %d — "
                "recoverable Load Memory Data parity): %s",
                EEH_FUNC_ODM_DEFAULT, cmd
            )

        return cmd

    def _build_eeh_inject_cmd_nvme(self, nvme_dev, bus_addr):
        """
        Construct eeh_tool Op 4 (enable) and Op 3 (inject) commands for
        EEH error injection on an NVMe adapter.
        Op 4 func 1 enables EEH; Op 3 func 6 injects with constant mask
        0xfffff000 and bus address from kdb. If bus_addr is None the
        inject command omits -a/-m and relies on ODM defaults.
        Returns (enable_cmd, inject_cmd) as a tuple of strings.
        """
        enable_cmd = (
            f"{EEH_TOOL_PATH} {nvme_dev} "
            f"{EEH_OP_ENABLE} {EEH_OP_ENABLE_FUNC}"
        )
        self.log.info(
            "NVMe EEH enable command (Op %d func %d): %s",
            EEH_OP_ENABLE, EEH_OP_ENABLE_FUNC, enable_cmd
        )

        if bus_addr:
            inject_cmd = (
                f"{EEH_TOOL_PATH} {nvme_dev} 3 {EEH_FUNC_NVME_INJECT} "
                f"-a {bus_addr} -m {EEH_MASK_NVME}"
            )
            self.log.info(
                "NVMe EEH inject command (func %d, busaddr %s, "
                "mask %s): %s",
                EEH_FUNC_NVME_INJECT, bus_addr, EEH_MASK_NVME,
                inject_cmd
            )
        else:
            inject_cmd = (
                f"{EEH_TOOL_PATH} {nvme_dev} 3 {EEH_FUNC_NVME_INJECT}"
            )
            self.log.warning(
                "NVMe bus address not available — injecting without "
                "-a/-m (ODM default path, func %d). Injection may not "
                "produce a reliable EEH freeze: %s",
                EEH_FUNC_NVME_INJECT, inject_cmd
            )

        return enable_cmd, inject_cmd

    def _inject_eeh_on_vios(self):
        """
        Orchestrate physical EEH error injection on the VIOS backing
        adapter using eeh_tool.
        SCSI/FC path: Op 1 check -> Op 5 bus addresses -> Op 3 inject.
        NVMe path: Op 1 check -> Op 4 enable -> kdb bus addr -> Op 3.
        Fails immediately if any step cannot proceed.
        """
        parent_dev = self._resolve_parent_adapter()

        self._check_eeh_enabled(parent_dev)

        if self._is_nvme_adapter(parent_dev):
            self.log.info(
                "NVMe backing adapter detected (%s) — using NVMe "
                "eeh_tool injection path", parent_dev
            )
            bus_addr = self._get_nvme_bus_address(parent_dev)

            enable_cmd, inject_cmd = self._build_eeh_inject_cmd_nvme(
                parent_dev, bus_addr
            )

            self.log.info(
                "Enabling EEH on NVMe slot %s via eeh_tool Op %d...",
                parent_dev, EEH_OP_ENABLE
            )
            enable_res = self._run_as_root(enable_cmd)
            if enable_res.exit_status != 0:
                self.fail(
                    f"eeh_tool Op {EEH_OP_ENABLE} (enable EEH) failed "
                    f"(exit {enable_res.exit_status}) for NVMe adapter "
                    f"{parent_dev} on VIOS {self.vios_ip}.\n"
                    f"Command: {enable_cmd}\n"
                    f"Output: {enable_res.stdout_text.strip()}"
                )
            self.log.info(
                "EEH enabled on NVMe slot %s", parent_dev
            )
        else:
            self.log.info(
                "SCSI/FC backing adapter detected (%s) — using "
                "standard eeh_tool injection path", parent_dev
            )
            bus_mem_addr, bus_io_addr = self._get_eeh_bus_addresses(
                parent_dev
            )
            inject_cmd = self._build_eeh_inject_cmd_scsi(
                parent_dev, bus_mem_addr, bus_io_addr
            )

        self.log.info(
            "Injecting EEH error on VIOS adapter %s via eeh_tool Op 3",
            parent_dev
        )
        inject_res = self._run_as_root(inject_cmd)

        if inject_res.exit_status != 0:
            self.fail(
                f"eeh_tool EEH injection failed "
                f"(exit {inject_res.exit_status}) for adapter "
                f"{parent_dev} on VIOS {self.vios_ip}.\n"
                f"Command: {inject_cmd}\n"
                f"Output: {inject_res.stdout_text.strip()}"
            )

        self.log.info(
            "EEH error injection via eeh_tool completed successfully "
            "for adapter %s", parent_dev
        )

    def _format_states(self, states):
        """
        Return a human-readable multi-line string of device states for
        logging. Each line is '  <device>  :  <state>'.
        """
        return "\n".join(
            f"  {dev:<20} : {state}"
            for dev, state in states.items()
        )

    def _read_vios_errlog(self):
        """
        Run errpt -a on the VIOS, falling back to ioscli errlog.
        Returns (log_text, log_source) where log_source identifies
        which command produced the output.
        """
        err_res = self.vios_session.cmd("errpt -a")
        if err_res.exit_status == 0:
            return err_res.stdout_text, "errpt -a"
        self.log.info(
            "errpt -a unavailable — falling back to ioscli errlog"
        )
        err_res = self.vios_session.cmd("ioscli errlog")
        return err_res.stdout_text, "ioscli errlog"

    def _check_vios_logs_for_unexpected(self):
        """
        Warn on non-EEH Temporary/Permanent Hardware errors whose
        resource is one of the physical/virtual devices in the vSCSI
        path (parent_dev, physical_hdisk, vios_hdisk, vtd).

        sysplanar0 errors with EEH-expected IDs are silently accepted;
        all other sysplanar0 and unrelated-resource entries are ignored.
        This step never fails the test.
        """
        eeh_expected_ids = {'E142C6D4', 'E2EC9CD2'}
        parent_dev, physical_hdisk = self._get_physical_devs()
        our_devices = {
            parent_dev,
            physical_hdisk,
            self.vios_hdisk,
            self.vtd,
        }
        self.log.info(
            "Error log filtering: watching devices %s",
            sorted(our_devices)
        )

        log_text, log_source = self._read_vios_errlog()
        self.log.info(
            "--- VIOS %s output ---\n%s", log_source, log_text.strip()
        )

        unexpected = []
        for line in log_text.splitlines():
            parts = line.split()
            if len(parts) < 5:
                continue
            identifier = parts[0]
            severity = parts[2]
            category = parts[3]
            resource = parts[4]

            if severity not in ('T', 'P') or category != 'H':
                continue

            if resource == 'sysplanar0':
                if identifier not in eeh_expected_ids:
                    self.log.debug(
                        "Ignoring non-EEH sysplanar0 error (id=%s) "
                        "— pre-existing platform entry, not related "
                        "to vSCSI path under test", identifier
                    )
                continue

            if resource not in our_devices:
                self.log.debug(
                    "Ignoring error on unrelated resource %s "
                    "(id=%s) — not in vSCSI path under test",
                    resource, identifier
                )
                continue

            if identifier not in eeh_expected_ids:
                unexpected.append(f"  {line.strip()}")
                self.log.warning(
                    "Unexpected hardware error on vSCSI path device "
                    "in VIOS log: id=%s resource=%s — '%s'",
                    identifier, resource, line.strip()
                )

        if unexpected:
            self.log.warning(
                "--- %d unexpected VIOS hardware error(s) found "
                "in %s on vSCSI path devices "
                "(test will still pass if states match) ---\n%s",
                len(unexpected), log_source, "\n".join(unexpected)
            )
        else:
            self.log.info(
                "VIOS error log contains no unexpected hardware "
                "errors on vSCSI path devices"
            )

    def _wait_and_get_post_eeh_states(self):
        """
        Poll the VIOS physical adapter and hdisk until both leave the
        transient 'Defined' state (up to INJECT_CONFIRM_SECS each),
        then read VTD status via lsmap.

        Returns {adapter: state, hdisk: state, vtd: state}.
        Fails immediately if either physical device does not recover
        within the polling window.
        """
        parent_dev, physical_hdisk = self._get_physical_devs()
        states = {}

        for dev in (parent_dev, physical_hdisk):
            self.log.info(
                "Polling physical device %s for stable state "
                "(timeout %ds)...", dev, INJECT_CONFIRM_SECS
            )
            last_state = "<unavailable>"
            recovered = False
            for _ in range(INJECT_CONFIRM_SECS):
                res = self.vios_session.cmd(
                    f"ioscli lsdev -dev {dev}"
                )
                if res.exit_status == 0:
                    match = re.search(
                        r'^\S+\s+(\w+)', res.stdout_text, re.MULTILINE
                    )
                    if match:
                        last_state = match.group(1)
                        if last_state != "Defined":
                            recovered = True
                            break
                time.sleep(1)

            if not recovered:
                self.fail(
                    f"VIOS device {dev} did not leave 'Defined'/error "
                    f"state within {INJECT_CONFIRM_SECS}s after EEH "
                    f"injection. Last observed state: '{last_state}'"
                )

            self.log.info(
                "Physical device %-10s post-EEH state: %s",
                dev, last_state
            )
            states[dev] = last_state

        vtd_state = self._get_vtd_status()
        states[self.vtd] = vtd_state
        self.log.info(
            "Virtual device  %-10s post-EEH state: %s",
            self.vtd, vtd_state
        )

        return states

    def _teardown_close_vios_session(self):
        """
        Cleanly terminate the VIOS SSH ControlMaster session and remove
        its socket file. quit() sends '-O exit' to the master process;
        cleanup_master() removes the socket file. Both are called
        unconditionally so a failed quit() still cleans up the socket.
        """
        session = getattr(self, 'vios_session', None)
        if not session:
            return

        self.log.info("Closing VIOS SSH ControlMaster session")
        quit_ok = session.quit()
        if not quit_ok:
            self.log.warning(
                "VIOS session quit() returned failure — "
                "master may have already exited"
            )

        try:
            session.cleanup_master()
            self.log.info(
                "VIOS SSH ControlMaster socket file removed"
            )
        except OSError as exc:
            self.log.debug(
                "cleanup_master: socket file not found (%s)", exc
            )

        self.vios_session = None

    def _log_vios_traces(self):
        """
        Retrieve and log VIOS AIX error report entries.
        EEH injection traces are expected here and confirm the VIOS
        recorded the physical error event. Falls back to ioscli errlog
        if errpt is unavailable.
        """
        log_text, log_source = self._read_vios_errlog()
        self.log.info(
            "--- VIOS %s Output ---\n%s", log_source, log_text.strip()
        )

    def tearDown(self):  # pylint: disable=invalid-name
        """
        Capture VIOS forensic traces and close the VIOS SSH session.
        No virtual device mapping changes are made — the test does not
        touch vhost/VTD mappings.
        """
        self.log.info(
            "========= Starting vSCSI EEH Test tearDown ========="
        )

        if hasattr(self, 'vios_session') and self.vios_session:
            self._log_vios_traces()

        self._teardown_close_vios_session()

        self.log.info(
            "========= vSCSI EEH Test tearDown Complete ========="
        )
