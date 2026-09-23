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
backing adapter via NPIV lsmap, uses eeh_tool_64 Op 3 with -w 64 to inject
a recoverable EEH freeze via the 64-bit RTAS token 'ioa-bus-error-64',
monitors ibmvfc transport recovery on the client LPAR (Link Down, PLOGI,
PRLI, Power-on or device reset), and validates disk health after recovery.

Architecture: NPIV — VIOS exposes a vfchost port backed by a physical fcsX
HBA. Client sees FC LUNs via ibmvfc. VIOS mapping restore uses
'ioscli mkvdev -fcp -vadapter <vfchost>' (port-level virtual device).

See Readme.txt for detailed technical rationales on:
  - Why eeh_tool_64 with -w 64 is required (Power10 64-bit BAR address domain).
  - eeh_tool Op 3 recoverable function codes and why functions 14/15/18/19
    are excluded.
"""

import os
import re
import select
import struct
import subprocess
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

# eeh_tool_64 Op 3 function codes (see Readme.txt for technical details).
EEH_FUNC_MEM_LOAD_DATA = 1   # Load Memory Space Data parity / TLP ECRC
EEH_FUNC_IO_LOAD_DATA = 3    # Load I/O Space Data parity   / TLP ECRC
EEH_FUNC_ODM_DEFAULT = 1     # fallback when no address from Op 1


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
        self.iterations = self.params.get('iterations', default=1)

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

        # Read the ibmvfc command queue depth from sysfs so we know how
        # many concurrent O_DIRECT processes are needed to keep all HBA
        # queue slots occupied when the EEH freeze fires.
        # ibmvfc sets queue_depth per LUN; typical value is 16 on this
        # system. Falls back to 16 (ibmvfc default) if sysfs is absent.
        qd_path = (
            "/sys/class/block/%s/device/queue_depth"
            % os.path.basename(os.path.realpath(self.disk_input))
        )
        try:
            self.queue_depth = int(genio.read_file(qd_path).strip())
        except (OSError, ValueError):
            self.queue_depth = 16
        self.log.info(
            "Device queue depth for %s: %d (concurrent I/O processes "
            "needed to saturate ibmvfc queue)",
            self.disk_name, self.queue_depth
        )

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
        post-recovery I/O accessibility. Runs for a configurable number
        of iterations.
        """
        for iteration in range(1, self.iterations + 1):
            self.log.info(
                "========= Starting Iteration %d of %d =========",
                iteration, self.iterations
            )
            self.log.info("--- Initiating EEH Error Injection on VIOS ---")

            dmesg.clear_dmesg()

            # Pre-flight: resolve the inject command via SSH BEFORE starting
            # background I/O. All SSH round-trips (lsdev, eeh_tool_64 Op1,
            # test -x) happen here while the disk is idle so that only a
            # single SSH call (the RTAS inject) fires while I/O is active.
            self.log.info(
                "Pre-flight: resolving EEH inject command before starting "
                "background I/O (amortising SSH overhead)..."
            )
            inject_cmd = self._build_inject_cmd_preflight()

            # Start queue_depth concurrent O_DIRECT background dd processes.
            # Each process runs count=10000 reads x ~13ms = ~130s, guaranteeing
            # I/O is in-flight when RTAS fires.
            io_cmd = (
                "dd if=/dev/%s of=/dev/null bs=512 count=10000 iflag=direct"
                % self.disk_name
            )
            self.log.info(
                "Launching %d concurrent O_DIRECT dd processes on /dev/%s "
                "to fill ibmvfc queue depth %d before EEH injection...",
                self.queue_depth, self.disk_name, self.queue_depth
            )
            bg_procs = [
                subprocess.Popen(
                    io_cmd, shell=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                for _ in range(self.queue_depth)
            ]

            # Wait 500ms for processes to reach the HBA and fill the queue.
            time.sleep(0.5)

            # Fire the single pre-built RTAS inject command.
            self.log.info(
                "Firing EEH inject (eeh_tool_64 -w 64, single SSH call): %s",
                inject_cmd
            )
            inject_res = self._run_as_root(inject_cmd)
            self.log.info(
                "eeh_tool_64 Op 3 output:\n%s",
                inject_res.stdout_text.strip() or "<no output>"
            )
            if inject_res.stderr_text.strip():
                self.log.warning(
                    "eeh_tool_64 Op 3 stderr:\n%s",
                    inject_res.stderr_text.strip()
                )
            if inject_res.exit_status != 0:
                for proc in bg_procs:
                    proc.kill()
                    proc.wait()
                self.fail(
                    "eeh_tool_64 EEH injection failed (exit %d): %s"
                    % (inject_res.exit_status,
                       inject_res.stdout_text.strip())
                )

            # Wait for background processes to exit with I/O errors (expected
            # and fully handled when the freeze fires and the adapter resets).
            # The test case must never fail because of these in-flight errors.
            self.log.info(
                "Waiting for %d background I/O processes to exit after "
                "EEH freeze...", len(bg_procs)
            )
            exit_codes = []
            for proc in bg_procs:
                try:
                    proc.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                exit_codes.append(proc.returncode)
            self.log.info(
                "Background I/O exit codes: %s "
                "(non-zero and I/O errors expected when freeze fired)",
                exit_codes
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
                "vFC transport recovery confirmed — LPAR reconnected"
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
                "========= Iteration %d of %d Completed Successfully =========",
                iteration, self.iterations
            )

            # If there are more iterations to follow, recreate the SSH session
            # if needed and allow the disk to settle.
            if iteration < self.iterations:
                time.sleep(10)

        self.log.info(
            "vFC device recovered successfully across all %d iterations, test passed",
            self.iterations
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
        (e.g. 'host3'). Fallback: decimal ClntID matches LPAR partition
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

        # Primary match: VFC client name (e.g. 'host3') == self.fc_host.
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

        If eeh_tool_url is set and the binary is absent, downloads it
        using python3 urllib.request (wget/curl are absent on this VIOS).
        The URL is expected to serve the plain eeh_tool_64 binary directly.
        """
        if not self.eeh_tool_url:
            self.log.info(
                "eeh_tool_url not set — assuming eeh_tool_64 is already "
                "present at %s on VIOS", self.eeh_tool_path
            )
            return

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

        # python3 urllib.request via heredoc avoids ksh subshell quoting
        # issues that occur when using python3 -c "..." inline.
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
        Verify the fcsX device exists on VIOS via 'lsdev -Cl <fcs>' and
        return its name. Fails if the device is unavailable.
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
        Verify eeh_tool_64 is executable and EEH is enabled for
        adapter_dev using Op 1 (Query Slot Capabilities and Slot State).
        Fails the test with a clear message if slot_capabilities=0 or
        the tool cannot be executed.
        """
        self.log.info(
            "Checking eeh_tool_64 availability at %s on VIOS...",
            self.eeh_tool_path
        )
        avail_res = self._run_as_root(
            "test -x %s && echo AVAILABLE || echo MISSING"
            % self.eeh_tool_path
        )
        if "MISSING" in avail_res.stdout_text or \
                "AVAILABLE" not in avail_res.stdout_text:
            self.fail(
                "eeh_tool_64 not found or not executable at %s on "
                "VIOS %s. Place the 64-bit binary at that path and "
                "ensure it has execute permission."
                % (self.eeh_tool_path, self.vios_ip)
            )

        self.log.info(
            "Querying EEH slot capabilities for adapter %s "
            "via eeh_tool_64 Op 1...", adapter_dev
        )
        query_cmd = "%s %s 1" % (self.eeh_tool_path, adapter_dev)
        query_res = self._run_as_root(query_cmd)

        if query_res.exit_status == 255:
            self.fail(
                "eeh_tool_64 could not open the AIX machine device "
                "driver on VIOS %s (errno=13 / EACCES). The binary "
                "must run as root via oem_setup_env."
                % self.vios_ip
            )

        output = query_res.stdout_text
        self.log.info(
            "eeh_tool_64 Op 1 output for %s:\n%s", adapter_dev, output
        )

        # 32-bit eeh_tool prints "Slot capabilities: 1"
        # 64-bit eeh_tool_64 prints "slot_capabilities = 1"
        # Match both formats.
        cap_match = re.search(
            r'[Ss]lot\s+[Cc]apabilit(?:ies|y)\s*[=:]\s*(\d+)', output
        )
        if cap_match:
            slot_cap = int(cap_match.group(1))
            if slot_cap == 0:
                self.fail(
                    "EEH injection is not enabled: eeh_tool_64 reports "
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
                "Could not parse slot capabilities from eeh_tool_64 "
                "Op 1 output for %s. Proceeding with injection.",
                adapter_dev
            )

    def _get_eeh_bus_addresses(self, adapter_dev):
        """
        Retrieve PCI bus addresses for adapter_dev from the eeh_tool_64
        Op 1 header block. Returns (bus_mem_addr, bus_io_addr) as hex
        strings (e.g. '0x0000000080240000', '0x0') or (None, None).

        See Readme.txt for details on Op 5 and multi-BAR capturing.
        """
        self.log.info(
            "Querying PCI bus addresses for %s from eeh_tool_64 Op 1 "
            "header...", adapter_dev
        )
        info_cmd = "%s %s 1" % (self.eeh_tool_path, adapter_dev)
        info_res = self._run_as_root(info_cmd)

        if info_res.exit_status == 255:
            self.log.warning(
                "eeh_tool_64 Op 1 returned exit 255 for %s — "
                "machine DD open failed; will use ODM defaults for "
                "address/mask in Op 3.", adapter_dev
            )
            return None, None

        output = info_res.stdout_text
        self.log.info(
            "eeh_tool_64 Op 1 header output for %s:\n%s",
            adapter_dev, output
        )

        mem_match = re.search(
            r'Bus\s+mem\s+addr\s*:\s*(0x[0-9a-fA-F]+)', output
        )
        io_match = re.search(
            r'Bus\s+IO\s+addr\s*:\s*(0x[0-9a-fA-F]+)', output
        )

        bus_mem_addr = mem_match.group(1) if mem_match else None
        bus_io_addr = io_match.group(1) if io_match else None

        if bus_io_addr == '0x0':
            bus_io_addr = None

        self.log.info(
            "Parsed bus addresses from Op 1 header — mem: %s  io: %s",
            bus_mem_addr if bus_mem_addr else "<not found>",
            bus_io_addr if bus_io_addr else "<not applicable>"
        )
        return bus_mem_addr, bus_io_addr

    def _build_eeh_inject_cmd(self, adapter_dev, bus_mem_addr,
                              bus_io_addr):
        """
        Construct the eeh_tool_64 Op 3 command string with -w 64.
        See Readme.txt for technical rationale on -w 64 and BAR addresses.
        """
        mask = "0x0fffffff"

        mem_val = int(bus_mem_addr, 16) if bus_mem_addr else 0
        io_val = int(bus_io_addr, 16) if bus_io_addr else 0

        if mem_val != 0:
            cmd = (
                "%s %s 3 %d -a %s -m %s -w 64"
                % (self.eeh_tool_path, adapter_dev,
                   EEH_FUNC_MEM_LOAD_DATA, bus_mem_addr, mask)
            )
            self.log.info(
                "EEH inject command (BAR0 64-bit mem addr %s, func %d "
                "-w 64 — Load Memory Data parity / TLP ECRC): %s",
                bus_mem_addr, EEH_FUNC_MEM_LOAD_DATA, cmd
            )
        elif io_val != 0:
            cmd = (
                "%s %s 3 %d -a %s -m %s -w 64"
                % (self.eeh_tool_path, adapter_dev,
                   EEH_FUNC_IO_LOAD_DATA, bus_io_addr, mask)
            )
            self.log.info(
                "EEH inject command (I/O addr %s, func %d -w 64): %s",
                bus_io_addr, EEH_FUNC_IO_LOAD_DATA, cmd
            )
        else:
            cmd = (
                "%s %s 3 %d -w 64"
                % (self.eeh_tool_path, adapter_dev, EEH_FUNC_ODM_DEFAULT)
            )
            self.log.info(
                "EEH inject command (ODM default addr, func %d -w 64): "
                "%s", EEH_FUNC_ODM_DEFAULT, cmd
            )

        return cmd

    def _build_inject_cmd_preflight(self):
        """
        Resolve the eeh_tool_64 Op 3 command string via SSH before
        background I/O starts. All pre-injection SSH round-trips (lsdev,
        Op 1 slot check, address query) happen here so that the actual
        inject step is a single SSH call while I/O is in-flight.
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
            "Pre-flight complete — inject command ready: %s", inject_cmd
        )
        return inject_cmd

    def _restore_eeh_on_vios(self):
        """
        Restore the NPIV virtual FC port mapping on VIOS to allow client
        LPAR recovery. 'mkvdev -fcp' re-enables the NPIV virtual FC port
        on the VIOS so the client can re-login via PLOGI/PRLI.
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
        initiates recovery. ibmvfc signals disruption via Link Down events,
        adapter reset messages, and I/O command cancels. Uses /dev/kmsg
        event-driven detection.
        """
        disruption_signals = [
            'Link Down',
            'ibmvfc',
            'adapter reset',
            'LOGO',
            'link down',
            'I/O error',
            'transport',
            'transaction cancelled',
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
        select(). ibmvfc signals recovery through Link Up events,
        PLOGI/PRLI completion, 'Re-enabling adapter', or target discovery
        messages. All known recovery strings across ibmvfc driver versions
        are checked.
        """
        recovery_signals = [
            'Link Up',
            'Re-enabling adapter',
            'ibmvfc: Target',
            'PLOGI',
            'PRLI',
            'Power-on or device reset',
        ]
        failure_signals = ['error after reset']
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

    def _log_vios_traces(self):
        """
        Retrieve and print VIOS logs and FC error traces for tearDown.
        Uses ioscli errlog (available in padmin rksh; errpt requires root
        via oem_setup_env and is not available in non-interactive context).
        """
        err_res = self.vios_session.cmd("ioscli errlog")
        if err_res.exit_status == 0 and err_res.stdout_text.strip():
            self.log.info(
                "--- VIOS ioscli errlog ---\n%s",
                err_res.stdout_text.strip()
            )
        else:
            self.log.debug(
                "ioscli errlog returned no output (exit %d)",
                err_res.exit_status
            )

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
