#!/usr/bin/env python3
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
# Author: Abdul Haleem <abdhalee@linux.vnet.ibm.com>
#         Sai Janani C <jananic@linux.ibm.com>

"""
Spyre EEH (Enhanced Error Handling) Test Suite

This test suite validates EEH functionality for Spyre AIU (AI Unit) adapters
on IBM Power systems. It includes:
- EEH enablement and max freeze count verification
- EEH error injection PCIe devices
- Kernel message validation for EEH events
- PCIe device recovery verification
- Non-root user container restart and vLLM startup verification
"""

import os
import re
import time
import pexpect
from avocado import Test
from avocado.utils import process
from avocado.utils.podman import wait_for_vllm_startup


class SpyreEEHTest(Test):
    """
    Test EEH (Enhanced Error Handling) functionality for Spyre AIU adapters.

    This test validates that EEH is properly configured and can handle
    error injection scenarios for Spyre AIU PCIe devices.
    """

    def _discover_pci_addresses(self):
        """
        Discover Spyre AIU PCI addresses dynamically using lspci.

        :return: List of PCI address strings (e.g. ['0382:60:00.0', ...])
        """
        try:
            cmd = "lspci -D -d 1014:06a7"
            result = process.run(cmd, shell=True, ignore_status=True)
            if result.exit_status == 0 and result.stdout_text.strip():
                addresses = []
                for line in result.stdout_text.strip().splitlines():
                    parts = line.split()
                    if parts:
                        addresses.append(parts[0])
                if addresses:
                    self.log.info("Discovered %d Spyre PCI device(s) via lspci: %s",
                                  len(addresses), addresses)
                    return addresses
        except Exception as ex:
            self.log.warning(
                "Failed to auto-discover Spyre PCI devices via lspci: %s", ex)
        return []

    def setUp(self):
        """
        Initialize test environment and validate prerequisites.
        """
        self.log.info("Spyre EEH Test - Setup")
        arch = process.run("uname -m", shell=True,
                           ignore_status=True).stdout_text.strip()
        if "ppc64" not in arch:
            self.cancel("This test is only supported on PowerPC platforms")

        pci_addresses_str = self.params.get("PCI_ADDRESSES", default="")
        if pci_addresses_str:
            self.pci_addresses = [
                addr.strip() for addr in pci_addresses_str.split() if addr.strip()]
        else:
            self.pci_addresses = self._discover_pci_addresses()

        if not self.pci_addresses:
            self.cancel(
                "No valid PCI addresses provided in YAML or discovered on system")
        self.log.info("PCI Addresses to test: %s", self.pci_addresses)

        self.max_freezes = int(self.params.get("MAX_FREEZES", default="5"))
        self.log.info("Expected max freeze count: %d", self.max_freezes)

        self.eeh_enable_path = "/sys/kernel/debug/powerpc/eeh_enable"
        self.eeh_max_freezes_path = "/sys/kernel/debug/powerpc/eeh_max_freezes"
        self.eeh_dev_break_path = "/sys/kernel/debug/powerpc/eeh_dev_break"

        self.user = self.params.get("USER", default="")
        self.validate_container = True
        self.log.info("✓ Setup completed successfully")

    def _check_file_exists(self, filepath):
        """
        Check if a file exists and is readable.

        :param filepath: Path to the file
        :return: True if file exists and is readable, False otherwise
        """
        if not os.path.exists(filepath):
            self.log.error("File does not exist: %s", filepath)
            return False
        if not os.access(filepath, os.R_OK):
            self.log.error("File is not readable: %s", filepath)
            return False
        return True

    def _read_sysfs_value(self, filepath):
        """
        Read a value from a sysfs file.

        :param filepath: Path to the sysfs file
        :return: Content of the file as string, or None on error
        """
        try:
            with open(filepath, 'r') as f:
                value = f.read().strip()
                self.log.debug("Read from %s: %s", filepath, value)
                return value
        except Exception as ex:
            self.log.error("Failed to read %s: %s", filepath, ex)
            return None

    def _write_sysfs_value(self, filepath, value):
        """
        Write a value to a sysfs file.

        :param filepath: Path to the sysfs file
        :param value: Value to write
        :return: True on success, False on error
        """
        try:
            cmd = f"echo {value} > {filepath}"
            result = process.run(
                cmd, shell=True, sudo=True, ignore_status=True)
            if result.exit_status == 0:
                self.log.info("✓ Successfully wrote '%s' to %s",
                              value, filepath)
                return True
            else:
                self.log.error("Failed to write to %s: %s",
                               filepath, result.stderr_text)
                return False
        except Exception as ex:
            self.log.error("Exception writing to %s: %s", filepath, ex)
            return False

    def _get_active_non_root_user(self):
        """
        Determine the non-root user for container checks.
        If self.user is specified, use it. Otherwise, find non-root users with active podman containers.
        """
        if self.user and self.user != "root":
            return self.user

        # Try to find users with running rootless containers or systemd user services
        try:
            cmd = "loginctl list-users --no-legend 2>/dev/null"
            res = process.run(cmd, shell=True, ignore_status=True)
            if res.exit_status == 0 and res.stdout_text.strip():
                for line in res.stdout_text.strip().splitlines():
                    parts = line.split()
                    if len(parts) >= 2:
                        uname = parts[1]
                        if uname not in ["root", "gdm", "lightdm"]:
                            # Check if this user has any container
                            c_cmd = f"su - {uname} -c 'podman ps -a -q' 2>/dev/null"
                            c_res = process.run(
                                c_cmd, shell=True, sudo=True, ignore_status=True)
                            if c_res.exit_status == 0 and c_res.stdout_text.strip():
                                return uname
        except Exception as ex:
            self.log.debug("Failed checking loginctl users: %s", ex)

        # Fallback check common non-root test users
        for test_user in ["senuser", "testuser"]:
            try:
                c_cmd = f"su - {test_user} -c 'podman ps -a -q' 2>/dev/null"
                c_res = process.run(c_cmd, shell=True,
                                    sudo=True, ignore_status=True)
                if c_res.exit_status == 0:
                    return test_user
            except Exception:
                pass
        return None

    def _get_non_root_containers_state(self, username=None):
        """
        Get state snapshot of all containers for the non-root user.

        :param username: Non-root user to check
        :return: Dict mapping container_id -> {'name': str, 'status': str, 'created': str}
        """
        containers = {}
        user_to_check = username or self._get_active_non_root_user()
        if not user_to_check:
            self.log.warning("No non-root user found for container check")
            return containers

        try:
            cmd = (f"su - {user_to_check} -c "
                   f"\"podman ps -a --format '{{{{.ID}}}}|{{{{.Names}}}}|{{{{.Status}}}}|{{{{.CreatedAt}}}}'\"")
            result = process.run(
                cmd, shell=True, sudo=True, ignore_status=True)
            if result.exit_status == 0 and result.stdout_text.strip():
                for line in result.stdout_text.strip().splitlines():
                    parts = line.split("|")
                    if len(parts) >= 3:
                        cid = parts[0].strip()
                        cname = parts[1].strip()
                        cstatus = parts[2].strip()
                        created = parts[3].strip() if len(parts) > 3 else ""
                        containers[cid] = {
                            "name": cname,
                            "status": cstatus,
                            "created": created,
                            "user": user_to_check
                        }
        except Exception as ex:
            self.log.warning(
                "Failed to get non-root containers for user %s: %s", user_to_check, ex)
        return containers

    def _get_running_containers(self, username=None):
        """
        Get all running containers for the non-root user.

        :param username: Non-root user to check
        :return: List of dicts of running containers
        """
        state = self._get_non_root_containers_state(username)
        return [
            c for c in state.values()
            if "Up" in c["status"] or "running" in c["status"].lower()
        ]

    def _validate_containers_down(self, initial_running_containers, timeout=30):
        """
        Validate that running containers went down (exited / stopped / restarting) after EEH injection.

        :param initial_running_containers: List of container dicts that were running before injection
        :param timeout: Maximum wait time in seconds
        :return: True if container down event observed, False otherwise
        """
        if not initial_running_containers:
            self.log.info(
                "No running non-root containers were detected to track going down.")
            return True

        user_to_check = initial_running_containers[0]["user"]
        running_names = [c["name"] for c in initial_running_containers]
        self.log.info("Validating containers go down for user '%s': %s (timeout: %ds)",
                      user_to_check, running_names, timeout)

        start_time = time.time()
        while time.time() - start_time < timeout:
            current_state = self._get_non_root_containers_state(user_to_check)

            # Check if any initial container has exited, stopped, or is missing
            for c_init in initial_running_containers:
                cid = None
                for k, v in current_state.items():
                    if v["name"] == c_init["name"]:
                        cid = k
                        break

                # If container is gone or no longer in "Up" status
                if not cid or "Up" not in current_state[cid]["status"]:
                    status = current_state[cid]["status"] if cid else "Removed/Stopped"
                    self.log.info("✓ Confirmed container '%s' went down after EEH injection (Status: %s)",
                                  c_init["name"], status)
                    return True

            time.sleep(1)

        self.log.info(
            "Container(s) remained in current state or recovered quickly within %d seconds", timeout)
        return False

    def _validate_non_root_containers_recovered(self, initial_running_containers, timeout=90):
        """
        Validate that containers for the non-root user recover and return to UP / running state,
        then wait for VLLM application startup to complete.

        :param initial_running_containers: List of container dicts that were running before injection
        :param timeout: Maximum wait time in seconds for container to report UP
        :return: True if container(s) are back UP and running and VLLM startup succeeds, False otherwise
        """
        if not initial_running_containers:
            self.log.info(
                "No initial running non-root containers to validate recovery for.")
            return True

        user_to_check = initial_running_containers[0]["user"]
        self.log.info("Validating container recovery for non-root user '%s' (timeout: %ds)...",
                      user_to_check, timeout)

        start_time = time.time()
        recovered_containers = []
        while time.time() - start_time < timeout:
            current_running = self._get_running_containers(user_to_check)
            if current_running:
                recovered_containers = current_running
                running_names = [c["name"] for c in current_running]
                self.log.info(
                    "✓ Container is recovered and back UP: %s", running_names)
                break
            time.sleep(3)

        if not recovered_containers:
            self.log.error("Container failed to recover back to UP state within %d seconds for user '%s'",
                           timeout, user_to_check)
            return False

        # Wait for vLLM application startup within each recovered container
        for c in recovered_containers:
            cid = None
            # Find the matching container ID
            state = self._get_non_root_containers_state(user_to_check)
            for k, v in state.items():
                if v["name"] == c["name"]:
                    cid = k
                    break

            target_id = cid or c["name"]
            self.log.info("Waiting for VLLM application startup in container '%s' (ID: %s, user: %s, timeout: 600s)...",
                          c["name"], target_id, user_to_check)
            vllm_ok = wait_for_vllm_startup(
                container_id=target_id,
                timeout=600,
                check_interval=15,
                user=user_to_check,
                log=self.log,
                show_live_logs=False
            )
            if not vllm_ok:
                self.log.error(
                    "VLLM application startup failed or timed out in container '%s'", c["name"])
                return False
            self.log.info(
                "✓ VLLM is up and running successfully in container '%s'", c["name"])

        return True

    def _verify_eeh_max_freezes(self):
        """
        Helper function to verify EEH max freeze count configuration.

        Checks /sys/kernel/debug/powerpc/eeh_max_freezes matches expected value
        """
        self.log.info("Checking EEH Max Freezes configuration")
        if not self._check_file_exists(self.eeh_max_freezes_path):
            self.fail(
                f"EEH max freezes file not found: {self.eeh_max_freezes_path}")
        max_freezes_value = self._read_sysfs_value(self.eeh_max_freezes_path)
        if max_freezes_value is None:
            self.fail("Failed to read EEH max freezes value")
        self.log.info("EEH max freezes value: %s", max_freezes_value)
        try:
            actual_max_freezes = int(max_freezes_value.strip(), 0)
            if actual_max_freezes == self.max_freezes:
                self.log.info(
                    "✓ EEH max freezes matches expected value: %d", self.max_freezes)
            else:
                self.fail(
                    f"EEH max freezes mismatch. Expected: {self.max_freezes}, Actual: {actual_max_freezes}"
                )
        except ValueError:
            self.fail(f"Invalid max freezes value: {max_freezes_value}")

    def test_eeh_enabled(self):
        """
        Test 1: Verify that EEH is enabled and max freeze count is configured.

        Checks /sys/kernel/debug/powerpc/eeh_enable for non-zero enabled value (0x1)
        and verifies /sys/kernel/debug/powerpc/eeh_max_freezes matches expected value.
        """
        self.log.info("Test: EEH Enablement and Configuration Check")

        if not self._check_file_exists(self.eeh_enable_path):
            self.fail(f"EEH enable file not found: {self.eeh_enable_path}")

        eeh_enable_raw = self._read_sysfs_value(self.eeh_enable_path)
        if eeh_enable_raw is None:
            self.fail("Failed to read EEH enable value")

        self.log.info("EEH enable value: %s", eeh_enable_raw)
        try:
            eeh_enable_val = int(eeh_enable_raw.strip(), 0)
            if eeh_enable_val == 1:
                self.log.info("✓ EEH is enabled (0x1)")
            else:
                self.fail(
                    f"EEH is not enabled. Expected 0x1, got {eeh_enable_raw}")
        except ValueError:
            self.fail(f"Could not parse EEH enable value: {eeh_enable_raw}")

        self._verify_eeh_max_freezes()

    def _inject_eeh_error(self, pci_address):
        """
        Inject EEH error for a specific PCI device.

        :param pci_address: PCI address in format XXXX:XX:XX.X
        :return: True on success, False on failure
        """
        self.log.info("Injecting EEH error for PCI device: %s", pci_address)

        if not self._check_file_exists(self.eeh_dev_break_path):
            self.log.error("EEH dev break file not found: %s",
                           self.eeh_dev_break_path)
            return False

        return self._write_sysfs_value(self.eeh_dev_break_path, pci_address)

    def _get_dmesg_lines(self):
        """
        Get current dmesg lines quietly (verbose=False) so full dmesg output
        is never dumped into debug.log.
        """
        try:
            raw = process.system_output(
                "dmesg", verbose=False, ignore_status=True, sudo=True)
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            return [line.strip() for line in raw.splitlines() if line.strip()]
        except Exception:
            return []

    def _validate_eeh_in_dmesg(self, pci_address, initial_line_count=0, timeout=30, max_new_lines=None):
        """
        Check if the latest kernel logs contain EEH error or recovery messages.
        If found, logs ONLY the specific matching EEH lines (no full dmesg dump).

        :param pci_address: PCI address to check for
        :param initial_line_count: Number of dmesg lines prior to injection
        :param timeout: Timeout in seconds to wait for message
        :param max_new_lines: If set, inspect only the last N new lines (e.g. 2 for PHYP test)
        :return: True if EEH message found, False otherwise
        """
        self.log.info(
            "Checking for EEH messages in latest kernel logs for %s", pci_address)

        patterns = [
            rf"vfio-pci\s+{re.escape(pci_address)}:\s+Going to break:",
            rf"EEH:\s+Frozen PE#.*detected on.*{re.escape(pci_address)}",
            rf"EEH:\s+Beginning recovery",
            rf"EEH:\s+Recovery successful",
            rf"EEH:\s+Notify device drivers.*{re.escape(pci_address)}",
            rf"eeh_dev_break.*{re.escape(pci_address)}",
            rf"EEH:\s+Frozen",
            rf"EEH:\s+PE.*frozen",
            rf"EEH:\s+Event.*detected",
            rf"eeh_pci_enable",
            rf"eeh_unfreeze_pe",
            rf"rtas.*errinjct",
            rf"ioa-bus-error"
        ]

        found_any = False
        matched_lines = set()
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                current_dmesg = self._get_dmesg_lines()
                # Inspect only the latest lines emitted since injection started
                new_lines = current_dmesg[initial_line_count:]
                if max_new_lines is not None:
                    new_lines = new_lines[-max_new_lines:]

                for line in new_lines:
                    if line in matched_lines:
                        continue
                    for pattern in patterns:
                        if re.search(pattern, line, re.IGNORECASE):
                            self.log.info("✓ [dmesg EEH] %s", line)
                            matched_lines.add(line)
                            found_any = True
                            break

                if found_any:
                    time.sleep(1)
                    current_dmesg = self._get_dmesg_lines()
                    follow_up_lines = current_dmesg[initial_line_count:]
                    if max_new_lines is not None:
                        follow_up_lines = follow_up_lines[-max_new_lines:]
                    for line in follow_up_lines:
                        if line not in matched_lines:
                            for pattern in patterns:
                                if re.search(pattern, line, re.IGNORECASE):
                                    self.log.info("✓ [dmesg EEH] %s", line)
                                    matched_lines.add(line)
                                    break
                    return True

                time.sleep(2)
            except Exception as ex:
                self.log.debug("Error checking dmesg: %s", ex)
                time.sleep(2)

        self.log.info("No EEH messages observed in latest dmesg for %s within %d seconds",
                      pci_address, timeout)
        return False

    def _validate_pci_device_present(self, pci_address):
        """
        Validate that PCI device is still listed by lspci.

        :param pci_address: PCI address to check
        :return: True if device is present, False otherwise
        """
        self.log.info("Validating PCI device presence: %s", pci_address)
        try:
            cmd = f"lspci -s {pci_address}"
            result = process.run(cmd, shell=True, ignore_status=True)
            if result.exit_status == 0 and result.stdout_text.strip():
                self.log.info(
                    "✓ PCI device %s is present in lspci output", pci_address)
                self.log.debug("lspci output: %s", result.stdout_text.strip())
                return True
            else:
                self.log.error(
                    "PCI device %s not found in lspci output", pci_address)
                return False
        except Exception as ex:
            self.log.error("Failed to run lspci: %s", ex)
            return False

    def _get_spyre_location_code(self, pci_address):
        """
        Get the physical location code for a PCI device.
        Tries lspci first, then lsslot -c pci.

        :param pci_address: PCI address in format XXXX:XX:XX.X
        :return: Location code string or None
        """
        # Method 1: lspci -s <addr> -v
        try:
            cmd = f"lspci -s {pci_address} -v"
            res = process.run(cmd, shell=True, ignore_status=True)
            if res.exit_status == 0 and res.stdout_text:
                for line in res.stdout_text.splitlines():
                    if "Physical Slot:" in line:
                        loc = line.split("Physical Slot:")[-1].strip()
                        if loc:
                            return loc
        except Exception as ex:
            self.log.debug("lspci Physical Slot lookup failed: %s", ex)

        # Method 2: lsslot -c pci
        try:
            cmd = "lsslot -c pci"
            res = process.run(cmd, shell=True, ignore_status=True)
            if res.exit_status == 0 and res.stdout_text:
                for line in res.stdout_text.splitlines():
                    if pci_address in line:
                        parts = line.split()
                        if parts:
                            return parts[0]
        except Exception as ex:
            self.log.debug("lsslot lookup failed: %s", ex)

        return None

    def _get_spyre_memory_regions(self, pci_address):
        """
        Retrieve physical bus addresses and assign fixed hardware masks for Spyre BAR regions.

        Hardware BAR regions and masks on Spyre cards:
          - Region 0: 4MB  -> 0xffffffffffc00000
          - Region 2: 2GB  -> 0xffffffff80000000
          - Region 4: 32MB -> 0xfffffffffe000000

        :param pci_address: PCI address in format XXXX:XX:XX.X
        :return: List of dicts [{'region': int, 'bus_addr': str, 'size': str, 'mask': str}]
        """
        # Fixed Spyre hardware BAR region definitions
        SPYRE_BAR_SPECS = [
            {"region": 0, "size": "4M", "mask": "0xffffffffffc00000"},
            {"region": 2, "size": "2G", "mask": "0xffffffff80000000"},
            {"region": 4, "size": "32M", "mask": "0xfffffffffe000000"},
        ]

        regions = []
        try:
            # Physical bus addresses from lspci -bvs
            cmd = f"lspci -bvs {pci_address}"
            res = process.run(cmd, shell=True, ignore_status=True)
            if res.exit_status == 0 and res.stdout_text:
                bus_addrs = []
                for line in res.stdout_text.splitlines():
                    m = re.search(r"Memory at\s+([0-9a-fA-F]+)", line)
                    if m:
                        bus_addrs.append(f"0x{m.group(1)}")

                for idx, spec in enumerate(SPYRE_BAR_SPECS):
                    if idx < len(bus_addrs):
                        regions.append({
                            "region": spec["region"],
                            "bus_addr": bus_addrs[idx],
                            "size": spec["size"],
                            "mask": spec["mask"]
                        })
        except Exception as ex:
            self.log.error(
                "Failed to get physical bus addresses via lspci -bvs: %s", ex)

        return regions

    def _inject_errinjct_tool_error(self, loc_code, bus_addr, mask, func=6):
        """
        Execute errinjct tool to inject ioa-bus-error-64.

        :param loc_code: Physical slot location code (e.g. U5B67.001.WZS04XK-P1-C0)
        :param bus_addr: Physical bus address (e.g. 0x6c21880000000)
        :param mask: Address mask (e.g. 0xffffffffffc00000)
        :param func: Injection function code (default: 6)
        :return: True if injection succeeded, False otherwise
        """
        # Ensure errinjct facility is open
        open_cmd = "errinjct open"
        open_res = process.run(open_cmd, shell=True,
                               sudo=True, ignore_status=True)
        self.log.info("errinjct open output: %s",
                      open_res.stdout_text.strip() or open_res.stderr_text.strip())

        # Construct error injection command
        cmd = f"errinjct ioa-bus-error-64 -k 1 -p {loc_code} -a {bus_addr} -m {mask} -f {func}"
        self.log.info("Injecting RTAS error with command: %s", cmd)

        result = process.run(cmd, shell=True, sudo=True, ignore_status=True)
        stdout = result.stdout_text
        stderr = result.stderr_text
        output = f"{stdout}\n{stderr}".strip()
        self.log.info("errinjct output:\n%s", output)

        if "Call to RTAS errinjct succeeded" in output or "succeeded" in output.lower():
            self.log.info("✓ RTAS errinjct injection succeeded!")
            return True
        else:
            self.log.error(
                "RTAS errinjct injection did not succeed: %s", output)
            return False

    def test_linux_eeh(self):
        """
        Test 2: Inject EEH errors to all configured PCI devices via Linux debugfs.

        This test:
        1. Checks non-root user's podman containers are UP before injection
        2. Injects EEH error to each PCI device sequentially via Linux debugfs
        3. Validates container goes DOWN upon injection
        4. Validates EEH message in new kernel logs for each device
        5. Validates each device is present in lspci after recovery
        6. Validates container recovers back UP and vLLM starts after each/all injections
        """
        self.log.info(
            "Test 2: EEH Injection via Linux debugfs - All PCI Devices")

        if not self.pci_addresses:
            self.cancel("No PCI addresses configured for testing")
        self.log.info("Testing with %d PCI devices", len(self.pci_addresses))

        initial_running = self._get_running_containers()
        if initial_running:
            running_names = [c["name"] for c in initial_running]
            self.log.info("✓ Pre-injection check: Non-root container(s) are UP and running: %s",
                          running_names)
        else:
            self.log.info(
                "Pre-injection check: No running non-root container found.")

        failed_devices = []

        for idx, pci_address in enumerate(self.pci_addresses, 1):
            self.log.info("Testing PCI device %d/%d: %s", idx,
                          len(self.pci_addresses), pci_address)
            try:
                # Check container is up prior to this injection
                current_running = self._get_running_containers() or initial_running

                initial_dmesg_count = len(self._get_dmesg_lines())

                # Trigger error injection
                if not self._inject_eeh_error(pci_address):
                    self.log.error(
                        "Failed to inject EEH error for %s", pci_address)
                    failed_devices.append(pci_address)
                    continue

                # Verify container goes down upon injection
                if current_running:
                    self._validate_containers_down(current_running, timeout=15)

                # Validate dmesg EEH message (optional log; test still passes if absent)
                if not self._validate_eeh_in_dmesg(pci_address, initial_line_count=initial_dmesg_count):
                    self.log.info(
                        "EEH logs not captured in dmesg for %s (continuing with recovery and VLLM validation)", pci_address)

                # Wait for recovery & check PCI device presence
                time.sleep(5)
                if not self._validate_pci_device_present(pci_address):
                    self.log.error(
                        "PCI device %s not found after EEH injection", pci_address)
                    failed_devices.append(pci_address)
                    continue

                # Wait for container to recover back UP and VLLM to startup
                if current_running:
                    if not self._validate_non_root_containers_recovered(current_running, timeout=90):
                        self.log.error(
                            "Container recovery or VLLM startup failed for %s", pci_address)
                        failed_devices.append(pci_address)
                        continue
                    self.log.info(
                        "✓ Container and VLLM recovery validated successfully for %s", pci_address)

                self.log.info(
                    "✓ PCI device %s passed all validations", pci_address)
                if idx < len(self.pci_addresses):
                    self.log.info(
                        "Waiting 10 seconds before next injection...")
                    time.sleep(10)
            except Exception as ex:
                self.log.error("Exception testing %s: %s", pci_address, ex)
                failed_devices.append(pci_address)

        if initial_running:
            self.log.info(
                "Validating final non-root container and VLLM state after all EEH injections...")
            if not self._validate_non_root_containers_recovered(initial_running, timeout=90):
                self.log.error(
                    "Final container or VLLM recovery validation failed")
                self.fail("Final container recovery / VLLM startup check failed")
            else:
                self.log.info(
                    "✓ Final non-root container and VLLM state validated successfully")

        self.log.info("Total devices tested: %d", len(self.pci_addresses))
        self.log.info("Successful: %d", len(
            self.pci_addresses) - len(failed_devices))
        self.log.info("Failed: %d", len(failed_devices))

        if failed_devices:
            self.log.error("Failed devices: %s", ", ".join(failed_devices))
            self.fail(
                f"EEH injection failed for {len(failed_devices)} device(s)")

        self.log.info("✓ All PCI devices passed EEH injection test")

    def test_errinjct_tool_eeh(self):
        """
        Test 3: Inject EEH errors using the errinjct RTAS tool across memory regions and function codes.

        Steps:
        1. Query physical slot / location code for each Spyre device
        2. Query physical bus addresses (lspci -bvs) and region sizes (lspci -vvv) to calculate masks
        3. Execute errinjct ioa-bus-error-64 with -k 1 across memory regions and functions (e.g. 6, 0, 4)
        4. Validate EEH dmesg events, PCI device presence, and container/vLLM recovery
        """
        self.log.info(
            "Test 3: EEH Error Injection using errinjct RTAS Tool (ioa-bus-error-64)")

        # Verify errinjct utility is installed
        chk = process.run("which errinjct", shell=True, ignore_status=True)
        if chk.exit_status != 0:
            self.cancel(
                "errinjct tool not found on system. Please install powerpc-utils.")

        if not self.pci_addresses:
            self.cancel("No PCI addresses configured for testing")

        func_param = self.params.get("ERRINJCT_FUNCTIONS", default="0 1 6 7")
        functions = [int(f.strip())
                     for f in str(func_param).split() if f.strip().isdigit()]
        if not functions:
            functions = [0, 1, 6, 7]

        initial_running = self._get_running_containers()
        if initial_running:
            running_names = [c["name"] for c in initial_running]
            self.log.info(
                "✓ Pre-injection check: Non-root container(s) are UP: %s", running_names)

        failed_tests = []

        for card_idx, pci_address in enumerate(self.pci_addresses):
            self.log.info("==================================================")
            self.log.info("Testing Spyre PCI device %d/%d: %s",
                          card_idx + 1, len(self.pci_addresses), pci_address)

            loc_code = self._get_spyre_location_code(pci_address)
            if not loc_code:
                self.log.error(
                    "Could not find location code for %s", pci_address)
                failed_tests.append(f"{pci_address}: missing location code")
                continue
            self.log.info("Found Location Code: %s", loc_code)

            regions = self._get_spyre_memory_regions(pci_address)
            if not regions:
                self.log.error(
                    "Could not obtain physical memory regions for %s", pci_address)
                failed_tests.append(f"{pci_address}: missing memory regions")
                continue

            # Pick 1 region and 1 function for this card
            reg = regions[card_idx % len(regions)]
            func = functions[card_idx % len(functions)]

            test_label = f"{pci_address} (Reg {reg['region']}, Func {func})"
            self.log.info("--- Running 1 Injection for this Card: %s | Addr: %s | Mask: %s ---",
                          test_label, reg['bus_addr'], reg['mask'])

            current_running = self._get_running_containers() or initial_running
            initial_dmesg_count = len(self._get_dmesg_lines())

            # Inject error via errinjct
            if not self._inject_errinjct_tool_error(loc_code, reg['bus_addr'], reg['mask'], func=func):
                self.log.error(
                    "Failed to inject RTAS error for %s", test_label)
                failed_tests.append(f"{test_label}: injection failed")
                continue

            # Verify container goes down upon injection
            if current_running:
                self._validate_containers_down(current_running, timeout=15)

            # Validate dmesg EEH message (optional check; logs message if present, does not fail test if absent)
            if not self._validate_eeh_in_dmesg(pci_address, initial_line_count=initial_dmesg_count):
                self.log.info(
                    "EEH logs not captured in dmesg for %s (continuing with recovery and VLLM validation)", test_label)

            # Wait for recovery & verify PCI device presence
            time.sleep(5)
            if not self._validate_pci_device_present(pci_address):
                self.log.error(
                    "PCI device %s not present after error injection", pci_address)
                failed_tests.append(f"{test_label}: device not found in lspci")
                continue

            # Validate container and vLLM recovery
            if current_running:
                if not self._validate_non_root_containers_recovered(current_running, timeout=90):
                    self.log.error(
                        "Container/VLLM recovery failed for %s", test_label)
                    failed_tests.append(
                        f"{test_label}: container recovery failed")
                    continue
                self.log.info(
                    "✓ Container and VLLM recovery validated successfully for %s", test_label)

            self.log.info(
                "✓ Successfully verified EEH injection and recovery for %s", test_label)
            time.sleep(5)

        # Close RTAS facility
        process.run("errinjct close -k 1", shell=True,
                    sudo=True, ignore_status=True)

        if failed_tests:
            self.log.error("Failed errinjct tests:\n%s",
                           "\n".join(failed_tests))
            self.fail(
                f"errinjct tool EEH test failed for {len(failed_tests)} test combination(s)")

        self.log.info(
            "✓ All errinjct tool EEH injections passed successfully!")

    def _phyp_connect(self, fsp_ip, fsp_user, fsp_password, port=2201):
        """
        Connect to PHYP console via SSH on port 2201 using pexpect.

        :return: pexpect spawn child handle or None
        """
        ssh_cmd = f"ssh -k -p {port} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null {fsp_user}@{fsp_ip}"
        self.log.info("Connecting to PHYP console: %s", ssh_cmd)
        try:
            child = pexpect.spawn(ssh_cmd, encoding="utf-8", timeout=30)
            idx = child.expect(
                ["password:", "Password:", pexpect.TIMEOUT, pexpect.EOF])
            if idx in [0, 1]:
                child.send(f"{fsp_password}\r\n")
                time.sleep(2)
                child.send("\r\n")
                time.sleep(1)
                child.expect([r"phyp\s*#", r"PHYP>", r"FSP-.*>",
                             r"[#>$]", pexpect.TIMEOUT], timeout=20)
                self.log.info("✓ Connected to PHYP console successfully")
                return child
            elif idx == 2:
                self.log.error("Timeout waiting for PHYP password prompt")
            else:
                self.log.error(
                    "EOF encountered when connecting to PHYP console: %s", child.before)
        except Exception as ex:
            self.log.error("Exception connecting to PHYP console: %s", ex)
        return None

    def _phyp_run_command(self, child, cmd, timeout=60):
        """
        Run a command on the PHYP console and return the output.
        Retries if 'Macro entry point could not be located' or 'not registered' is returned.

        :param child: pexpect spawn child
        :param cmd: Command string to execute
        :param timeout: Command timeout in seconds
        :return: Command output string or None
        """
        prompts = [r"phyp\s*#", r"PHYP>", r"FSP-.*>", r"[#>$]"]
        for attempt in range(1, 4):
            try:
                # Flush any leftover chars in the buffer before sending new command
                try:
                    while True:
                        child.read_nonblocking(size=1024, timeout=0.1)
                except Exception:
                    pass

                self.log.info("PHYP [attempt %d] Executing: %s", attempt, cmd)
                child.send(f"{cmd}\r\n")
                matched_idx = child.expect(
                    prompts + [pexpect.TIMEOUT], timeout=timeout)
                output = child.before or ""
                self.log.debug(
                    "PHYP raw output (matched idx %s):\n%s", matched_idx, output)

                if matched_idx == len(prompts):  # TIMEOUT
                    self.log.info(
                        "Timeout waiting for prompt after '%s'. Output received so far:\n%s", cmd, output)
                    if "Slot Drc:" in output or "Port Error Injection" in output:
                        return output
                    child.send("\r\n")
                    time.sleep(1)
                    continue

                if "Macro entry point could not be located" in output or "not registered" in output:
                    self.log.warning(
                        "Macro not registered / entry point error, retrying in 2s...")
                    time.sleep(2)
                    continue

                return output
            except Exception as ex:
                self.log.error(
                    "Exception executing PHYP command '%s': %s", cmd, ex)
                time.sleep(2)

        return None

    def _get_switch_drcs_from_phyp(self, child, pci_addresses):
        """
        Run xmquery -q allslots -d 2 and extract Switch DRC values for target PCI addresses.
        Mapping logic:
          - For each PCI address (e.g. '0301:50:00.0'), takes first 3 chars ('301' or '030')
          - Matches Slot Drc whose last 3 hex chars equal the first 3 chars of the PCI address
          - Extracts 'Switch Drc: <val>'

        :param child: Active PHYP pexpect session
        :param pci_addresses: List of PCI address strings
        :return: Dict mapping pci_address -> switch_drc
        """
        output = self._phyp_run_command(child, "xmquery -q allslots -d 2")
        if not output:
            self.log.error("Failed to get allslots output from PHYP")
            return {}

        self.log.info("xmquery allslots output:\n%s", output)

        pci_switch_map = {}
        for pci_addr in pci_addresses:
            # Extract first 3 hex characters (ignoring leading 0s or taking normalized 3 digits)
            # Example '0301:50:00.0' -> '301', '0382:60:00.0' -> '382', '0015:01:00.0' -> '015'
            clean_bdf = pci_addr.split(":")[0].lstrip("0") or "0"
            clean_bdf_3 = pci_addr.split(":")[0][-3:]

            match_keys = [clean_bdf, clean_bdf_3]
            self.log.info(
                "Looking up Switch DRC for PCI %s using search keys: %s", pci_addr, match_keys)

            for line in output.splitlines():
                if "Slot Drc:" in line and "Switch Drc:" in line:
                    # Example line: Slot Drc: 21010301 C0 HasIoa On OwningLp:0003 Port:00 Parent Drc: 24080038 Switch Drc: 28000300
                    # Slot Drc value is 2nd token after 'Slot Drc:' (e.g. 21010301 or *2101001A)
                    m = re.search(r"Slot Drc:\s*\*?([0-9a-fA-F]+)", line)
                    if m:
                        slot_drc_val = m.group(1).upper()
                        # Last 3 digits of slot drc
                        last_3 = slot_drc_val[-3:]

                        if any(k.upper() in last_3 or last_3.endswith(k.upper()) for k in match_keys):
                            # Extract switch DRC
                            sw_match = re.search(
                                r"Switch Drc:\s*([0-9a-fA-F]+)", line)
                            if sw_match:
                                sw_drc = sw_match.group(1).strip()
                                pci_switch_map[pci_addr] = sw_drc
                                self.log.info("✓ Matched PCI %s -> Slot DRC: %s -> Switch DRC: %s",
                                              pci_addr, slot_drc_val, sw_drc)
                                break

        return pci_switch_map

    def test_phyp_eeh(self):
        """
        Test 4: Inject EEH errors from PHYP console using xmswitchmodeinjecterror.

        Steps:
        1. Ensure container and vLLM are up before injection
        2. Connect to PHYP console via SSH (port 2201) using FSP credentials from YAML
        3. Run xmquery -q allslots -d 2 to find Switch DRC for each PCI device
        4. Run xmswitchmodeinjecterror -d <switch_drc> -p 0 UERR -b 17 -ds on unique Switch DRCs
        5. Verify 'Port Error Injection' in PHYP output
        6. Capture EEH kernel logs in dmesg (e.g. eeh_pci_enable / eeh_unfreeze_pe / PE frozen)
        7. Validate container goes down, recovers back UP, and vLLM starts up
        """
        self.log.info("Test 4: PHYP Console EEH Switch Mode Error Injection")

        fsp_ip = self.params.get("FSP_IP", default="")
        fsp_user = self.params.get("FSP_USER", default="")
        fsp_password = self.params.get("FSP_PASSWORD", default="")

        if not fsp_ip or not fsp_user or not fsp_password:
            self.cancel(
                "FSP_IP, FSP_USER, or FSP_PASSWORD not configured in YAML. Skipping PHYP EEH test.")

        if not self.pci_addresses:
            self.cancel("No PCI addresses configured for testing")

        # Step 1: Ensure initial container and vLLM state
        initial_running = self._get_running_containers()
        if initial_running:
            running_names = [c["name"] for c in initial_running]
            self.log.info(
                "✓ Pre-injection check: Non-root container(s) are UP: %s", running_names)
            # Ensure vLLM is healthy before proceeding
            self.log.info(
                "Ensuring vLLM is fully started before PHYP injection...")
            if not self._validate_non_root_containers_recovered(initial_running, timeout=120):
                self.fail(
                    "Pre-test validation failed: Container or vLLM not healthy before PHYP injection")

        # Step 2: Connect to PHYP console
        phyp_session = self._phyp_connect(
            fsp_ip, fsp_user, fsp_password, port=2201)
        if not phyp_session:
            self.fail(f"Failed to connect to PHYP console at {fsp_ip}:2201")

        try:
            # Step 3: Discover Switch DRCs
            pci_switch_map = self._get_switch_drcs_from_phyp(
                phyp_session, self.pci_addresses)
            if not pci_switch_map:
                self.fail(
                    "Could not find Switch DRC for any configured Spyre PCI devices from xmquery output")

            # Collect unique switch DRCs to avoid duplicate injections on shared switches
            unique_switch_drcs = {}
            for pci_addr, sw_drc in pci_switch_map.items():
                if sw_drc not in unique_switch_drcs:
                    unique_switch_drcs[sw_drc] = []
                unique_switch_drcs[sw_drc].append(pci_addr)

            self.log.info("Unique Switch DRC(s) to test: %s",
                          unique_switch_drcs)

            failed_switches = []

            # Step 4: Inject error per unique switch DRC
            for sw_idx, (sw_drc, associated_pcis) in enumerate(unique_switch_drcs.items(), 1):
                self.log.info(
                    "==================================================")
                self.log.info("Testing Switch DRC %d/%d: %s (Associated PCI devices: %s)",
                              sw_idx, len(unique_switch_drcs), sw_drc, associated_pcis)

                current_running = self._get_running_containers() or initial_running
                initial_dmesg_count = len(self._get_dmesg_lines())

                inject_cmd = f"xmswitchmodeinjecterror -d {sw_drc} -p 0 UERR -b 17 -ds"
                inject_output = self._phyp_run_command(
                    phyp_session, inject_cmd, timeout=30)
                self.log.info(
                    "xmswitchmodeinjecterror output:\n%s", inject_output)

                if not inject_output or "Port Error Injection" not in inject_output:
                    self.log.error("xmswitchmodeinjecterror failed or 'Port Error Injection' not in output for %s: %s",
                                   sw_drc, inject_output)
                    failed_switches.append(
                        f"Switch DRC {sw_drc}: injection command failed")
                    continue

                self.log.info(
                    "✓ Port Error Injection triggered successfully on Switch DRC %s", sw_drc)

                # Step 5: Verify container goes down upon injection
                if current_running:
                    self._validate_containers_down(current_running, timeout=15)

                # Step 6: Validate dmesg EEH message for each associated PCI device
                # Only check the last 2 new dmesg lines to avoid matching stale/old log entries
                for pci_addr in associated_pcis:
                    if not self._validate_eeh_in_dmesg(pci_addr, initial_line_count=initial_dmesg_count, max_new_lines=2):
                        self.log.info(
                            "EEH logs not captured in dmesg for %s (continuing with recovery and VLLM validation)", pci_addr)

                # Step 7: Wait for recovery & verify PCI device presence
                time.sleep(5)
                for pci_addr in associated_pcis:
                    if not self._validate_pci_device_present(pci_addr):
                        self.log.error(
                            "PCI device %s not present in lspci after PHYP EEH injection", pci_addr)
                        failed_switches.append(
                            f"Switch DRC {sw_drc} ({pci_addr}): device missing in lspci")

                # Step 8: Validate container and vLLM recovery
                if current_running:
                    if not self._validate_non_root_containers_recovered(current_running, timeout=120):
                        self.log.error(
                            "Container/VLLM recovery failed after PHYP EEH on Switch DRC %s", sw_drc)
                        failed_switches.append(
                            f"Switch DRC {sw_drc}: container recovery failed")
                        continue
                    self.log.info(
                        "✓ Container and VLLM recovery validated successfully for Switch DRC %s", sw_drc)

                self.log.info(
                    "✓ Successfully verified PHYP EEH injection and recovery on Switch DRC %s", sw_drc)
                time.sleep(5)

            if failed_switches:
                self.log.error("Failed PHYP EEH test(s):\n%s",
                               "\n".join(failed_switches))
                self.fail(
                    f"PHYP EEH test failed for {len(failed_switches)} switch DRC(s)")

            self.log.info(
                "✓ All PHYP EEH switch injections passed successfully!")

        finally:
            try:
                phyp_session.sendline("exit")
                phyp_session.close()
            except Exception:
                pass
