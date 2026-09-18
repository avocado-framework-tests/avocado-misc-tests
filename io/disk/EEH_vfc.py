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
VIOS-Level EEH Error Injection and Recovery Test for Virtual Fibre Channel
(ibmvfc / NPIV) adapters on IBM PowerVM LPAR.

Connects to the VIOS, maps the target virtual FC disk to its physical fcsX
backing adapter via NPIV lsmap, uses eeh_tool Op 3 to inject a recoverable
EEH freeze, monitors ibmvfc transport recovery on the client LPAR (PLOGI,
PRLI, Re-enabling adapter), and validates disk health after recovery.

Architecture: NPIV — VIOS exposes a vfchost port backed by a physical fcsX
HBA. Client sees FC LUNs via ibmvfc. VIOS mapping restore uses
'ioscli mkvdev -fcp -vadapter <vfchost>' (port-level virtual device).

eeh_tool (64-bit: eeh_tool_64) must run as root via oem_setup_env; it opens
/dev/nvram via ioctl for RTAS firmware calls. errinjct is not supported.
"""

import os
import re
import select
import struct
import time

from avocado import Test
from avocado.utils import dmesg
from avocado.utils import distro
from avocado.utils import genio
from avocado.utils import process
from avocado.utils import wait
from avocado.utils.ssh import Session
from avocado.utils.software_manager.manager import SoftwareManager

RECOVERY_TIMEOUT_SECS = 300
DISK_RESCAN_TIMEOUT_SECS = 60
INJECT_CONFIRM_SECS = 180
VIOS_CRQ_RELEASE_WAIT_SECS = 60

# eeh_tool Op 3 function codes that produce a recoverable EEH freeze.
#
# Only Load/Store address-parity and data-parity errors (functions 0-11)
# are used. These inject a PCI bus freeze that the RTAS firmware classifies
# as recoverable, allowing the OS EEH handler to reset the slot and bring
# the adapter back online. On PCIe adapters they map to TLP ECRC errors.
#
# Excluded non-recoverable / inapplicable functions:
#   14 - DMA Read  Master abort  : not applicable on PCIe; may permanently
#                                   disable the slot rather than freeze it.
#   18 - DMA Write Master abort  : same reason as 14.
#   19 - DMA Write Target abort  : explicitly "Not Applicable" on PCIe per
#                                   eeh_tool help output.
#   15 - DMA Read  Target abort  : Completer Abort on PCIe; firmware
#                                   severity classification is
#                                   implementation-defined and may be
#                                   treated as fatal on some adapters.
#
# Selected injection functions (recoverable):
#   EEH_FUNC_MEM_LOAD_DATA  = 1  (Load Memory Space Data parity / TLP ECRC)
#   EEH_FUNC_IO_LOAD_DATA   = 3  (Load I/O Space Data parity  / TLP ECRC)
# Function 1 is preferred for mem-addr injection because data-path parity
# errors most reliably trigger the freeze+recover cycle across both
# PCI/PCI-X and PCIe adapter generations used in PowerVM VIOS environments.
EEH_FUNC_MEM_LOAD_DATA = 1   # Load Memory Space Data parity / TLP ECRC
EEH_FUNC_IO_LOAD_DATA = 3    # Load I/O Space Data parity   / TLP ECRC
EEH_FUNC_ODM_DEFAULT = 1     # fallback when no address from Op 5


class EEHVfc(Test):
    """
    VIOS-Level EEH Error Injection and Recovery test for Virtual Fibre
    Channel (ibmvfc / NPIV) devices on IBM PowerVM LPAR.
    """

    def setUp(self):
        """
        Validate environments, load YAML inputs, connect to the VIOS,
        and map the client virtual FC disk to the underlying physical VIOS
        FC adapter (fcsX) via NPIV lsmap.
        """
        self.log.info("========= Starting vFC EEH Test Setup =========")

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
        self.eeh_tool_path = '/home/padmin/eeh_tool_64'
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
                "Failed to establish SSH connection to VIOS at %s"
                % self.vios_ip
            )
        self.log.info("Connected to VIOS successfully")

        if not os.path.exists(self.disk_input):
            self.cancel(
                "Target disk input %s does not exist on client LPAR"
                % self.disk_input
            )
        self.disk_name = os.path.basename(
            os.path.realpath(self.disk_input)
        )
        self.log.info("Resolved client disk name: %s", self.disk_name)

        self.fc_host = self._get_fc_host_for_disk()
        self.log.info(
            "Resolved FC host for %s: %s",
            self.disk_name, self.fc_host
        )

        self.client_wwpn = self._get_client_wwpn()
        if not self.client_wwpn:
            self.fail(
                "Failed to resolve client WWPN for FC host %s. "
                "Ensure ibmvfc driver is loaded and fc_host sysfs "
                "is populated." % self.fc_host
            )
        self.log.info(
            "Resolved client WWPN: %s", self.client_wwpn
        )

        self._discover_vios_npiv_devices()

        self._ensure_eeh_tool()

        self._log_vios_fcs_state()

        smm = SoftwareManager()
        if not smm.check_installed('sg3_utils') and \
                not smm.install('sg3_utils'):
            self.cancel(
                "Required package 'sg3_utils' could not be installed "
                "on client LPAR"
            )

        self.log.info(
            "========= vFC EEH Test Setup Complete ========="
        )

    def test_eeh_vfc(self):
        """
        Execute the physical EEH error injection on the VIOS backing FC
        HBA, verify that ibmvfc transport reset recovery initiates and
        succeeds on LPAR, and confirm target device health and
        post-recovery I/O accessibility.
        """
        self.log.info("--- Initiating EEH Error Injection on VIOS ---")

        dmesg.clear_dmesg()

        self._inject_eeh_on_vios()

        self.log.info(
            "Triggering active I/O read on client LPAR to force FC "
            "transport detection..."
        )
        process.run(
            "dd if=/dev/%s of=/dev/null bs=512 count=1"
            % self.disk_name,
            ignore_status=True, shell=True, timeout=5
        )

        self.log.info(
            "Monitoring client logs for ibmvfc reset/recovery..."
        )
        if not self._check_reset_started():
            self.fail(
                "LPAR ibmvfc driver did not detect transport disruption "
                "within %ds — EEH injection may not have reached the "
                "client" % INJECT_CONFIRM_SECS
            )

        self._restore_eeh_on_vios()

        self._close_vios_session_for_crq_release()

        self.log.info(
            "Waiting for client LPAR FC transport recovery..."
        )
        if not self._check_vfc_login_recovered():
            self.fail(
                "ibmvfc adapter FC login recovery timed out or failed "
                "within %ds" % RECOVERY_TIMEOUT_SECS
            )

        self.log.info(
            "vFC transport recovery confirmed - LPAR reconnected"
        )

        if not self._wait_for_disk_reappear():
            self.fail(
                "Disk %s did not reappear on the LPAR within %ds "
                "after FC transport recovery"
                % (self.disk_name, DISK_RESCAN_TIMEOUT_SECS)
            )

        self.log.info(
            "Performing final post-recovery health audit..."
        )
        self._verify_post_recovery_health()

        self.log.info(
            "vFC device recovered successfully, test passed"
        )

    # ------------------------------------------------------------------ #
    #  Helper Methods                                                     #
    # ------------------------------------------------------------------ #

    def _get_fc_host_for_disk(self):
        """
        Resolve the fc_host sysfs name (e.g. 'host3') for the client
        disk via sysfs. Used to anchor dmesg recovery signal matching
        to this ibmvfc adapter and to retrieve the client WWPN.
        """
        try:
            real = os.path.realpath(
                "/sys/block/%s/device" % self.disk_name
            )
            match = re.search(r'(host\d+)', real)
            if match:
                return match.group(1)
        except OSError:
            pass
        return ""

    def _get_client_wwpn(self):
        """
        Retrieve the ibmvfc client WWPN from the fc_host sysfs node.
        The WWPN is used to match the client's virtual FC port against
        the VIOS NPIV lsmap output.

        Returns the WWPN string (e.g. '0x10000090fa1b2c3d') or None.
        """
        if not self.fc_host:
            return None
        wwpn_path = "/sys/class/fc_host/%s/port_name" % self.fc_host
        if not os.path.exists(wwpn_path):
            self.log.warning(
                "fc_host sysfs port_name not found at %s", wwpn_path
            )
            return None
        try:
            wwpn = genio.read_file(wwpn_path).strip().lower()
            self.log.info(
                "Read client WWPN from %s: %s", wwpn_path, wwpn
            )
            return wwpn
        except OSError as exc:
            self.log.warning(
                "Failed to read WWPN from %s: %s", wwpn_path, exc
            )
            return None

    def _discover_vios_npiv_devices(self):
        """
        Discover the VIOS vfchost and its physical fcsX backing adapter
        using 'ioscli lsmap -all -npiv'.

        Primary match: 'VFC client name:' field matches self.fc_host
        (e.g. 'host1'). Fallback: decimal ClntID matches LPAR partition
        number. Populates self.vfchost and self.vios_fcs on success.
        """
        lpar_id_hex = None
        lpar_name = None

        part_no_path = "/proc/device-tree/ibm,partition-no"
        if os.path.exists(part_no_path):
            try:
                with open(part_no_path, "rb") as fh:
                    part_no_bytes = fh.read()
                partition_id = struct.unpack(">I", part_no_bytes)[0]
                lpar_id_hex = "0x%08x" % partition_id
                self.log.info(
                    "Resolved LPAR Partition ID: %d (%s)",
                    partition_id, lpar_id_hex
                )
            except OSError as exc:
                self.log.debug(
                    "Failed to read partition-no from device-tree: %s",
                    exc
                )

        part_name_path = "/proc/device-tree/ibm,partition-name"
        if os.path.exists(part_name_path):
            try:
                with open(part_name_path, "r",
                          encoding="utf-8") as fh:
                    lpar_name = fh.read().strip("\x00 \n\r")
                self.log.info(
                    "Resolved LPAR Partition Name: %s", lpar_name
                )
            except OSError as exc:
                self.log.debug(
                    "Failed to read partition-name from device-tree: "
                    "%s", exc
                )

        self.log.info(
            "Querying 'ioscli lsmap -all -npiv' on VIOS to parse "
            "NPIV mappings..."
        )
        res = self.vios_session.cmd("ioscli lsmap -all -npiv")
        if res.exit_status != 0:
            self.fail(
                "Failed to execute 'ioscli lsmap -all -npiv' on VIOS: "
                "%s" % res.stderr_text
            )

        # Real lsmap -all -npiv output format (one block per vfchost):
        #
        #   Name          Physloc                            ClntID ...
        #   ------------- ---------------------------------- ------
        #   vfchost0      U9043.MRX.13ECF5X-V100-C201             1 ...
        #
        #   Status:LOGGED_IN
        #   FC name:fcs0                    FC loc code:...
        #   Ports logged in:1
        #   VFC client name:host1           VFC client DRC:...
        #
        # Key observations:
        #   - ClntID is a plain decimal integer (not hex).
        #   - FC name: has no space after the colon.
        #   - WWPNs are NOT listed; client FC host is in VFC client name:.
        #   - Header/separator lines appear before each block and must be
        #     skipped.
        lsmap_raw = res.stdout_text
        vfchost_data = {}
        current_vfchost = None

        for line in lsmap_raw.splitlines():
            line_str = line.strip()
            # Skip blank lines, header rows, and dashed separator lines.
            if (not line_str
                    or line_str.startswith("Name ")
                    or line_str.startswith("-----")):
                continue

            # vfchost header line: name, physloc, optional ClntID fields.
            vfchost_match = re.match(
                r'^(vfchost\d+)\s+\S+(?:\s+(\S+))?', line_str
            )
            if vfchost_match:
                current_vfchost = vfchost_match.group(1)
                client_id_raw = vfchost_match.group(2) or ""
                vfchost_data[current_vfchost] = {
                    "client_id": client_id_raw,
                    "fcs": None,
                    "vfc_client_name": "",
                }
                continue

            if current_vfchost:
                # FC name:fcsX — no space after the colon in real output.
                fc_name_match = re.match(
                    r'FC name:(\S+)', line_str
                )
                if fc_name_match:
                    fcs_val = fc_name_match.group(1)
                    # Ignore empty placeholder (FC name: with nothing).
                    if fcs_val:
                        vfchost_data[current_vfchost]["fcs"] = fcs_val
                    continue

                # VFC client name:hostN — carries the ibmvfc host name.
                vfc_client_match = re.match(
                    r'VFC client name:(\S*)', line_str
                )
                if vfc_client_match:
                    vfchost_data[current_vfchost]["vfc_client_name"] = (
                        vfc_client_match.group(1)
                    )

        self.log.debug(
            "Parsed VIOS NPIV mappings: %s", vfchost_data
        )

        matched_vfchost = None
        matched_fcs = None

        # Primary match: VFC client name (e.g. 'host1') == self.fc_host.
        if self.fc_host:
            for vfchost, data in vfchost_data.items():
                if data["vfc_client_name"] == self.fc_host:
                    self.log.info(
                        "FC host match: client fc_host '%s' found under "
                        "vfchost %s (fcs: %s)",
                        self.fc_host, vfchost, data["fcs"]
                    )
                    matched_vfchost = vfchost
                    matched_fcs = data["fcs"]
                    break

        # Fallback: decimal ClntID matches LPAR partition number.
        if not matched_vfchost and lpar_id_hex:
            self.log.warning(
                "FC host name matching failed. Trying partition ID "
                "fallback (%s)...", lpar_id_hex
            )
            lpar_id_int = int(lpar_id_hex, 16)
            for vfchost, data in vfchost_data.items():
                client_id = data["client_id"]
                if not client_id or client_id.lower() == "none":
                    continue
                # ClntID is decimal; try decimal first, then hex.
                matched_id = False
                for base in (10, 16):
                    try:
                        if int(client_id, base) == lpar_id_int:
                            matched_id = True
                            break
                    except ValueError:
                        pass
                if matched_id:
                    matched_vfchost = vfchost
                    matched_fcs = data["fcs"]
                    self.log.warning(
                        "Fallback matched vfchost %s (fcs %s) "
                        "via partition ID %s",
                        matched_vfchost, matched_fcs, lpar_id_hex
                    )
                    break

        if not matched_vfchost or not matched_fcs:
            self.fail(
                "Failed to find VIOS NPIV vfchost/fcsX mapping for "
                "client fc_host '%s' / WWPN %s (LPAR partition %s). "
                "Verify NPIV is configured and the LPAR is logged in.\n"
                "Raw lsmap output:\n%s"
                % (self.fc_host, self.client_wwpn,
                   lpar_id_hex, lsmap_raw.strip())
            )

        self.vfchost = matched_vfchost
        self.vios_fcs = matched_fcs
        self.log.info(
            "Resolved VIOS NPIV mapping: vfchost=%s fcs=%s",
            self.vfchost, self.vios_fcs
        )

    def _log_vios_fcs_state(self):
        """
        Retrieve and log the health and configuration status of the
        physical FC adapter (fcsX) on VIOS. Recorded for informational
        purposes only.
        """
        cmd = "ioscli lsdev -dev %s" % self.vios_fcs
        res = self.vios_session.cmd(cmd)
        if res.exit_status == 0:
            self.log.info(
                "VIOS Physical FC Adapter Status:\n%s",
                res.stdout_text.strip()
            )
        else:
            self.log.warning(
                "Could not retrieve VIOS status for %s",
                self.vios_fcs
            )

    def _ensure_eeh_tool(self):
        """
        Ensure eeh_tool_64 exists and is executable on the VIOS.

        If eeh_tool_url is set, checks whether the binary already exists at
        the hardcoded eeh_tool_path. If not, downloads the binary directly
        from eeh_tool_url using python3 urllib.request and sets execute
        permission.

        wget and curl are absent on this VIOS. python3 is confirmed
        available and urllib.request handles plain HTTP downloads reliably
        on AIX. The URL is expected to serve the plain eeh_tool_64 binary
        directly (no zip or cpgz extraction needed).
        """
        if not self.eeh_tool_url:
            self.log.info(
                "eeh_tool_url not set — assuming eeh_tool_64 is already "
                "present at %s on VIOS", self.eeh_tool_path
            )
            return

        # Check if the binary already exists and is executable.
        check_res = self._run_as_root(
            "test -x %s && echo EXISTS || echo MISSING"
            % self.eeh_tool_path
        )
        if "EXISTS" in check_res.stdout_text:
            self.log.info(
                "eeh_tool_64 already present and executable at %s — "
                "skipping download", self.eeh_tool_path
            )
            return

        self.log.info(
            "eeh_tool_64 not found at %s — downloading from %s",
            self.eeh_tool_path, self.eeh_tool_url
        )

        # Use python3 urllib.request to download the binary over HTTP.
        # wget and curl are absent on this VIOS; python3 is confirmed
        # available and its stdlib HTTP client works on AIX without any
        # additional packages.
        #
        # ksh/quoting constraint: _run_as_root wraps commands inside
        # echo "..." | oem_setup_env.  ksh treats '(' as a subshell
        # operator even inside the echo argument, so any python3 -c
        # "..." string containing function calls triggers:
        #   ksh: 0403-057 Syntax error at line 1 : '(' is not expected.
        #
        # Solution: feed python3 via a shell heredoc.  The heredoc body
        # is passed verbatim to python3's stdin — ksh never parses its
        # contents as shell syntax.  echo "python3 << PYEOF\n...\nPYEOF"
        # is safe because echo treats everything up to the closing
        # delimiter as literal text.
        dl_cmd = (
            "python3 << PYEOF\n"
            "import urllib.request\n"
            "urllib.request.urlretrieve("
            "\"%(url)s\", \"%(dest)s\")\n"
            "print(\"DOWNLOADED\")\n"
            "PYEOF"
        ) % {"url": self.eeh_tool_url, "dest": self.eeh_tool_path}

        dl_res = self._run_as_root(dl_cmd)
        if dl_res.exit_status != 0 or \
                "DOWNLOADED" not in dl_res.stdout_text:
            self.fail(
                "Failed to download eeh_tool_64 from %s to %s on "
                "VIOS %s: %s"
                % (self.eeh_tool_url, self.eeh_tool_path, self.vios_ip,
                   dl_res.stderr_text.strip())
            )

        # Set execute permission.
        chmod_res = self._run_as_root(
            "chmod +x %s" % self.eeh_tool_path
        )
        if chmod_res.exit_status != 0:
            self.fail(
                "Failed to set execute permission on %s on VIOS %s: %s"
                % (self.eeh_tool_path, self.vios_ip,
                   chmod_res.stderr_text.strip())
            )

        self.log.info(
            "eeh_tool_64 downloaded and ready at %s on VIOS %s",
            self.eeh_tool_path, self.vios_ip
        )

    def _run_as_root(self, cmd):
        """
        Execute an AIX command as root on the VIOS by piping it into
        oem_setup_env. Prevents interactive terminal hangs and bypasses
        restricted shell (rksh) blocks.

        Only echo is available in the padmin rksh environment before
        oem_setup_env elevates to root. The command string is embedded
        inside echo "..." so double-quotes within cmd must be escaped.
        """
        escaped_cmd = cmd.replace('"', '\\"')
        pipe_cmd = 'echo "%s" | oem_setup_env' % escaped_cmd
        return self.vios_session.cmd(pipe_cmd)

    def _resolve_fcs_parent_adapter(self):
        """
        Resolve the fcsX device name on the VIOS as the injectable adapter.

        For FC HBAs eeh_tool is invoked directly on the fcsX device.
        Verifies the device exists via 'lsdev -Cl <fcs>' and returns it
        unchanged. Fails if the device is unavailable.
        """
        check_res = self._run_as_root(
            "lsdev -Cl %s" % self.vios_fcs
        )
        if check_res.exit_status != 0 or \
                not check_res.stdout_text.strip():
            self.fail(
                "Could not verify FC adapter %s on VIOS — "
                "lsdev -Cl returned: %s"
                % (self.vios_fcs, check_res.stderr_text.strip())
            )
        self.log.info(
            "Verified VIOS FC adapter for EEH injection: %s",
            self.vios_fcs
        )
        return self.vios_fcs

    def _check_eeh_enabled(self, adapter_dev):
        """
        Verify that EEH error injection is enabled for the slot occupied
        by adapter_dev using eeh_tool Op 1 (Query Slot Capabilities and
        Slot State). Fails the test with a clear message if EEH is not
        enabled or the tool cannot be executed.
        """
        self.log.info(
            "Checking eeh_tool availability at %s on VIOS...",
            self.eeh_tool_path
        )
        avail_res = self._run_as_root(
            "test -x %s && echo AVAILABLE || echo MISSING"
            % self.eeh_tool_path
        )
        if "MISSING" in avail_res.stdout_text or \
                "AVAILABLE" not in avail_res.stdout_text:
            self.fail(
                "eeh_tool binary not found or not executable at %s "
                "on VIOS %s. Place eeh_tool_64 at that path and ensure "
                "it has execute permission before running this test."
                % (self.eeh_tool_path, self.vios_ip)
            )

        self.log.info(
            "Querying EEH slot capabilities for adapter %s "
            "via eeh_tool Op 1...", adapter_dev
        )
        query_cmd = "%s %s 1" % (self.eeh_tool_path, adapter_dev)
        query_res = self._run_as_root(query_cmd)

        if query_res.exit_status == 255:
            self.fail(
                "eeh_tool could not open the AIX machine device driver "
                "on VIOS %s (errno=13 / EACCES). The binary must be run "
                "as root. Ensure oem_setup_env provides root context or "
                "set the SUID bit: chmod 4750 %s"
                % (self.vios_ip, self.eeh_tool_path)
            )

        output = query_res.stdout_text
        self.log.info(
            "eeh_tool Op 1 output for %s:\n%s", adapter_dev, output
        )

        cap_match = re.search(
            r'slot_capabilities\s*=\s*(\d+)', output
        )
        if cap_match:
            slot_cap = int(cap_match.group(1))
            if slot_cap == 0:
                self.fail(
                    "EEH injection is not enabled: eeh_tool reports "
                    "slot_capabilities=0 for adapter %s on VIOS %s. "
                    "EEH must be enabled on this slot before this test "
                    "can run." % (adapter_dev, self.vios_ip)
                )
            self.log.info(
                "EEH enabled confirmed: slot_capabilities=%d for "
                "adapter %s", slot_cap, adapter_dev
            )
        else:
            self.log.warning(
                "Could not parse 'slot_capabilities' from eeh_tool "
                "Op 1 output for %s. Proceeding with injection; "
                "verify eeh_tool output manually if injection fails.",
                adapter_dev
            )

    def _get_eeh_bus_addresses(self, adapter_dev):
        """
        Retrieve PCI bus addresses for adapter_dev from eeh_tool Op 5
        (IO Information). Returns (bus_mem_addr, bus_io_addr) as hex
        strings for use as the -a argument in eeh_tool Op 3. Falls back
        to None values if Op 5 cannot parse a usable address.
        """
        self.log.info(
            "Querying PCI bus addresses for %s via eeh_tool Op 5...",
            adapter_dev
        )
        info_cmd = "%s %s 5" % (self.eeh_tool_path, adapter_dev)
        info_res = self._run_as_root(info_cmd)

        if info_res.exit_status == 255:
            self.log.warning(
                "eeh_tool Op 5 returned exit 255 for %s — "
                "machine DD open failed; will use ODM defaults for "
                "address/mask in Op 3.", adapter_dev
            )
            return None, None

        output = info_res.stdout_text
        self.log.info(
            "eeh_tool Op 5 output for %s:\n%s", adapter_dev, output
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

    def _build_eeh_inject_cmd(self, adapter_dev, bus_mem_addr,
                              bus_io_addr):
        """
        Construct the eeh_tool Op 3 command string for EEH error
        injection on adapter_dev (the fcsX FC HBA on VIOS).

        Only recoverable function codes are used; see module-level
        constant comments for rationale.
        """
        mask = "0x0fffffff"

        mem_val = int(bus_mem_addr, 16) if bus_mem_addr else 0
        io_val = int(bus_io_addr, 16) if bus_io_addr else 0

        if mem_val != 0:
            cmd = (
                "%s %s 3 %d -a %s -m %s"
                % (self.eeh_tool_path, adapter_dev,
                   EEH_FUNC_MEM_LOAD_DATA, bus_mem_addr, mask)
            )
            self.log.info(
                "EEH inject command (mem addr, func %d — recoverable "
                "Load Memory Data parity / TLP ECRC): %s",
                EEH_FUNC_MEM_LOAD_DATA, cmd
            )
        elif io_val != 0:
            cmd = (
                "%s %s 3 %d -a %s -m %s"
                % (self.eeh_tool_path, adapter_dev,
                   EEH_FUNC_IO_LOAD_DATA, bus_io_addr, mask)
            )
            self.log.info(
                "EEH inject command (I/O addr, func %d — recoverable "
                "Load I/O Data parity / TLP ECRC): %s",
                EEH_FUNC_IO_LOAD_DATA, cmd
            )
        else:
            cmd = (
                "%s %s 3 %d"
                % (self.eeh_tool_path, adapter_dev, EEH_FUNC_ODM_DEFAULT)
            )
            self.log.info(
                "EEH inject command (ODM default addr, func %d — "
                "recoverable Load Memory Data parity): %s",
                EEH_FUNC_ODM_DEFAULT, cmd
            )

        return cmd

    def _inject_eeh_on_vios(self):
        """
        Orchestrate physical EEH error injection on the VIOS fcsX FC HBA
        using eeh_tool_64.

        Verifies fcsX via lsdev, confirms EEH via Op 1, queries PCI bus
        addresses via Op 5, builds and executes the Op 3 inject command
        under oem_setup_env. Fails immediately on any step error.
        """
        adapter_dev = self._resolve_fcs_parent_adapter()

        self._check_eeh_enabled(adapter_dev)

        bus_mem_addr, bus_io_addr = self._get_eeh_bus_addresses(
            adapter_dev
        )

        inject_cmd = self._build_eeh_inject_cmd(
            adapter_dev, bus_mem_addr, bus_io_addr
        )

        self.log.info(
            "Injecting EEH error on VIOS FC adapter %s via eeh_tool "
            "Op 3", adapter_dev
        )
        inject_res = self._run_as_root(inject_cmd)

        # Log eeh_tool stdout/stderr immediately so injection outcome is
        # visible in the job log regardless of whether the LPAR detects it.
        self.log.info(
            "eeh_tool Op 3 stdout for %s:\n%s",
            adapter_dev,
            inject_res.stdout_text.strip() or "<no output>"
        )
        if inject_res.stderr_text.strip():
            self.log.warning(
                "eeh_tool Op 3 stderr for %s:\n%s",
                adapter_dev, inject_res.stderr_text.strip()
            )

        if inject_res.exit_status != 0:
            self.fail(
                "eeh_tool EEH injection failed (exit %d) for FC adapter "
                "%s on VIOS %s.\nCommand: %s\nOutput: %s"
                % (
                    inject_res.exit_status,
                    adapter_dev,
                    self.vios_ip,
                    inject_cmd,
                    inject_res.stdout_text.strip()
                )
            )

        self.log.info(
            "EEH error injection via eeh_tool completed successfully "
            "for FC adapter %s — capturing VIOS AIX errpt snapshot...",
            adapter_dev
        )
        self._log_vios_injection_errpt(adapter_dev)

    def _restore_eeh_on_vios(self):
        """
        Restore the NPIV virtual FC port mapping on VIOS to allow client
        LPAR recovery. For vFC, recovery is triggered by removing and
        re-adding the vfchost port mapping rather than a VTD device.
        'mkvdev -fcp' re-enables the NPIV virtual FC port on the VIOS so
        the client can re-login via PLOGI/PRLI.
        """
        self.log.info(
            "--- Restoring VIOS NPIV vfchost mapping and initiating "
            "FC recovery ---"
        )
        add_cmd = (
            "ioscli mkvdev -fcp -vadapter %s" % self.vfchost
        )
        self.log.info(
            "Restoring NPIV vfchost mapping: %s", add_cmd
        )
        add_res = self.vios_session.cmd(add_cmd)
        if add_res.exit_status != 0:
            self.log.error(
                "mkvdev -fcp failed to restore NPIV mapping: %s",
                add_res.stderr_text
            )
        self.log.info(
            "NPIV reconnection restoration phase completed"
        )

    def _close_vios_session_for_crq_release(self):
        """
        Close the VIOS SSH session immediately after mkvdev -fcp, then
        wait 60s. This allows the VIOS to GC the NPIV transport state so
        the client ibmvfc adapter completes FC re-login (PLOGI/PRLI) in
        seconds rather than waiting for the passive reconnect timer. The
        session is reopened for tearDown.
        """
        self.log.info(
            "Closing VIOS session to release NPIV endpoint — "
            "quiescing %ds for VIOS to GC FC transport state...",
            VIOS_CRQ_RELEASE_WAIT_SECS
        )
        self.vios_session.quit()
        try:
            self.vios_session.cleanup_master()
        except OSError:
            pass

        time.sleep(VIOS_CRQ_RELEASE_WAIT_SECS)

        self.log.info(
            "Reconnecting to VIOS at %s after quiesce...",
            self.vios_ip
        )
        self.vios_session = Session(
            self.vios_ip,
            user=self.vios_username,
            password=self.vios_pwd,
        )
        if not wait.wait_for(self.vios_session.connect, timeout=30):
            self.log.warning(
                "VIOS reconnect after quiesce failed — "
                "tearDown will skip VIOS operations"
            )
            self.vios_session = None
        else:
            self.log.info(
                "VIOS session re-established after quiesce"
            )

    def _watch_kmsg(self, match_signals, fail_signals,
                    timeout_secs, label):
        """
        Event-driven kernel message watcher using /dev/kmsg + select().
        Seeks to end of /dev/kmsg and detects new records within
        milliseconds. Returns True when a match_signal is found, False
        on a fail_signal or when timeout_secs expires. Falls back to
        dmesg polling if /dev/kmsg cannot be opened.
        """
        deadline = time.monotonic() + timeout_secs
        remainder = b""

        try:
            kmsg_fd = os.open("/dev/kmsg", os.O_RDONLY | os.O_NONBLOCK)
            os.lseek(kmsg_fd, 0, os.SEEK_END)
        except OSError as exc:
            self.log.warning(
                "Cannot open /dev/kmsg (%s); falling back to dmesg "
                "polling", exc
            )
            return self._poll_dmesg_fallback(
                match_signals, fail_signals, timeout_secs, label
            )

        self.log.info(
            "Watching /dev/kmsg for %s (deadline %ds)...",
            label, timeout_secs
        )

        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.log.warning(
                        "%s: deadline reached (%ds) without matching "
                        "signal", label, timeout_secs
                    )
                    return False

                ready, _, _ = select.select(
                    [kmsg_fd], [], [], min(remaining, 5.0)
                )

                if ready:
                    try:
                        chunk = os.read(kmsg_fd, 8192)
                        remainder += chunk
                    except BlockingIOError:
                        continue

                    lines = remainder.split(b"\n")
                    remainder = lines[-1]

                    for raw_line in lines[:-1]:
                        sep = raw_line.find(b";")
                        msg = (
                            raw_line[sep + 1:] if sep != -1
                            else raw_line
                        )
                        text = msg.decode("utf-8", errors="replace")

                        for sig in fail_signals:
                            if sig in text:
                                elapsed = timeout_secs - remaining
                                self.log.error(
                                    "%s: failure signal matched after "
                                    "%.1fs: '%s'",
                                    label, elapsed, sig
                                )
                                return False

                        for sig in match_signals:
                            if sig in text:
                                elapsed = timeout_secs - remaining
                                self.log.info(
                                    "%s: recovery signal matched after "
                                    "%.1fs: '%s'",
                                    label, elapsed, sig
                                )
                                return True
        finally:
            os.close(kmsg_fd)

    def _poll_dmesg_fallback(self, match_signals, fail_signals,
                             timeout_secs, label):
        """
        Fallback dmesg polling when /dev/kmsg is not accessible.
        Reads the full post-clear ring buffer once per second.
        """
        deadline = time.monotonic() + timeout_secs
        while time.monotonic() < deadline:
            res = process.run("dmesg", ignore_status=True, shell=True)
            output = res.stdout.decode("utf-8", errors="replace")
            for sig in fail_signals:
                if sig in output:
                    self.log.error(
                        "%s: failure signal in dmesg: '%s'", label, sig
                    )
                    return False
            for sig in match_signals:
                if sig in output:
                    self.log.info(
                        "%s: recovery signal in dmesg: '%s'", label, sig
                    )
                    return True
            time.sleep(1)
        return False

    def _check_reset_started(self):
        """
        Verify that the client LPAR detects FC transport failure and
        initiates recovery. ibmvfc signals disruption via adapter reset
        messages, link-down events, and I/O errors. Uses /dev/kmsg
        event-driven detection.
        """
        disruption_signals = [
            'ibmvfc',
            'adapter reset',
            'LOGO',
            'link down',
            'I/O error',
            'transport',
        ]
        return self._watch_kmsg(
            match_signals=disruption_signals,
            fail_signals=[],
            timeout_secs=INJECT_CONFIRM_SECS,
            label="vfc-disruption-detection",
        )

    def _check_vfc_login_recovered(self):
        """
        Monitor client LPAR for ibmvfc transport recovery via /dev/kmsg
        select(). ibmvfc signals recovery through PLOGI/PRLI completion,
        'Re-enabling adapter', or target discovery messages. All known
        recovery strings across ibmvfc driver versions are checked.
        """
        recovery_signals = [
            'Re-enabling adapter',
            'ibmvfc: Target',
            'PLOGI',
            'PRLI',
            'ibmvfc.*login',
            'ibmvfc.*online',
        ]
        failure_signals = ['ibmvfc.*failed', 'error after reset']
        return self._watch_kmsg(
            match_signals=recovery_signals,
            fail_signals=failure_signals,
            timeout_secs=RECOVERY_TIMEOUT_SECS,
            label="vfc-recovery",
        )

    def _wait_for_disk_reappear(self):
        """
        Poll /sys/class/block/ to find the device node after FC recovery.
        Handles possible device name alterations after FC target rescans.
        """
        self.log.info(
            "Waiting for block device behind FC host to stabilize..."
        )
        for elapsed in range(DISK_RESCAN_TIMEOUT_SECS):
            if os.path.exists(
                "/sys/class/block/%s" % self.disk_name
            ):
                self.log.info(
                    "Disk %s stabilized after %ds",
                    self.disk_name, elapsed
                )
                return True
            time.sleep(1)
        return False

    def _verify_post_recovery_health(self):
        """
        Audit post-recovery device operational state and run basic I/O
        read tests via sg_turs and dd.
        """
        dev_state_path = (
            "/sys/class/block/%s/device/state" % self.disk_name
        )
        if os.path.exists(dev_state_path):
            state = genio.read_file(dev_state_path).strip()
            self.log.info(
                "Client FC device operational state: %s", state
            )
            if state != "running":
                self.fail(
                    "Post-recovery device state is '%s', "
                    "expected 'running'" % state
                )

        rc = process.system(
            "sg_turs /dev/%s" % self.disk_name,
            ignore_status=True, shell=True
        )
        if rc != 0:
            self.log.warning(
                "sg_turs returned error code: %d. "
                "Falling back to read test...", rc
            )
            rc = process.system(
                "dd if=/dev/%s of=/dev/null bs=512 count=1"
                % self.disk_name,
                ignore_status=True, shell=True
            )

        if rc != 0:
            self.fail(
                "Target disk /dev/%s failed I/O accessibility checks "
                "post-recovery" % self.disk_name
            )

        self.log.info(
            "I/O accessibility checks on /dev/%s completed "
            "successfully", self.disk_name
        )

    # ------------------------------------------------------------------ #
    #  Teardown Helpers                                                   #
    # ------------------------------------------------------------------ #

    def _teardown_restore_vios_mapping(self):
        """
        Re-add the NPIV vfchost port mapping on VIOS if it was removed
        by the test but never restored (e.g. test failed between EEH
        injection and mkvdev -fcp). Checks live lsmap -npiv output rather
        than internal state flags, so it is safe to call even when setUp
        partially completed.
        """
        session = getattr(self, 'vios_session', None)
        if not session:
            return
        vfchost = getattr(self, 'vfchost', None)
        fcs = getattr(self, 'vios_fcs', None)
        if not vfchost or not fcs:
            return

        check_res = session.cmd(
            "ioscli lsmap -vadapter %s -npiv" % vfchost
        )
        if check_res.exit_status != 0:
            self.log.warning(
                "tearDown: could not query lsmap -npiv for %s; "
                "skipping mapping check", vfchost
            )
            return

        # If the vfchost appears in lsmap output with its fcs backing,
        # the NPIV port is active — no restore needed.
        if fcs in check_res.stdout_text:
            self.log.info(
                "tearDown: vfchost %s mapping to %s is intact — "
                "no action needed", vfchost, fcs
            )
            return

        self.log.warning(
            "tearDown: vfchost %s mapping missing — restoring NPIV "
            "port for next run", vfchost
        )
        restore_cmd = "ioscli mkvdev -fcp -vadapter %s" % vfchost
        restore_res = session.cmd(restore_cmd)
        if restore_res.exit_status == 0:
            self.log.info(
                "tearDown: NPIV mapping restored successfully (%s)",
                restore_res.stdout_text.strip()
            )
        else:
            self.log.error(
                "tearDown: failed to restore NPIV mapping for %s: %s",
                vfchost, restore_res.stderr_text.strip()
            )

    def _teardown_close_vios_session(self):
        """
        Cleanly terminate the VIOS SSH ControlMaster session and remove
        its socket file.
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

    def _log_vios_injection_errpt(self, adapter_dev):
        """
        Capture a snapshot of the VIOS AIX error report immediately after
        EEH injection. Logs the most recent errpt entries filtered to EEH,
        FC, and PCI hardware errors so injection evidence is preserved in
        the job log even if the LPAR monitor window times out.
        """
        # -a  full detail; -s restricts to entries after a timestamp but
        # AIX errpt does not support -n (last N lines). Pipe through head
        # to limit noise — the most recent entries appear first.
        snap_res = self._run_as_root(
            "errpt -a | head -200"
        )
        if snap_res.exit_status == 0 and snap_res.stdout_text.strip():
            self.log.info(
                "--- VIOS errpt snapshot post-injection (adapter %s) ---\n"
                "%s",
                adapter_dev, snap_res.stdout_text.strip()
            )
        else:
            self.log.warning(
                "errpt snapshot returned no output or failed (exit %d)",
                snap_res.exit_status
            )

        # Also log the raw fcs adapter state immediately after injection.
        fcs_res = self._run_as_root(
            "lsdev -Cl %s" % adapter_dev
        )
        self.log.info(
            "VIOS fcs adapter state post-injection: %s",
            fcs_res.stdout_text.strip()
        )

    def _log_vios_traces(self):
        """
        Retrieve and print VIOS logs and FC error traces for tearDown.
        """
        err_res = self.vios_session.cmd("errpt -a")
        if err_res.exit_status == 0:
            self.log.info(
                "--- VIOS AIX errpt (Error Report) Output ---"
            )
            self.log.info(err_res.stdout_text.strip())
        else:
            self.vios_session.cmd("ioscli errlog")

    # ------------------------------------------------------------------ #
    #  Teardown                                                           #
    # ------------------------------------------------------------------ #

    def tearDown(self):
        """
        Restore environment, capture forensic traces, and close all
        sessions. Guarantees VIOS NPIV vfchost mapping is restored if
        the test failed mid-injection, the VIOS SSH ControlMaster is
        exited and its socket removed, and client LPAR kernel warnings
        are captured for post-mortem.
        """
        self.log.info(
            "========= Starting vFC EEH Test tearDown ========="
        )

        self._teardown_restore_vios_mapping()

        if hasattr(self, 'vios_session') and self.vios_session:
            self._log_vios_traces()

        out = process.system_output(
            "dmesg -T --level=alert,crit,err,warn",
            ignore_status=True, shell=True
        )
        self.log.debug(
            "LPAR client kernel warnings/errors:\n%s",
            out.decode("utf-8", errors="replace").strip()
        )

        self._teardown_close_vios_session()

        self.log.info(
            "========= vFC EEH Test tearDown Complete ========="
        )
