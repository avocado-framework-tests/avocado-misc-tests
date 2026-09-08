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
# Author: Maram S Murthy <msmurthy@linux.ibm.com>

"""
VIOS-Level EEH Error Injection and Recovery Test for vSCSI (ibmvscsi) adapters on
IBM PowerVM LPAR.

This test connects to the VIOS managing the client LPAR, correlates the target
virtual SCSI disk (e.g., /dev/sda) with its underlying physical backing hdisk
on the VIOS, triggers physical EEH error injection on the VIOS, monitors
the LPAR client for SCSI transport recovery traces, and validates the health
and accessibility of the virtual disk after recovery.
"""

import os
import re
import select
import time

from avocado import Test
from avocado.utils import dmesg
from avocado.utils import distro
from avocado.utils import genio
from avocado.utils import process
from avocado.utils import wait
from avocado.utils.ssh import Session
from avocado.utils.software_manager.manager import SoftwareManager

# Timeout constants — expressed as wall-clock deadlines.
# RECOVERY_TIMEOUT_SECS: after the VIOS session is closed and the 60s
# quiesce completes, the client ibmvscsi driver completes SRP re-login
# within ~200s on this VIOS/LPAR hardware (vs 650s without the quiesce).
# 300s gives a safe margin above the observed 202s maximum.
# Detection is event-driven (/dev/kmsg select) — no polling step to miss.
RECOVERY_TIMEOUT_SECS = 300
DISK_RESCAN_TIMEOUT_SECS = 60
INJECT_CONFIRM_SECS = 30


class EEHVscsi(Test):
    """
    VIOS-Level EEH Error Injection and Recovery test for vSCSI devices.
    """

    def setUp(self):
        """
        Validate environments, load YAML inputs, connect to the VIOS,
        and map the client virtual disk to the underlying physical VIOS hdisk.
        """
        self.log.info("========= Starting vSCSI EEH Test Setup =========")

        # 1. Architecture guard (Retained for sanity)
        if 'ppc' not in distro.detect().arch:
            self.cancel("This test requires a ppc64/ppc64le architecture")

        # 2. PowerVM LPAR only (Retained for sanity)
        if 'PowerNV' in genio.read_file("/proc/cpuinfo").strip():
            self.cancel("This test targets PowerVM LPAR, not bare-metal PowerNV")

        # 3. Load YAML parameters
        self.disk_input = self.params.get('disk', default='/dev/sda')
        self.vios_ip = self.params.get('vios_ip', default='')
        self.vios_username = self.params.get('vios_username', default='padmin')
        self.vios_pwd = self.params.get('vios_pwd', default='')
        self.vios_key = self.params.get('vios_key', default='')
        self.eeh_tool = self.params.get('eeh_tool', default='eeh_tool_64')
        self.errinjct_cmd = self.params.get('errinjct_cmd', default='')

        if not self.vios_ip:
            self.cancel("vios_ip parameter is required in the YAML configuration")

        # 4. Connect to VIOS SSH via Session
        self.vios_session = Session(
            self.vios_ip,
            user=self.vios_username,
            password=self.vios_pwd,
            key=self.vios_key if self.vios_key else None
        )
        self.vios_session.cleanup_master()
        self.log.info("Connecting to VIOS at %s...", self.vios_ip)
        if not wait.wait_for(self.vios_session.connect, timeout=30):
            self.cancel(f"Failed to establish SSH connection to VIOS at {self.vios_ip}")
        self.log.info("Connected to VIOS successfully")

        # 5. Resolve client disk and real path
        if not os.path.exists(self.disk_input):
            self.cancel(f"Target disk input {self.disk_input} does not exist on client LPAR")
        self.disk_name = os.path.basename(os.path.realpath(self.disk_input))
        self.log.info("Resolved client disk name: %s", self.disk_name)

        # Resolve the scsi_host number for this disk (used to anchor dmesg recovery signals)
        self.scsi_host = self._get_scsi_host_for_disk()
        self.log.info("Resolved SCSI host for %s: %s", self.disk_name, self.scsi_host)

        # 6. Resolve client virtual slot number (for debugging and fallback reference)
        self.slot = self._get_client_slot()
        if self.slot:
            self.log.info("Resolved client Virtual SCSI Slot: %s", self.slot)
        else:
            self.log.warning("Could not resolve client Virtual SCSI Slot via standard location mappings")

        # 7. Resolve client Inquiry ID
        self.inquiry_id = self._get_client_inquiry_id()
        if not self.inquiry_id:
            self.fail(f"Failed to resolve SCSI Inquiry identifier for device {self.disk_name}")
        self.log.info("Resolved client SCSI Inquiry ID: %s", self.inquiry_id)

        # 8. Unified, bulletproof auto-discovery of vhost adapter and backing hdisk on VIOS
        self._discover_vios_devices()

        # 9. Log backing hdisk state on VIOS
        self._log_vios_hdisk_state()

        # 11. Ensure sg3_utils is available on LPAR client for health check
        smm = SoftwareManager()
        if not smm.check_installed('sg3_utils') and not smm.install('sg3_utils'):
            self.cancel("Required package 'sg3_utils' could not be installed on client LPAR")

        self.log.info("========= vSCSI EEH Test Setup Complete =========")

    def test_eeh_vscsi(self):
        """
        Execute the physical error injection on the VIOS backing hdisk,
        verify that transport reset recovery initiates and succeeds on LPAR,
        and confirm target device health and post-recovery I/O accessibility.
        """
        self.log.info("--- Initiating EEH Error Injection on VIOS ---")

        # 1. Clear dmesg on client LPAR.
        # dmesg is fully cleared here, so _read_new_dmesg() reads only messages
        # produced during this test run — no --since anchoring needed.
        dmesg.clear_dmesg()

        # 2. Trigger Disconnection / Error Injection on VIOS
        self._inject_eeh_on_vios()

        # 3. Actively trigger I/O on LPAR client to force SCSI layer to detect the absent disk immediately
        self.log.info("Triggering active I/O read on client LPAR to force SCSI transport detection...")
        process.run(f"dd if=/dev/{self.disk_name} of=/dev/null bs=512 count=1", ignore_status=True, shell=True, timeout=5)

        # 4. Monitor LPAR client logs for reset or disruption initiation
        self.log.info("Monitoring client logs for reset/recovery warnings...")
        if not self._check_reset_started():
            self.log.warning("LPAR driver did not register reset warning in dmesg immediately, proceeding to recovery")

        # 5. Restore the virtual mapping on VIOS
        self._restore_eeh_on_vios()

        # 6. Terminate the VIOS SSH session and quiesce for 60 seconds.
        #
        # Root cause of escalating recovery times across runs:
        # The VIOS ibmvscsi server adapter keeps the CRQ session bound to the
        # client partition for as long as the padmin SSH session (and its
        # associated VIOS process context) remains open.  While our session
        # stays alive, the VIOS treats the transport endpoint as still in use
        # and will not fully release it.  When the client tries to reconnect
        # it must wait for the old CRQ session to time out (init_timeout=300s,
        # up to two cycles = 600s) before a fresh login is accepted.
        #
        # Fix: close the session immediately after mkvdev confirms the VTD is
        # Available, then wait 60 seconds for the VIOS to fully release and
        # garbage-collect the old CRQ endpoint.  The client ibmvscsi driver
        # will then receive a clean Transport Event and complete SRP re-login
        # in seconds rather than minutes.  We reconnect afterwards only to
        # collect traces in tearDown.
        self._close_vios_session_for_crq_release()

        # 7. Wait for driver recovery: Power-on/device-reset or SRP_LOGIN
        self.log.info("Waiting for client LPAR transport recovery...")
        if not self._check_srp_login_recovered():
            self.fail("vSCSI adapter SRP login recovery timed out or failed "
                      f"within {RECOVERY_TIMEOUT_SECS}s")

        self.log.info("vSCSI transport recovery confirmed - LPAR reconnected")

        # 8. Wait for the block device node to reappear on LPAR
        if not self._wait_for_disk_reappear():
            self.fail(f"Disk {self.disk_name} did not reappear on the LPAR "
                      f"within {DISK_RESCAN_TIMEOUT_SECS}s after transport recovery")

        # 9. Verify device health and accessibility after recovery
        self.log.info("Performing final post-recovery health audit...")
        self._verify_post_recovery_health()

        self.log.info("vSCSI device recovered successfully, test passed")

    def tearDown(self):
        """
        Restore environment, capture forensic traces, and close all sessions.

        Guarantees:
        - VIOS virtual mapping is restored if the test failed mid-injection.
        - VIOS SSH ControlMaster process is exited and its socket file removed.
        - Client LPAR kernel warnings are captured for post-mortem inspection.
        - No duplicate VIOS log output (traces are only dumped once here, not
          repeated from test_eeh_vscsi which calls _log_vios_traces mid-run).
        """
        self.log.info("========= Starting vSCSI EEH Test tearDown =========")

        # 1. Safety-restore the VIOS virtual mapping if the test failed after
        #    rmvdev but before mkvdev completed successfully.  Without this the
        #    disk stays offline between test runs, causing the next run to fail
        #    at setUp with a missing backing device.
        self._teardown_restore_vios_mapping()

        # 2. Capture VIOS AIX error log (session must still be open at this point)
        if hasattr(self, 'vios_session') and self.vios_session:
            self._log_vios_traces()

        # 3. Capture client LPAR kernel warnings/errors for post-mortem
        out = process.system_output(
            "dmesg -T --level=alert,crit,err,warn",
            ignore_status=True, shell=True
        )
        self.log.debug(
            "LPAR client kernel warnings/errors:\n%s",
            out.decode("utf-8", errors="replace").strip()
        )

        # 4. Close the VIOS SSH session cleanly:
        #    - send ControlMaster "-O exit" to terminate the master process
        #    - call cleanup_master() to remove the socket file regardless of
        #      whether quit() succeeded (prevents stale sockets on next run)
        self._teardown_close_vios_session()

        self.log.info("========= vSCSI EEH Test tearDown Complete =========")

    # ------------------------------------------------------------------ #
    #  Teardown Helpers                                                  #
    # ------------------------------------------------------------------ #

    def _teardown_restore_vios_mapping(self):
        """
        Re-add the virtual device mapping on VIOS if it was removed by the test
        but never restored (e.g. test failed between rmvdev and mkvdev).

        Checks the live VIOS lsmap output rather than relying on internal state
        flags so it is safe to call even when setUp partially completed.
        """
        session = getattr(self, 'vios_session', None)
        if not session:
            return
        vhost = getattr(self, 'vhost', None)
        hdisk = getattr(self, 'vios_hdisk', None)
        vtd = getattr(self, 'vtd', None)
        if not all([vhost, hdisk, vtd]):
            return

        # Query current mapping state on the VIOS
        check_res = session.cmd(f"ioscli lsmap -vadapter {vhost}")
        if check_res.exit_status != 0:
            self.log.warning(
                "tearDown: could not query lsmap for %s; skipping mapping check",
                vhost
            )
            return

        if vtd in check_res.stdout_text:
            # VTD is present and mapping is live.
            # The VIOS session close + quiesce in _close_vios_session_for_crq_release()
            # already handled state cleanup during the test run.  No further
            # action needed — a redundant rmvdev/mkvdev here would trigger a
            # second Transport Event on the client, causing a spurious recovery
            # signal after the kmsg watcher has already exited.
            self.log.info(
                "tearDown: VTD %s present on %s — mapping intact, no action needed",
                vtd, vhost
            )
            return

        # VTD is absent — test failed between rmvdev and mkvdev; restore it
        # so the disk is back online and the next run starts cleanly.
        self.log.warning(
            "tearDown: VTD %s missing from %s — restoring mapping for next run",
            vtd, vhost
        )
        restore_cmd = (
            f"ioscli mkvdev -vdev {hdisk} -vadapter {vhost} -dev {vtd}"
        )
        restore_res = session.cmd(restore_cmd)
        if restore_res.exit_status == 0:
            self.log.info(
                "tearDown: mapping restored successfully (%s)",
                restore_res.stdout_text.strip()
            )
        else:
            self.log.error(
                "tearDown: failed to restore mapping %s: %s",
                vtd, restore_res.stderr_text.strip()
            )

    def _teardown_close_vios_session(self):
        """
        Cleanly terminate the VIOS SSH ControlMaster session and remove its
        socket file.

        quit() sends '-O exit' to the master process so it terminates
        gracefully.  cleanup_master() then removes the socket file from
        ~/.ssh/avocado-master-*.  Both are called unconditionally so that a
        failed quit() (e.g. master already dead) still cleans up the socket,
        preventing a stale-socket error on the next test run.
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

        # Always remove the socket file regardless of quit() result
        try:
            session.cleanup_master()
            self.log.info("VIOS SSH ControlMaster socket file removed")
        except OSError as exc:
            # Socket file already gone — not an error
            self.log.debug(
                "cleanup_master: socket file not found (%s)", exc
            )

        self.vios_session = None

    # ------------------------------------------------------------------ #
    #  Helper Methods                                                    #
    # ------------------------------------------------------------------ #

    def _get_client_slot(self):
        """
        Robustly resolve the virtual slot number of the client SCSI device.
        Supports both modern location codes (-C<slot>) and legacy H<host> codes.
        """
        # First, try to resolve via the sysfs device link (highly robust, no cmd dependency)
        dev_path = f"/sys/block/{self.disk_name}/device"
        if os.path.exists(dev_path):
            real_path = os.path.realpath(dev_path)
            # real_path looks like: /sys/devices/vio/30000005/host5/...
            match = re.search(r'/vio/([0-9a-fA-F]+)/', real_path)
            if match:
                unit_addr_str = match.group(1)
                try:
                    unit_addr = int(unit_addr_str, 16)
                    # Slot is the lower 28 bits of the unit address (standard PowerVM mapping)
                    slot = str(unit_addr & 0x0FFFFFFF)
                    self.log.info("Resolved slot %s from VIO unit address %s via sysfs realpath", slot, unit_addr_str)
                    return slot
                except ValueError:
                    pass

        # Second, try lscfg parsing
        cmd = f"lscfg -l {self.disk_name}"
        res = process.run(cmd, ignore_status=True, shell=True)
        if res.exit_status == 0:
            output = res.stdout.decode("utf-8").strip()
            for line in output.splitlines():
                if self.disk_name in line:
                    parts = line.split()
                    if len(parts) >= 2:
                        loc_code = parts[1]
                        # Look for -C<slot>
                        match_c = re.search(r'-C(\d+)', loc_code)
                        if match_c:
                            return match_c.group(1)
                        # Look for H<host>-B<bus>-...
                        match_h = re.search(r'H(\d+)', loc_code)
                        if match_h:
                            host_num = match_h.group(1)
                            # Find the scsi_host link to map back to the VIO unit address
                            host_link = f"/sys/class/scsi_host/host{host_num}"
                            if os.path.exists(host_link):
                                try:
                                    target = os.readlink(host_link)
                                    match_vio = re.search(r'/vio/([0-9a-fA-F]+)/', target)
                                    if match_vio:
                                        unit_addr = int(match_vio.group(1), 16)
                                        slot = str(unit_addr & 0x0FFFFFFF)
                                        self.log.info("Resolved slot %s from legacy location H%s", slot, host_num)
                                        return slot
                                except Exception:
                                    pass
        return None

    def _get_client_inquiry_id(self):
        """
        Retrieve the unique SCSI Inquiry identifier for the client disk.
        """
        inquiry_paths = [
            f"/sys/block/{self.disk_name}/device/inquiry",
            f"/sys/class/block/{self.disk_name}/device/inquiry"
        ]
        for path in inquiry_paths:
            if os.path.exists(path):
                try:
                    # Inquiry files contain raw binary SCSI data which cannot be read as plain UTF-8 text
                    with open(path, "rb") as f:
                        raw_data = f.read()
                    data = raw_data.decode("utf-8", errors="ignore").strip()
                    # Strip any non-printable chars or binary markers
                    clean_id = re.sub(r'[\x00-\x1f\x7f-\xff]', '', data)
                    # Extract the serial component (usually at the end of the inquiry string)
                    parts = clean_id.split()
                    if len(parts) >= 3:
                        # Extract and return the device serial/VDASD ID
                        return parts[-1]
                    elif len(clean_id) > 8:
                        return clean_id[-8:]
                    return clean_id
                except (OSError, UnicodeDecodeError):
                    continue

        # Fallback to lsscsi -vl parsing if sysfs attributes are protected
        res = process.run("lsscsi -vl", ignore_status=True, shell=True)
        if res.exit_status == 0:
            output = res.stdout.decode("utf-8")
            # Extract the device directory and read inquiry
            match = re.search(rf"\[\d+:\d+:\d+:\d+\].*{self.disk_name}", output)
            if match:
                for line in output.splitlines():
                    if "dir" in line and self.disk_name in line:
                        dir_path = line.split()[-1].strip("[]")
                        inquiry_file = os.path.join(dir_path, "inquiry")
                        if os.path.exists(inquiry_file):
                            try:
                                return genio.read_file(inquiry_file).split()[2].strip(b'0001').decode("utf-8")
                            except Exception:
                                pass
        return None

    def _discover_vios_devices(self):
        """
        Unified, bulletproof auto-discovery of vhost adapter and backing hdisk
        on the VIOS using LPAR partition ID and disk Inquiry ID.
        """
        # 1. Resolve client LPAR partition ID and name from device-tree
        lpar_id_hex = None
        lpar_name = None

        part_no_path = "/proc/device-tree/ibm,partition-no"
        if os.path.exists(part_no_path):
            try:
                with open(part_no_path, "rb") as f:
                    part_no_bytes = f.read()
                import struct
                partition_id = struct.unpack(">I", part_no_bytes)[0]
                lpar_id_hex = f"0x{partition_id:08x}"
                self.log.info("Resolved LPAR Partition ID: %d (%s)", partition_id, lpar_id_hex)
            except Exception as e:
                self.log.debug("Failed to read partition-no from device-tree: %s", e)

        part_name_path = "/proc/device-tree/ibm,partition-name"
        if os.path.exists(part_name_path):
            try:
                with open(part_name_path, "r", encoding="utf-8") as f:
                    lpar_name = f.read().strip("\x00 \n\r")
                self.log.info("Resolved LPAR Partition Name: %s", lpar_name)
            except Exception as e:
                self.log.debug("Failed to read partition-name from device-tree: %s", e)

        # 2. Query lsmap -all on VIOS
        self.log.info("Querying lsmap -all on VIOS to parse mappings...")
        res = self.vios_session.cmd("ioscli lsmap -all")
        if res.exit_status != 0:
            self.fail(f"Failed to execute 'ioscli lsmap -all' on VIOS: {res.stderr_text}")

        # Parse the lsmap -all output into structured sections
        # We group by SVSA vhost adapter.
        vhosts_data = {}
        current_vhost = None
        current_client_id = None

        for line in res.stdout_text.splitlines():
            line_str = line.strip()
            if not line_str:
                continue

            # Detect SVSA header line, e.g.:
            # vhost0          U78C9.001.WSD0107-V2-C11                     0x00000005
            if line_str.startswith("vhost") or (len(line_str.split()) > 0 and line_str.split()[0].startswith("vhost")):
                parts = line_str.split()
                current_vhost = parts[0]
                current_client_id = parts[-1] if len(parts) >= 3 else None
                vhosts_data[current_vhost] = {
                    "client_id": current_client_id,
                    "devices": []
                }
                continue

            # Parse Virtual Target Devices (VTD) within the current vhost section
            if "VTD" in line_str:
                vtd_name = line_str.split()[-1]
                # We'll expect a "Backing device" line next or soon
                vhosts_data[current_vhost]["devices"].append({"vtd": vtd_name, "hdisk": None})
            elif "Backing device" in line_str and current_vhost and vhosts_data[current_vhost]["devices"]:
                backing_dev = line_str.split()[-1]
                vhosts_data[current_vhost]["devices"][-1]["hdisk"] = backing_dev

        self.log.debug("Parsed VIOS vhost mappings: %s", vhosts_data)

        # 3. Clean and prepare Inquiry ID core for matching
        # remove suffix (like .4 or partition numbers) and non-hex/non-alphanumeric noise
        inq_core = self.inquiry_id.split('.')[0]
        # Keep only alphanumeric characters to make matching highly resilient
        inq_core_clean = re.sub(r'[^a-zA-Z0-9]', '', inq_core).lower()
        self.log.info("Resilient core Inquiry ID for matching: %s", inq_core_clean)

        # 4. Iterate and find the exact vhost and hdisk mapping
        matched_vhost = None
        matched_hdisk = None

        for vhost, data in vhosts_data.items():
            client_id = data["client_id"]

            # If we resolved the LPAR partition ID, skip vhosts that don't match our partition ID
            if lpar_id_hex and client_id:
                try:
                    # Parse client IDs to integers for robust comparison (e.g. 0x05 vs 0x5 vs 5)
                    v_id = int(client_id, 16)
                    l_id = int(lpar_id_hex, 16)
                    if v_id != l_id:
                        self.log.debug("Skipping vhost %s (client_id %s != LPAR %s)", vhost, client_id, lpar_id_hex)
                        continue
                except ValueError:
                    pass

            # Now search through the backing devices of this candidate vhost
            for dev_info in data["devices"]:
                hdisk = dev_info["hdisk"]
                if not hdisk:
                    continue

                # Retrieve the candidate hdisk's attributes/unique_id to match with our Inquiry ID
                self.log.info("Checking candidate backing device %s on vhost %s...", hdisk, vhost)
                attr_cmd = f"ioscli lsdev -dev {hdisk} -attr"
                attr_res = self.vios_session.cmd(attr_cmd)

                # Check for match in attributes (lowercase and cleaned comparison)
                attr_text_clean = re.sub(r'[^a-zA-Z0-9]', '', attr_res.stdout_text).lower()

                if inq_core_clean in attr_text_clean:
                    self.log.info("Found exact backing hdisk match! dev: %s, vhost: %s, VTD: %s", hdisk, vhost, dev_info["vtd"])
                    matched_vhost = vhost
                    matched_hdisk = hdisk
                    matched_vtd = dev_info["vtd"]
                    break

                # If attr check failed, run lsattr check as fallback (no oem_setup_env to avoid interactive hangs)
                lsattr_cmd = f"/usr/sbin/lsattr -El {hdisk}"
                lsattr_res = self.vios_session.cmd(lsattr_cmd)
                lsattr_clean = re.sub(r'[^a-zA-Z0-9]', '', lsattr_res.stdout_text).lower()
                if inq_core_clean in lsattr_clean:
                    self.log.info("Found exact backing hdisk match via lsattr! dev: %s, vhost: %s, VTD: %s", hdisk, vhost, dev_info["vtd"])
                    matched_vhost = vhost
                    matched_hdisk = hdisk
                    matched_vtd = dev_info["vtd"]
                    break

            if matched_hdisk:
                break

        # 5. Ultimate fallback: if matching via Inquiry ID failed, but we have exactly one vhost
        # matching our LPAR partition ID, we can use the hdisk mapped there.
        if not matched_hdisk and lpar_id_hex:
            self.log.warning("Inquiry ID matching failed. Searching fallback via partition ID %s...", lpar_id_hex)
            for vhost, data in vhosts_data.items():
                client_id = data["client_id"]
                if client_id:
                    try:
                        if int(client_id, 16) == int(lpar_id_hex, 16):
                            if data["devices"]:
                                matched_vhost = vhost
                                matched_hdisk = data["devices"][0]["hdisk"]
                                matched_vtd = data["devices"][0]["vtd"]
                                self.log.warning("Fallback matched first device %s (VTD: %s) on vhost %s", matched_hdisk, matched_vtd, matched_vhost)
                                break
                    except ValueError:
                        pass

        # 6. Set instance variables or fail
        if not matched_hdisk:
            self.fail(f"Failed to find physical backing hdisk on VIOS matching disk {self.disk_name} "
                      f"and Inquiry ID {self.inquiry_id}")

        self.vhost = matched_vhost
        self.vios_hdisk = matched_hdisk
        self.vtd = matched_vtd

    def _log_vios_hdisk_state(self):
        """
        Retrieve and log the health and configuration status of the backing hdisk on VIOS.
        This is recorded for informational purposes and will not fail setUp.
        """
        cmd = f"ioscli lsdev -dev {self.vios_hdisk}"
        res = self.vios_session.cmd(cmd)
        if res.exit_status == 0:
            self.log.info("VIOS Backing Device Status details:\n%s", res.stdout_text.strip())
        else:
            self.log.warning("Could not retrieve VIOS status for %s", self.vios_hdisk)

    def _run_as_root(self, cmd):
        """
        Execute an AIX command as root on the VIOS by piping it into oem_setup_env.
        This prevents interactive terminal hangs and bypasses restricted shell (rksh) blocks.
        """
        escaped_cmd = cmd.replace('"', '\\"')
        pipe_cmd = f'echo "{escaped_cmd}" | oem_setup_env'
        return self.vios_session.cmd(pipe_cmd)

    def _inject_eeh_on_vios(self):
        """
        Trigger the physical hardware error injection on the VIOS targeting the backing hdisk parent.
        """
        if self.errinjct_cmd:
            self.log.info("Executing custom error injection command as root: %s", self.errinjct_cmd)
            res = self._run_as_root(self.errinjct_cmd)
            if res.exit_status != 0:
                self.fail(f"Failed to inject custom error on VIOS: {res.stderr_text}")
            return

        # Fetch physical location (Physloc) of the hdisk to identify the physical slot/PHB
        physloc = ""
        lsmap_cmd = f"ioscli lsmap -vadapter {self.vhost}"
        lsmap_res = self.vios_session.cmd(lsmap_cmd)
        if lsmap_res.exit_status == 0:
            lines = lsmap_res.stdout_text.splitlines()
            for idx, line in enumerate(lines):
                if self.vios_hdisk in line or (idx > 0 and self.vios_hdisk in lines[idx-1]):
                    # Look for Physloc nearby
                    for j in range(max(0, idx-5), min(len(lines), idx+5)):
                        if "Physloc" in lines[j]:
                            candidate = lines[j].split()[-1]
                            # Bug 2 fix: guard against capturing the column header word
                            # when the Physloc value is blank (e.g. "Physloc   <empty>").
                            if candidate.lower() != "physloc":
                                physloc = candidate
                            break
                    if physloc:
                        break

        self.log.info("Resolved physical location (Physloc) of backing hdisk: %s",
                      physloc if physloc else "<not available>")

        # Extract parent adapter (e.g. fscsi0, sas0) - executed as root via pipe
        parent_dev = ""
        parent_res = self._run_as_root(f"lsdev -Cl {self.vios_hdisk} -F parent")
        if parent_res.exit_status == 0:
            parent_dev = parent_res.stdout_text.strip()
            self.log.info("Resolved backing device parent adapter on VIOS: %s", parent_dev)

        # Standard physical error injection via VIOS errinjct
        if parent_dev:
            # Check if errinjct command is present on VIOS
            check_inj = self._run_as_root("which errinjct")
            if check_inj.exit_status == 0:
                # Target the parent adapter (PCI slot)
                self.log.info("Injecting EEH error on VIOS backing parent adapter: %s", parent_dev)
                inject_cmd = f"errinjct eeh -p {parent_dev} -s 1"
                inject_res = self._run_as_root(inject_cmd)
                if inject_res.exit_status == 0:
                    self.log.info("errinjct completed successfully")
                    return
                else:
                    self.log.warning("errinjct returned non-zero: %s. Trying fallback mapping reset...", inject_res.stderr_text)

        # Fallback to simulated mapping teardown on VIOS to trigger client transport event.
        # Removing the virtual device mapping via rmvdev instantly signals transport event/CRQ teardown to client.
        self.log.info("Triggering simulated transport reset via VIOS virtual mapping teardown")
        rm_cmd = f"ioscli rmvdev -vtd {self.vtd}"

        self.log.info("Removing virtual device mapping: %s", rm_cmd)
        rm_res = self.vios_session.cmd(rm_cmd)
        if rm_res.exit_status != 0:
            self.log.warning("rmvdev failed: %s. Trying fallback remove by backing device...", rm_res.stderr_text)
            self.vios_session.cmd(f"ioscli rmvdev -vdev {self.vios_hdisk}")
        self.log.info("Disconnection injection phase completed successfully")

    def _restore_eeh_on_vios(self):
        """
        Restore the virtual device mapping on VIOS to allow client LPAR recovery.
        """
        self.log.info("--- Restoring VIOS virtual device mapping and initiating recovery ---")
        add_cmd = f"ioscli mkvdev -vdev {self.vios_hdisk} -vadapter {self.vhost} -dev {self.vtd}"
        self.log.info("Restoring virtual device mapping: %s", add_cmd)
        add_res = self.vios_session.cmd(add_cmd)
        if add_res.exit_status != 0:
            self.log.error("mkvdev failed to restore virtual mapping: %s", add_res.stderr_text)
        self.log.info("Reconnection restoration phase completed successfully")

    def _close_vios_session_for_crq_release(self):
        """
        Close the VIOS SSH session immediately after mkvdev, then wait 60
        seconds before returning.

        While the padmin SSH session stays open, the VIOS ibmvscsi server
        adapter keeps the CRQ session bound to this client partition.  The
        client cannot complete SRP re-login until the VIOS fully releases the
        old CRQ endpoint — which only happens after the session is gone and
        the VIOS has had time to GC its transport state (observed ~30-60s).

        After the quiesce we reconnect the session so tearDown can still
        use it for lsmap checks and errlog collection.
        """
        VIOS_CRQ_RELEASE_WAIT_SECS = 60

        self.log.info(
            "Closing VIOS session to release CRQ endpoint — "
            "quiescing %ds for VIOS to GC transport state...",
            VIOS_CRQ_RELEASE_WAIT_SECS
        )
        # Close: send -O exit and remove the socket file
        self.vios_session.quit()
        try:
            self.vios_session.cleanup_master()
        except OSError:
            pass

        # Wait for the VIOS to fully release the CRQ session
        time.sleep(VIOS_CRQ_RELEASE_WAIT_SECS)

        # Reconnect so tearDown helpers (_teardown_restore_vios_mapping,
        # _log_vios_traces) can still use the session
        self.log.info("Reconnecting to VIOS at %s after quiesce...", self.vios_ip)
        self.vios_session = Session(
            self.vios_ip,
            user=self.vios_username,
            password=self.vios_pwd,
            key=self.vios_key if self.vios_key else None
        )
        if not wait.wait_for(self.vios_session.connect, timeout=30):
            self.log.warning(
                "VIOS reconnect after quiesce failed — "
                "tearDown will skip VIOS operations"
            )
            self.vios_session = None
        else:
            self.log.info("VIOS session re-established after quiesce")

    def _kick_ibmvscsi_reconnect(self):
        """
        Actively trigger CRQ/SRP re-login on the LPAR ibmvscsi adapter.

        After rmvdev/mkvdev, the ibmvscsi driver is waiting for the VIOS to
        send a Transport Event CRQ message.  Writing '1' to host_reset forces
        the driver to immediately tear down the stale CRQ session and send a
        fresh SRP_LOGIN_REQ, bypassing the passive reconnect timer
        (init_timeout=300s module parameter).

        This is non-blocking: the write returns immediately and the actual
        re-login handshake happens asynchronously in the driver's kthread.
        Recovery is detected by _check_srp_login_recovered() via /dev/kmsg.
        """
        if not self.scsi_host:
            self.log.warning("scsi_host not resolved; skipping reconnect kick")
            return

        host_reset_path = f"/sys/class/scsi_host/{self.scsi_host}/host_reset"
        host_state_path = f"/sys/class/scsi_host/{self.scsi_host}/state"

        if not os.path.exists(host_reset_path):
            self.log.warning(
                "host_reset sysfs not found for %s; skipping reconnect kick",
                self.scsi_host
            )
            return

        # The ibmvscsi driver rejects host_reset writes with EINVAL when the
        # host is already 'running'.  Only kick when the adapter is offline.
        try:
            with open(host_state_path) as sf:
                current_state = sf.read().strip()
        except OSError:
            current_state = "unknown"

        if current_state == "running":
            self.log.info(
                "ibmvscsi %s already running — skipping host_reset kick",
                self.scsi_host
            )
            return

        self.log.info(
            "ibmvscsi %s state is '%s' — writing host_reset to force CRQ re-login",
            self.scsi_host, current_state
        )
        try:
            with open(host_reset_path, "w") as fh:
                fh.write("1")   # no trailing newline — driver rejects "1\n"
            self.log.info(
                "Triggered ibmvscsi CRQ reconnect via %s", host_reset_path
            )
        except OSError as exc:
            self.log.warning(
                "Failed to write to %s (%s); driver will reconnect passively",
                host_reset_path, exc
            )

    def _get_scsi_host_for_disk(self):
        """
        Resolve the scsi_host name (e.g. 'host5') for the client disk via sysfs.
        Used to anchor dmesg recovery signal matching to this specific adapter.
        """
        try:
            real = os.path.realpath(f"/sys/block/{self.disk_name}/device")
            match = re.search(r'(host\d+)', real)
            if match:
                return match.group(1)
        except Exception:
            pass
        return ""

    def _watch_kmsg(self, match_signals, fail_signals, timeout_secs, label):
        """
        Event-driven kernel message watcher using /dev/kmsg + select().

        Opens /dev/kmsg, seeks to the current end so only messages produced
        after this call are examined, then uses select() to block until new
        data arrives.  Detection happens within milliseconds of the kernel
        emitting the message — there is no discrete polling step to miss.

        Args:
            match_signals: iterable of substrings — return True when any match.
            fail_signals:  iterable of substrings — return False when any match.
            timeout_secs:  wall-clock deadline in seconds.
            label:         human-readable description for log messages.

        Returns:
            True  if a match_signal was found within timeout_secs.
            False if a fail_signal was found, or timeout expired.
        """
        deadline = time.monotonic() + timeout_secs
        remainder = b""

        try:
            kmsg_fd = os.open("/dev/kmsg", os.O_RDONLY | os.O_NONBLOCK)
            # Seek to end — we only care about messages produced after this point
            os.lseek(kmsg_fd, 0, os.SEEK_END)
        except OSError as exc:
            self.log.warning(
                "Cannot open /dev/kmsg (%s); falling back to dmesg polling", exc
            )
            return self._poll_dmesg_fallback(
                match_signals, fail_signals, timeout_secs, label
            )

        self.log.info("Watching /dev/kmsg for %s (deadline %ds)...", label, timeout_secs)

        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.log.warning(
                        "%s: deadline reached (%ds) without matching signal",
                        label, timeout_secs
                    )
                    return False

                # Block until the kernel writes a new record or we time out
                ready, _, _ = select.select([kmsg_fd], [], [], min(remaining, 5.0))

                if ready:
                    try:
                        chunk = os.read(kmsg_fd, 8192)
                        remainder += chunk
                    except BlockingIOError:
                        continue

                    # kmsg records are newline-terminated; process complete lines only
                    lines = remainder.split(b"\n")
                    remainder = lines[-1]           # keep incomplete trailing line

                    for raw_line in lines[:-1]:
                        # kmsg format: "priority,seqnum,timestamp,-;message text"
                        # Strip the header prefix to get just the message text
                        sep = raw_line.find(b";")
                        msg = raw_line[sep + 1:] if sep != -1 else raw_line
                        text = msg.decode("utf-8", errors="replace")

                        for sig in fail_signals:
                            if sig in text:
                                elapsed = timeout_secs - remaining
                                self.log.error(
                                    "%s: failure signal matched after %.1fs: '%s'",
                                    label, elapsed, sig
                                )
                                return False

                        for sig in match_signals:
                            if sig in text:
                                elapsed = timeout_secs - remaining
                                self.log.info(
                                    "%s: recovery signal matched after %.1fs: '%s'",
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
                    self.log.error("%s: failure signal in dmesg: '%s'", label, sig)
                    return False
            for sig in match_signals:
                if sig in output:
                    self.log.info("%s: recovery signal in dmesg: '%s'", label, sig)
                    return True
            time.sleep(1)
        return False

    def _check_reset_started(self):
        """
        Verify that the client LPAR detects transport failure and initiates recovery.
        Uses /dev/kmsg event-driven detection — no polling step boundary to miss.
        """
        disruption_signals = [
            'Initiating adapter reset!',
            'ibmvscsi: host',
            'DID_ERROR',
            'I/O error',
            'transport',
        ]
        return self._watch_kmsg(
            match_signals=disruption_signals,
            fail_signals=[],
            timeout_secs=INJECT_CONFIRM_SECS,
            label="disruption-detection",
        )

    def _check_srp_login_recovered(self):
        """
        Monitor client LPAR for vSCSI transport recovery via /dev/kmsg select().

        ibmvscsi 1.5.9 (RHEL 9 / kernel 5.14+) does not emit 'SRP_LOGIN
        succeeded' in dmesg.  Recovery is signalled by:
          'sd H:C:T:L: Power-on or device reset occurred'
        Both this and the legacy SRP_LOGIN string are checked for portability.

        Detection is event-driven — the result is reported within milliseconds
        of the kernel message appearing, regardless of how long recovery takes.
        """
        recovery_signals = [
            'SRP_LOGIN succeeded',
            'SRP_LOGIN',
            'Power-on or device reset occurred',
        ]
        failure_signals = ['error after reset']
        return self._watch_kmsg(
            match_signals=recovery_signals,
            fail_signals=failure_signals,
            timeout_secs=RECOVERY_TIMEOUT_SECS,
            label="srp-recovery",
        )

    def _wait_for_disk_reappear(self):
        """
        Poll /sys/class/block/ to find the device node after recovery.
        Handles possible device name alterations after SCSI target rescans.
        """
        self.log.info("Waiting for block device behind host to stabilize...")
        for elapsed in range(DISK_RESCAN_TIMEOUT_SECS):
            # Check if our target disk name exists and is active
            if os.path.exists(f"/sys/class/block/{self.disk_name}"):
                self.log.info("Disk %s stabilized after %ds", self.disk_name, elapsed)
                return True
            time.sleep(1)
        return False

    def _verify_post_recovery_health(self):
        """
        Audit post-recovery device operational state, and run basic I/O read tests.
        """
        # 1. Audit SCSI Device State
        dev_state_path = f"/sys/class/block/{self.disk_name}/device/state"
        if os.path.exists(dev_state_path):
            state = genio.read_file(dev_state_path).strip()
            self.log.info("Client SCSI device operational state: %s", state)
            if state != "running":
                self.fail(f"Post-recovery device state is '{state}', expected 'running'")

        # 2. Verify basic reading capacity via sg_turs & dd
        rc = process.system(f"sg_turs /dev/{self.disk_name}", ignore_status=True, shell=True)
        if rc != 0:
            self.log.warning("sg_turs returned error code: %d. Falling back to read test...", rc)
            rc = process.system(f"dd if=/dev/{self.disk_name} of=/dev/null bs=512 count=1", ignore_status=True, shell=True)

        if rc != 0:
            self.fail(f"Target disk /dev/{self.disk_name} failed I/O accessibility checks post-recovery")

        self.log.info("I/O accessibility checks on /dev/%s completed successfully", self.disk_name)

    def _log_vios_traces(self):
        """
        Retrieve and print VIOS logs and error traces.
        """
        err_res = self.vios_session.cmd("errpt -a")
        if err_res.exit_status == 0:
            self.log.info("--- VIOS AIX errpt (Error Report) Output ---")
            self.log.info(err_res.stdout_text.strip())
        else:
            # Fallback virtual wrapper
            self.vios_session.cmd("ioscli errlog")
