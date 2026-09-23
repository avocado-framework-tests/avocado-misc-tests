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
# Author: Naresh Bannoth <nbannoth@in.ibm.com>

"""
NVMe Dataset Management (DSM / Deallocate / Trim) Test.

Issues the NVMe Dataset Management command (Deallocate, Write, Read hints)
on the target namespace, then verifies the namespace is still accessible
and I/O continues to work.

Requires the device to advertise 'Data Set Management Supported' in id-ctrl.
"""

import json
import os

from avocado import Test
from avocado.utils import archive
from avocado.utils import disk
from avocado.utils import nvme
from avocado.utils import process
from avocado.utils.software_manager.manager import SoftwareManager


class NVMeDataSetManagement(Test):
    """
    NVMe Dataset Management (DSM) Test.

    :param device: Name of the nvme device (e.g. nvme0, or subsystem NQN)
    :param shared_namespaces: True if the namespace is shared (default False)
    :param package: 'distro' (default) or 'upstream' to build
                    nvme-cli from source
    """

    def setUp(self):
        """
        Install nvme-cli, resolve the device path, and verify DSM support.

        The namespace to operate on is discovered automatically by querying
        the controller at runtime — the first namespace returned by
        ``nvme.get_current_ns_list()`` is used.  No namespace parameter is
        required in the YAML configuration.
        """
        nvme_node = self.params.get('device', default=None)
        if not nvme_node:
            self.cancel("Please provide valid nvme node name")
        elif "subsys" in nvme_node:
            nvme_node = nvme.get_controllers_with_subsys(nvme_node)[0]
        elif nvme_node.startswith("nqn."):
            nvme_node = nvme.get_controllers_with_nqn(nvme_node)[0]
        self.device = disk.get_absolute_disk_path(nvme_node)
        if process.system(f'ls {self.device}', ignore_status=True):
            self.cancel(f"{self.device} does not exist")

        self.ctrl_name = self.device.split("/")[-1]
        self.shared = self.params.get('shared_namespaces', default=False)
        self.dsm_timeout = 5000

        # Discover all namespaces on the controller and pick the first one.
        ns_list = nvme.get_current_ns_list(self.ctrl_name,
                                           shared_ns=self.shared)
        if not ns_list:
            self.cancel(
                f"No namespaces found on controller {self.ctrl_name}")
        self.id_ns = ns_list[0]
        # Derive the integer namespace ID from the device path
        # e.g. /dev/nvme0n1  →  1
        self.namespace = int(self.id_ns.split("n")[-1])
        self.log.info("Selected namespace: %s (id=%d)",
                      self.id_ns, self.namespace)

        smm = SoftwareManager()
        self.package = self.params.get('package', default='distro')
        if self.package == 'upstream':
            if not smm.check_installed("meson") and not smm.install("meson"):
                self.cancel('meson is needed for the test to be run')
            locations = [
                "https://github.com/linux-nvme/nvme-cli/archive/master.zip"
            ]
            tarball = self.fetch_asset("nvme-cli.zip", locations=locations,
                                       expire='15d')
            archive.extract(tarball, self.teststmpdir)
            os.chdir(f"{self.teststmpdir}/nvme-cli-master")
            process.system("meson setup --force-fallback-for=libnvme .build",
                           ignore_status=True)
            process.system("meson compile -C .build", ignore_status=True)
            self.binary = './.build/nvme'
        else:
            if (not smm.check_installed("nvme-cli")
                    and not smm.install("nvme-cli")):
                self.cancel('nvme-cli is needed for the test to be run')
            self.binary = 'nvme'

        if not self._is_dsm_supported():
            self.cancel("Data Set Management is not supported on this device")

        # Confirm the block device path is actually exposed by the kernel
        if process.system(f'ls {self.id_ns}', ignore_status=True):
            self.cancel(
                f"Namespace block device {self.id_ns} does not exist")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _is_dsm_supported(self):
        """
        Return True if the controller advertises Dataset Management support.

        Two strategies are tried in order, stopping as soon as one succeeds:

        1. JSON output (``id-ctrl -o json``): reads the ``oncs`` field and
           checks bit 2 (0x4 = Dataset Management Supported, NVMe spec).
           Skipped when the command exits non-zero (json-c absent in the
           nvme-cli build → "Invalid output format").

        2. Human-readable output (``id-ctrl -H``): checks for either of the
           two annotation strings nvme-cli versions print for oncs bit 2:
             - distro  (older) : ``Data Set Management Supported``
             - upstream (3.x)  : ``Dataset Management Support Variants``
        """
        # Strategy 1: JSON + oncs bitmask (only when json-c is available)
        result = process.run(
            f"{self.binary} id-ctrl {self.device} -o json",
            shell=True, ignore_status=True)
        if result.exit_status == 0:
            raw = result.stdout.decode("utf-8")
            self.log.info("id-ctrl -o json output: %s", raw[:200])
            try:
                oncs = json.loads(raw).get("oncs", 0)
                self.log.info("oncs from json: 0x%x", oncs)
                if oncs & 0x4:
                    return True
            except json.JSONDecodeError:
                pass
        else:
            self.log.info("id-ctrl -o json not supported (json-c absent);"
                          " falling back to -H text check")

        # Strategy 2: human-readable (-H) annotation string check.
        # distro nvme-cli  : "[2:2] : 0x1  Data Set Management Supported"
        # upstream 3.x     : "[2:2] : 0x1  Dataset Management Support Variants"
        id_ctrl_h = process.system_output(
            f"{self.binary} id-ctrl {self.device} -H",
            shell=True, ignore_status=True).decode("utf-8")
        self.log.info("id-ctrl -H output (first 500 chars): %s",
                      id_ctrl_h[:500])
        return ("Data Set Management Supported" in id_ctrl_h
                or "Dataset Management Support" in id_ctrl_h)

    def _validate_ns_accessible(self):
        """Fail the test if the namespace block device is not accessible."""
        if process.system(f'ls -la {self.id_ns}', shell=True,
                          ignore_status=True):
            self.fail(f"Namespace {self.id_ns} is not accessible")

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_dsm(self):
        """
        Issue the NVMe Dataset Management command and verify the namespace
        remains accessible and functional afterwards.

        The command exercises:
          -a 1  : 1 range entry
          -b 1  : block count = 1
          -s 1  : starting LBA = 1
          -d    : Attribute Deallocate
          -w    : Attribute Write (hint)
          -r    : Attribute Read (hint)
          -t    : timeout in milliseconds (from dsm_timeout param)

        Steps:
          1. Validate namespace block device is accessible.
          2. Issue: nvme dsm <ns> -a 1 -b 1 -s 1 -d -w -r -t <timeout>
          3. Validate return code is 0 (command succeeded).
          4. Validate namespace is still accessible and listed.
          5. Issue a read to confirm I/O is functional after DSM.
        """
        self._validate_ns_accessible()
        block_size = nvme.get_block_size(self.ctrl_name, shared_ns=self.shared)

        dsm_cmd = (f"{self.binary} dsm {self.id_ns}"
                   f" -a 1 -b 1 -s 1 -d -w -r -t {self.dsm_timeout}")
        self.log.info("DSM command: %s", dsm_cmd)
        ret = process.system(dsm_cmd, ignore_status=True, shell=True)
        if ret:
            self.fail(f"NVMe DSM command failed on {self.id_ns}"
                      f" (exit code {ret})")
        self.log.info("DSM command succeeded on %s", self.id_ns)

        # Validation 1: namespace block device must still be accessible
        self._validate_ns_accessible()
        self.log.info("Validation OK: namespace %s accessible after DSM",
                      self.id_ns)

        # Validation 2: namespace must still be listed by the controller
        if not nvme.is_ns_exists(self.ctrl_name, self.namespace):
            self.fail(f"Namespace {self.namespace} missing from"
                      f" {self.ctrl_name} after DSM")
        self.log.info(
            "Validation OK: namespace %d present in controller list after DSM",
            self.namespace)

        # Validation 3: read I/O must succeed after DSM
        read_cmd = (f"{self.binary} read {self.id_ns}"
                    f" -z {block_size}")
        ret = process.system(read_cmd, timeout=60, ignore_status=True,
                             shell=True)
        if ret:
            self.fail(f"Read after DSM failed on {self.id_ns}"
                      f" (exit code {ret})")
        self.log.info("Validation OK: read after DSM succeeded on %s",
                      self.id_ns)
        self.log.info("Dataset Management test passed on %s", self.id_ns)

    def test_dsm_cdw11(self):
        """
        Issue the NVMe Dataset Management command using raw DWORD 11
        (--cdw11) instead of individual attribute flags, and verify the
        namespace remains accessible and functional afterwards.

        DWORD 11 bit layout (NVMe spec, Figure 210):
          Bit 0 : Attribute Deallocate (AD)
          Bit 1 : Attribute Integral Dataset for Write (IDW)
          Bit 2 : Attribute Integral Dataset for Read (IDR)

        Value 0x7 (binary 111) sets all three attributes simultaneously,
        which is equivalent to passing -d -w -r as individual flags.

        The command exercises:
          -a 1       : 1 range entry
          -b 1       : block count = 1
          -s 1       : starting LBA = 1
          -c 0x7     : DWORD 11 = 0x7 (AD + IDW + IDR)
          -t <ms>    : timeout in milliseconds (from dsm_timeout param)

        Steps:
          1. Validate namespace block device is accessible.
          2. Issue: nvme dsm <ns> -a 1 -b 1 -s 1 -c 0x7 -t <timeout>
          3. Validate return code is 0 (command succeeded).
          4. Validate namespace is still accessible and listed.
          5. Issue a read to confirm I/O is functional after DSM.
        """
        self._validate_ns_accessible()
        block_size = nvme.get_block_size(self.ctrl_name, shared_ns=self.shared)

        dsm_cmd = (f"{self.binary} dsm {self.id_ns}"
                   f" -a 1 -b 1 -s 1 -c 0x7 -t {self.dsm_timeout}")
        self.log.info("DSM cdw11 command: %s", dsm_cmd)
        ret = process.system(dsm_cmd, ignore_status=True, shell=True)
        if ret:
            self.fail(f"NVMe DSM cdw11 command failed on {self.id_ns}"
                      f" (exit code {ret})")
        self.log.info("DSM cdw11 command succeeded on %s", self.id_ns)

        # Validation 1: namespace block device must still be accessible
        self._validate_ns_accessible()
        self.log.info(
            "Validation OK: namespace %s accessible after DSM cdw11",
            self.id_ns)

        # Validation 2: namespace must still be listed by the controller
        if not nvme.is_ns_exists(self.ctrl_name, self.namespace):
            self.fail(f"Namespace {self.namespace} missing from"
                      f" {self.ctrl_name} after DSM cdw11")
        self.log.info(
            "Validation OK: namespace %d present in controller list"
            " after DSM cdw11", self.namespace)

        # Validation 3: read I/O must succeed after DSM
        read_cmd = (f"{self.binary} read {self.id_ns}"
                    f" -z {block_size}")
        ret = process.system(read_cmd, timeout=60, ignore_status=True,
                             shell=True)
        if ret:
            self.fail(f"Read after DSM cdw11 failed on {self.id_ns}"
                      f" (exit code {ret})")
        self.log.info("Validation OK: read after DSM cdw11 succeeded on %s",
                      self.id_ns)
        self.log.info("Dataset Management cdw11 test passed on %s", self.id_ns)
