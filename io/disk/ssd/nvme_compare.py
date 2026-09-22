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
NVMe Compare Test.

Writes a known pattern to a namespace then issues the NVMe Compare
command to verify that the data on the media matches the host buffer.
Requires the device to advertise 'Compare Supported' in id-ctrl.
"""

import os
from avocado import Test
from avocado.utils import disk
from avocado.utils import process
from avocado.utils import archive
from avocado.utils import nvme
from avocado.utils.software_manager.manager import SoftwareManager


class NVMeCompare(Test):
    """
    NVMe Compare Test.

    :param device: Name of the nvme device (e.g. nvme0, or subsystem NQN)
    :param namespace: Namespace number to use (default '1')
    :param shared_namespaces: True if the namespace is shared (default False)
    :param package: 'distro' (default) or 'upstream' to build nvme-cli
    """

    def _build_upstream_binary(self):
        """
        Build nvme-cli from the upstream GitHub master branch.
        Returns the absolute path to the compiled binary, or cancels.
        """
        smm = SoftwareManager()
        if not smm.check_installed("meson") and not smm.install("meson"):
            self.cancel('meson is needed for the test to be run')
        locations = [
            "https://github.com/linux-nvme/nvme-cli/archive/master.zip"
        ]
        tarball = self.fetch_asset("nvme-cli.zip", locations=locations,
                                   expire='15d')
        archive.extract(tarball, self.teststmpdir)
        build_dir = f"{self.teststmpdir}/nvme-cli-master"
        os.chdir(build_dir)
        if process.system("meson setup --force-fallback-for=libnvme .build",
                          ignore_status=True):
            self.cancel('meson setup failed for upstream nvme-cli build')
        if process.system("meson compile -C .build", ignore_status=True):
            self.cancel('meson compile failed for upstream nvme-cli build')
        binary = os.path.join(build_dir, '.build', 'nvme')
        if not os.path.isfile(binary):
            self.cancel(
                f'upstream nvme binary not found after build: {binary}')
        return binary

    def setUp(self):
        """
        Install nvme-cli, resolve the device path, and verify Compare support.
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
        self.namespace = self.params.get('namespace', default='1')
        self.id_ns = f"{self.device}n{self.namespace}"

        package = self.params.get('package', default='distro')
        if package == 'upstream':
            self.binary = self._build_upstream_binary()
        else:
            smm = SoftwareManager()
            if not smm.check_installed("nvme-cli") and \
                    not smm.install("nvme-cli"):
                self.cancel('nvme-cli is needed for the test to be run')
            self.binary = 'nvme'

        # Block size is the transfer length used for write and compare
        self.block_size = nvme.get_block_size(self.ctrl_name,
                                              shared_ns=self.shared)

        # Verify Compare command is supported via the ONCS bitmask.
        # Bit 0 of the Optional NVM Command Support (oncs) field indicates
        # Compare support (NVMe spec section 5.15.2.1).
        # Parsing the raw 'oncs' value is more reliable than matching the
        # human-readable -H output, which varies between nvme-cli versions
        # (older distro builds may print capability names unconditionally).
        id_ctrl_raw = process.system_output(
            f"{self.binary} id-ctrl {self.device}",
            shell=True).decode("utf-8")
        oncs_value = None
        for line in id_ctrl_raw.splitlines():
            if line.strip().startswith("oncs"):
                try:
                    oncs_value = int(line.split(":")[1].strip(), 0)
                except (IndexError, ValueError):
                    pass
                break
        if oncs_value is None or not oncs_value & 0x1:
            self.cancel("Compare command is not supported on this device")

        # Validate namespace device path exists
        if process.system(f'ls {self.id_ns}', ignore_status=True):
            self.cancel(
                f"Namespace device {self.id_ns} does not exist. "
                "Ensure the namespace is created before running this test.")

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_compare(self):
        """
        Write a data pattern to the namespace and compare it back.

        Steps:
          1. Validate namespace device path is accessible.
          2. Write one block of data using: echo 1 | nvme write <ns> -z <bs> -t
          3. Validate write return code is 0.
          4. Compare the same block: echo 1 | nvme compare <ns> -z <bs>
          5. Validate compare return code is 0 (data matches).

        A non-zero compare return code means the device-resident data
        does NOT match the host buffer, which is a data integrity failure.
        """
        # Validate namespace accessibility before I/O
        if process.system(f'ls -la {self.id_ns}', shell=True,
                          ignore_status=True):
            self.fail(f"Namespace {self.id_ns} is not accessible")

        # Step 1: Write a known pattern (nvme-cli reads data from stdin when
        # no -d flag is given; -t outputs latency statistics)
        write_cmd = (f'echo 1|{self.binary} write {self.id_ns}'
                     f' -z {self.block_size} -t')
        self.log.info("Write command: %s", write_cmd)
        ret = process.system(write_cmd, timeout=300, ignore_status=True,
                             shell=True)
        if ret:
            self.fail(f"Write failed on {self.id_ns} before compare"
                      f" (exit code {ret})")
        self.log.info("Write step succeeded on %s", self.id_ns)

        # Step 2: Compare the written data (nvme compare also reads the
        # host buffer from stdin when no -d flag is given)
        compare_cmd = (f'echo 1|{self.binary} compare {self.id_ns}'
                       f' -z {self.block_size}')
        self.log.info("Compare command: %s", compare_cmd)
        ret = process.system(compare_cmd, timeout=300, ignore_status=True,
                             shell=True)
        if ret:
            self.fail(f"Compare failed on {self.id_ns} — data mismatch"
                      f" detected (exit code {ret})")

        self.log.info("Compare test passed: data on %s matches host buffer",
                      self.id_ns)
