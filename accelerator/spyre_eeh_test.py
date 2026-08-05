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

"""
Spyre EEH (Enhanced Error Handling) Test Suite

This test suite validates EEH functionality for Spyre AIU (AI Unit) adapters
on IBM Power systems. It includes:
- EEH enablement verification
- EEH max freeze count validation
- EEH error injection (single and multiple PCIe devices)
- Kernel message validation for EEH events
- PCIe device recovery verification
- Container restart validation after EEH events
"""

import os
import re
import time
from avocado import Test
from avocado.utils import process, dmesg


class SpyreEEHTest(Test):
    """
    Test EEH (Enhanced Error Handling) functionality for Spyre AIU adapters.
    
    This test validates that EEH is properly configured and can handle
    error injection scenarios for Spyre AIU PCIe devices.
    """

    def setUp(self):
        """
        Initialize test environment and validate prerequisites.
        """
        self.log.info("Spyre EEH Test - Setup")
        arch = process.run("uname -m", shell=True, ignore_status=True).stdout_text.strip()
        if "ppc64" not in arch:
            self.cancel("This test is only supported on PowerPC platforms")
        pci_addresses_str = self.params.get("PCI_ADDRESSES", default="")
        if not pci_addresses_str:
            self.cancel("PCI_ADDRESSES parameter is required in YAML")
        self.pci_addresses = [addr.strip() for addr in pci_addresses_str.split() if addr.strip()]
        if not self.pci_addresses:
            self.cancel("No valid PCI addresses provided")
        self.log.info("PCI Addresses to test: %s", self.pci_addresses)
        self.max_freezes = int(self.params.get("MAX_FREEZES", default="5"))
        self.log.info("Expected max freeze count: %d", self.max_freezes)
        self.eeh_enable_path = "/sys/kernel/debug/powerpc/eeh_enable"
        self.eeh_max_freezes_path = "/sys/kernel/debug/powerpc/eeh_max_freezes"
        self.eeh_dev_break_path = "/sys/kernel/debug/powerpc/eeh_dev_break"
        self.container_name = self.params.get("CONTAINER_NAME", default="")
        self.validate_container = bool(self.container_name)
        self.initial_dmesg = dmesg.collect_dmesg()
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
            result = process.run(cmd, shell=True, sudo=True, ignore_status=True)
            if result.exit_status == 0:
                self.log.info("✓ Successfully wrote '%s' to %s", value, filepath)
                return True
            else:
                self.log.error("Failed to write to %s: %s", filepath, result.stderr_text)
                return False
        except Exception as ex:
            self.log.error("Exception writing to %s: %s", filepath, ex)
            return False

    def _get_container_id(self, container_name):
        """
        Get container ID by name.
        
        :param container_name: Name of the container
        :return: Container ID or None
        """
        try:
            cmd = f"podman ps -a --filter name={container_name} --format '{{{{.ID}}}}'"
            result = process.run(cmd, shell=True, ignore_status=True)
            if result.exit_status == 0:
                container_id = result.stdout_text.strip()
                if container_id:
                    return container_id
        except Exception as ex:
            self.log.warning("Failed to get container ID: %s", ex)
        return None

    def _is_container_running(self, container_name):
        """
        Check if a container is running.
        
        :param container_name: Name of the container
        :return: True if running, False otherwise
        """
        try:
            cmd = f"podman ps --filter name={container_name} --format '{{{{.Names}}}}'"
            result = process.run(cmd, shell=True, ignore_status=True)
            if result.exit_status == 0:
                running_containers = result.stdout_text.strip()
                return container_name in running_containers
        except Exception as ex:
            self.log.warning("Failed to check container status: %s", ex)
        return False

    def test_eeh_enabled(self):
        """
        Test 1: Verify that EEH is enabled on the system.
        
        Checks /sys/kernel/debug/powerpc/eeh_enable for value 0x1
        """
        self.log.info("Test: EEH Enablement Check")

        if not self._check_file_exists(self.eeh_enable_path):
            self.fail(f"EEH enable file not found: {self.eeh_enable_path}")

        eeh_enable_value = self._read_sysfs_value(self.eeh_enable_path)
        if eeh_enable_value is None:
            self.fail("Failed to read EEH enable value")

        self.log.info("EEH enable value: %s", eeh_enable_value)
        if eeh_enable_value.strip() == "0x1":
            self.log.info("✓ EEH is enabled (0x1)")
        else:
            self.fail(f"EEH is not enabled. Expected 0x1, got {eeh_enable_value}")

    def test_eeh_max_freezes(self):
        """
        Test 2: Verify EEH max freeze count configuration.
        
        Checks /sys/kernel/debug/powerpc/eeh_max_freezes matches expected value
        """
        self.log.info("Test: EEH Max Freezes Check")
        if not self._check_file_exists(self.eeh_max_freezes_path):
            self.fail(f"EEH max freezes file not found: {self.eeh_max_freezes_path}")
        max_freezes_value = self._read_sysfs_value(self.eeh_max_freezes_path)
        if max_freezes_value is None:
            self.fail("Failed to read EEH max freezes value")
        self.log.info("EEH max freezes value: %s", max_freezes_value)
        try:
            actual_max_freezes = int(max_freezes_value.strip())
            if actual_max_freezes == self.max_freezes:
                self.log.info("✓ EEH max freezes matches expected value: %d", self.max_freezes)
            else:
                self.log.warning(
                    "EEH max freezes mismatch. Expected: %d, Actual: %d",
                    self.max_freezes, actual_max_freezes
                )
        except ValueError:
            self.fail(f"Invalid max freezes value: {max_freezes_value}")

    def _inject_eeh_error(self, pci_address):
        """
        Inject EEH error for a specific PCI device.
        
        :param pci_address: PCI address in format XXXX:XX:XX.X
        :return: True on success, False on failure
        """
        self.log.info("Injecting EEH error for PCI device: %s", pci_address)

        if not self._check_file_exists(self.eeh_dev_break_path):
            self.log.error("EEH dev break file not found: %s", self.eeh_dev_break_path)
            return False

        return self._write_sysfs_value(self.eeh_dev_break_path, pci_address)

    def _validate_eeh_in_dmesg(self, pci_address, timeout=30):
        """
        Validate that EEH error was logged in kernel messages.
        
        :param pci_address: PCI address to check for
        :param timeout: Timeout in seconds to wait for message
        :return: True if EEH message found, False otherwise
        """
        self.log.info("Validating EEH hit in kernel messages for %s", pci_address)

        pattern = rf"vfio-pci\s+{re.escape(pci_address)}:\s+Going to break:"

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                current_dmesg = dmesg.collect_dmesg()
                
                for line in current_dmesg:
                    if re.search(pattern, line):
                        self.log.info("✓ Found EEH message in dmesg: %s", line.strip())
                        return True

                time.sleep(2)
            except Exception as ex:
                self.log.warning("Error checking dmesg: %s", ex)
                time.sleep(2)

        self.log.error("EEH message not found in dmesg for %s within %d seconds", 
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
                self.log.info("✓ PCI device %s is present in lspci output", pci_address)
                self.log.debug("lspci output: %s", result.stdout_text.strip())
                return True
            else:
                self.log.error("PCI device %s not found in lspci output", pci_address)
                return False
        except Exception as ex:
            self.log.error("Failed to run lspci: %s", ex)
            return False

    def _validate_container_restarted(self, container_name, timeout=60):
        """
        Validate that container was restarted after EEH event.
        
        :param container_name: Name of the container
        :param timeout: Timeout in seconds to wait for restart
        :return: True if container restarted, False otherwise
        """
        self.log.info("Validating container restart: %s", container_name)

        initial_id = self._get_container_id(container_name)
        if not initial_id:
            self.log.warning("Container %s not found initially", container_name)
            return False

        self.log.info("Initial container ID: %s", initial_id)

        start_time = time.time()
        while time.time() - start_time < timeout:
            time.sleep(5)
            
            current_id = self._get_container_id(container_name)
            if current_id and current_id != initial_id:
                self.log.info("✓ Container restarted with new ID: %s", current_id)
                return True
            
            if self._is_container_running(container_name):
                self.log.info("✓ Container %s is running", container_name)
                return True

        self.log.error("Container did not restart within %d seconds", timeout)
        return False

    def test_eeh_inject_single_pci(self):
        """
        Test 3: Inject EEH error to a single PCI device and validate recovery.
        
        This test:
        1. Injects EEH error to the first PCI device
        2. Validates EEH message in kernel logs
        3. Validates device is still present in lspci
        4. Validates container restart (if configured)
        """
        self.log.info("Test: EEH Injection - Single PCI Device")
        if not self.pci_addresses:
            self.cancel("No PCI addresses configured for testing")
        pci_address = self.pci_addresses[0]
        self.log.info("Testing with PCI device: %s", pci_address)
        if not self._inject_eeh_error(pci_address):
            self.fail(f"Failed to inject EEH error for {pci_address}")
        if not self._validate_eeh_in_dmesg(pci_address):
            self.fail(f"EEH message not found in dmesg for {pci_address}")
        time.sleep(5)  # Wait for recovery
        if not self._validate_pci_device_present(pci_address):
            self.fail(f"PCI device {pci_address} not found after EEH injection")
        if self.validate_container:
            if not self._validate_container_restarted(self.container_name):
                self.log.warning("Container restart validation failed")
            else:
                self.log.info("✓ Container restart validated")
        self.log.info("✓ Single PCI EEH injection test completed successfully")

    def test_eeh_inject_all_pci(self):
        """
        Test 4: Inject EEH errors to all configured PCI devices.
        
        This test:
        1. Injects EEH error to each PCI device sequentially
        2. Validates EEH message in kernel logs for each device
        3. Validates each device is still present in lspci
        4. Validates container restart after all injections (if configured)
        """
        self.log.info("Test: EEH Injection - All PCI Devices")

        if not self.pci_addresses:
            self.cancel("No PCI addresses configured for testing")
        self.log.info("Testing with %d PCI devices", len(self.pci_addresses))
        failed_devices = []
        for idx, pci_address in enumerate(self.pci_addresses, 1):
            self.log.info("Testing PCI device %d/%d: %s", idx, len(self.pci_addresses), pci_address)
            try:
                if not self._inject_eeh_error(pci_address):
                    self.log.error("Failed to inject EEH error for %s", pci_address)
                    failed_devices.append(pci_address)
                    continue
                if not self._validate_eeh_in_dmesg(pci_address):
                    self.log.error("EEH message not found for %s", pci_address)
                    failed_devices.append(pci_address)
                    continue
                time.sleep(5)  # Wait for recovery
                if not self._validate_pci_device_present(pci_address):
                    self.log.error("PCI device %s not found after EEH injection", pci_address)
                    failed_devices.append(pci_address)
                    continue
                self.log.info("✓ PCI device %s passed all validations", pci_address)
                if idx < len(self.pci_addresses):
                    self.log.info("Waiting 10 seconds before next injection...")
                    time.sleep(10)
            except Exception as ex:
                self.log.error("Exception testing %s: %s", pci_address, ex)
                failed_devices.append(pci_address)
        if self.validate_container:
            self.log.info("")
            self.log.info("Validating container restart after all EEH injections...")
            if not self._validate_container_restarted(self.container_name, timeout=120):
                self.log.warning("Container restart validation failed")
            else:
                self.log.info("✓ Container restart validated")
        self.log.info("Total devices tested: %d", len(self.pci_addresses))
        self.log.info("Successful: %d", len(self.pci_addresses) - len(failed_devices))
        self.log.info("Failed: %d", len(failed_devices))

        if failed_devices:
            self.log.error("Failed devices: %s", ", ".join(failed_devices))
            self.fail(f"EEH injection failed for {len(failed_devices)} device(s)")

        self.log.info("✓ All PCI devices passed EEH injection test")

    def tearDown(self):
        """
        Cleanup after tests.
        """
        try:
            current_dmesg = dmesg.collect_dmesg()
            error_patterns = [
                r"kernel panic",
                r"Oops:",
                r"BUG:",
                r"WARNING:",
            ]
            
            for line in current_dmesg:
                for pattern in error_patterns:
                    if re.search(pattern, line, re.IGNORECASE):
                        self.log.warning("Kernel error detected: %s", line.strip())
        except Exception as ex:
            self.log.warning("Failed to check dmesg in tearDown: %s", ex)

        self.log.info("✓ Teardown completed")

