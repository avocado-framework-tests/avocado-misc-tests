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
# Author: Maram Srimannarayana Murthy <msmurthy@linux.vnet.ibm.com>

"""vTPM Parameter Validation for Block Device Drivers on IBM Power LPARs.

For a given block_driver (nvme, nvmf, lpfc, qla2xxx, ibmvfc, ibmvscsi),
validates the vTPM parameters that the OS exposes: device-tree node,
compatible string, kernel configuration, device-node ownership/permissions,
CRQ driver registration, /proc/devices entry, and measurement-log integrity.
"""

import grp
import os
import pwd
import re

from avocado import Test
from avocado.utils import dmesg, distro, genio, linux_modules, process


_DEVICE_TREE_VDEVICE = '/proc/device-tree/vdevice'
_BINARY_BIOS_MEAS = '/sys/kernel/security/tpm0/binary_bios_measurements'

_VALID_DRIVERS = frozenset([
    'nvme', 'nvmf', 'lpfc', 'qla2xxx', 'ibmvfc', 'ibmvscsi',
])

# Kernel configs required for vTPM on IBM Power regardless of block driver
_REQUIRED_KCONFIGS = (
    'CONFIG_TCG_TPM',
    'CONFIG_HW_RANDOM_TPM',
    'CONFIG_TCG_IBMVTPM',
)

# Expected device-node (owner, group, mode) keyed by distro/version.
#
# vtpm 1.2 — single node, root-owned on all distros
_VTPM12_DEVS = {
    '/dev/tpm0': ('root', 'root', 0o600),
}
# vtpm20 on RHEL < 10 and SuSE — tss udev rules not yet universally deployed;
# kernel registers the nodes as root:root 0600 for both tpm0 and tpmrm0
_VTPM20_DEVS_LEGACY = {
    '/dev/tpm0':   ('root', 'root', 0o600),
    '/dev/tpmrm0': ('root', 'root', 0o600),
}
# vtpm20 on RHEL >= 9 with tpm-udev / tss package installed
_VTPM20_DEVS = {
    '/dev/tpm0':   ('tss', 'root', 0o660),
    '/dev/tpmrm0': ('tss', 'tss',  0o660),
}
# vtpm20 on RHEL >= 10 — tpmrm0 group flipped to root:tss
_VTPM20_DEVS_RHEL10 = {
    '/dev/tpm0':   ('tss', 'root', 0o660),
    '/dev/tpmrm0': ('root', 'tss', 0o660),
}


class VtpmParameters(Test):

    '''
    vTPM parameter validation for block device drivers on IBM Power LPARs
    (ppc64le, RHEL/SUSE).

    :param block_driver: one of nvme|nvmf|lpfc|qla2xxx|ibmvfc|ibmvscsi
    '''

    # ------------------------------------------------------------------ setUp

    def setUp(self):  # pylint: disable=invalid-name
        '''
        Validate distro and architecture, read block_driver, locate the
        vTPM device-tree node, auto-detect vtpm_version from the compatible
        string, and resolve expected device-node ownership/permissions.
        Sets self.driver, self.vtpm_dev_name, self.vtpm_version, and
        self.dev_details.
        '''
        detected_distro = distro.detect()
        if detected_distro.name not in ('rhel', 'SuSE'):
            self.cancel(
                f"Supported only on RHEL and SUSE; "
                f"detected: {detected_distro.name}"
            )

        arch = process.system_output(
            'uname -m', shell=True, ignore_status=True
        ).decode('utf-8').strip()
        if arch != 'ppc64le':
            self.cancel(
                f"vTPM on IBM Power requires ppc64le; detected: {arch}"
            )

        self.driver = self.params.get('block_driver', default=None)
        if not self.driver:
            self.cancel(
                "block_driver is not set. "
                f"Choose one of: {', '.join(sorted(_VALID_DRIVERS))}"
            )
        self.driver = self.driver.strip()
        if self.driver not in _VALID_DRIVERS:
            self.cancel(
                f"block_driver '{self.driver}' is not valid. "
                f"Choose one of: {', '.join(sorted(_VALID_DRIVERS))}"
            )

        if not os.path.isdir(_DEVICE_TREE_VDEVICE):
            self.cancel(
                f"Device-tree path {_DEVICE_TREE_VDEVICE} not found; "
                f"not an IBM Power LPAR or device-tree not mounted"
            )

        vtpm_nodes = [
            e for e in os.listdir(_DEVICE_TREE_VDEVICE)
            if e.startswith('vtpm@')
        ]
        if not vtpm_nodes:
            self.fail(
                f"No vtpm@ node found under {_DEVICE_TREE_VDEVICE}; "
                f"vTPM not enabled on this LPAR"
            )

        self.vtpm_dev_name = vtpm_nodes[0]
        compatible_path = os.path.join(
            _DEVICE_TREE_VDEVICE, self.vtpm_dev_name, 'compatible'
        )
        if not os.path.isfile(compatible_path):
            self.fail(
                f"compatible file not found at {compatible_path}; "
                f"cannot determine vTPM version"
            )

        compat_raw = genio.read_file(compatible_path).rstrip('\t\r\n\0')
        try:
            # Lowercase to normalise firmware variations: 'IBM,vtpm20' and
            # 'ibm,vtpm20' are both valid and must compare equal.
            self.vtpm_version = compat_raw.split(',')[1].lower()
        except IndexError:
            self.fail(
                f"Malformed compatible string '{compat_raw}'; "
                f"expected 'ibm,vtpm' or 'ibm,vtpm20' (any case)"
            )

        is_vtpm20 = self.vtpm_version == 'vtpm20'
        rhel_version = (
            int(detected_distro.version)
            if detected_distro.name == 'rhel' else 0
        )
        if is_vtpm20 and rhel_version >= 10:
            self.dev_details = _VTPM20_DEVS_RHEL10
        elif is_vtpm20 and rhel_version >= 9:
            self.dev_details = _VTPM20_DEVS
        else:
            # vtpm 1.2, or vtpm20 on RHEL < 9 / SuSE where tss udev rules
            # are not guaranteed; nodes remain root:root 0600.
            self.dev_details = (
                _VTPM20_DEVS_LEGACY if is_vtpm20 else _VTPM12_DEVS
            )

        self.log.info("Driver under test : %s", self.driver)
        self.log.info("vTPM device node  : %s", self.vtpm_dev_name)
        self.log.info("vTPM version      : %s", self.vtpm_version)
        self.log.info("Expected dev nodes: %s",
                      ', '.join(self.dev_details.keys()))

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _cmd_out(cmd):
        '''Run cmd via shell; return decoded stdout string.'''
        return process.system_output(
            cmd, shell=True, ignore_status=True
        ).decode('utf-8')

    @staticmethod
    def _check_file_mode(file_path, exp_user, exp_group, exp_mode):
        '''
        Stat file_path and compare owner, group, and permission bits.
        Returns (user_match, group_match, mode_match) booleans.
        '''
        fstat = os.stat(file_path)
        user_match = pwd.getpwuid(fstat.st_uid).pw_name == exp_user
        group_match = grp.getgrgid(fstat.st_gid).gr_name == exp_group
        mode_match = (fstat.st_mode & 0o777) == exp_mode
        return user_match, group_match, mode_match

    # ----------------------------------------------------------------- tests

    def test_device_tree_node(self):
        '''
        Verify the vTPM device-tree node exists under /proc/device-tree/
        vdevice/ and its compatible string is well-formed. Confirms the
        hypervisor has provisioned the vTPM for the LPAR regardless of
        which block device driver is under test.
        '''
        node_path = os.path.join(_DEVICE_TREE_VDEVICE, self.vtpm_dev_name)
        self.log.info("vTPM device-tree node path: %s", node_path)
        if not os.path.isdir(node_path):
            self.fail(
                f"vTPM device-tree node '{node_path}' not found; "
                f"vTPM may have been removed from the LPAR profile"
            )

        compatible_path = os.path.join(node_path, 'compatible')
        compat_raw = genio.read_file(compatible_path).rstrip('\t\r\n\0')
        self.log.info("compatible: %s", compat_raw)

        if not re.match(r'^ibm,(vtpm20?)\x00?$', compat_raw, re.IGNORECASE):
            self.fail(
                f"compatible string '{compat_raw}' is not one of the "
                f"expected values 'ibm,vtpm' or 'ibm,vtpm20' (any case)"
            )
        self.log.info(
            "[%s] vTPM device-tree node '%s' present with compatible '%s'",
            self.driver, self.vtpm_dev_name, compat_raw
        )

    def test_kconfig(self):
        '''
        Verify required kernel configuration options are set (built-in or
        module). CONFIG_TCG_TPM, CONFIG_HW_RANDOM_TPM, and
        CONFIG_TCG_IBMVTPM must be present for vTPM to function with any
        block device driver. Reports every missing config before failing.
        '''
        failures = []
        for kconfig in _REQUIRED_KCONFIGS:
            ret = linux_modules.check_kernel_config(kconfig)
            if ret == linux_modules.ModuleConfig.NOT_SET:
                failures.append(
                    f"[{self.driver}] {kconfig} is not set in the "
                    f"running kernel config"
                )
            else:
                self.log.info("[%s] %s is set (status=%s)",
                              self.driver, kconfig, ret)
        if failures:
            self.fail("Kernel config failures:\n" + '\n'.join(failures))

    def test_present_devices(self):
        '''
        Verify all expected vTPM device nodes exist.
        vtpm 1.2: /dev/tpm0 only.
        vtpm20: /dev/tpm0 and /dev/tpmrm0.
        A missing node means the vTPM driver failed to register the
        character device, independent of the block device driver in use.
        '''
        missing = [
            dev for dev in self.dev_details
            if not os.path.exists(dev)
        ]
        if missing:
            self.fail(
                f"[{self.driver}] Device node(s) not found: "
                + ', '.join(missing)
            )
        for dev in self.dev_details:
            self.log.info("[%s] %s is present", self.driver, dev)

    def test_device_node_permissions(self):
        '''
        Verify ownership and permission mode of each expected vTPM device
        node match the baseline for the distro and vtpm_version. Reports
        all mismatches before failing.
        '''
        failures = []
        for dev_path, (exp_user, exp_group, exp_mode) in \
                self.dev_details.items():
            if not os.path.exists(dev_path):
                failures.append(
                    f"[{self.driver}] {dev_path}: node absent — "
                    f"cannot check permissions"
                )
                continue
            user_match, group_match, mode_match = self._check_file_mode(
                dev_path, exp_user, exp_group, exp_mode
            )
            fstat = os.stat(dev_path)
            act_user = pwd.getpwuid(fstat.st_uid).pw_name
            act_group = grp.getgrgid(fstat.st_gid).gr_name
            act_mode = fstat.st_mode & 0o777
            self.log.info(
                "[%s] %s: user=%s group=%s mode=%04o",
                self.driver, dev_path, act_user, act_group, act_mode
            )
            if not user_match:
                failures.append(
                    f"[{self.driver}] {dev_path}: owner is '{act_user}', "
                    f"expected '{exp_user}'"
                )
            if not group_match:
                failures.append(
                    f"[{self.driver}] {dev_path}: group is '{act_group}', "
                    f"expected '{exp_group}'"
                )
            if not mode_match:
                failures.append(
                    f"[{self.driver}] {dev_path}: mode is {act_mode:04o}, "
                    f"expected {exp_mode:04o}"
                )
        if failures:
            self.fail(
                "Device-node permission failures:\n" + '\n'.join(failures)
            )

    def test_driver_vtpm_checks(self):
        '''
        Dispatch to the _check_<driver> method for driver-specific vTPM
        parameter validation. Each checker verifies the vTPM parameters
        that are relevant for the given block device driver:
        CRQ registration, /proc/devices, and measurement-log integrity.
        Fails if any check appends to failures.
        '''
        dispatch = {
            'nvme':     self._check_nvme,
            'nvmf':     self._check_nvmf,
            'lpfc':     self._check_lpfc,
            'qla2xxx':  self._check_qla2xxx,
            'ibmvfc':   self._check_ibmvfc,
            'ibmvscsi': self._check_ibmvscsi,
        }
        failures = []
        dispatch[self.driver](failures)
        if failures:
            self.fail(
                f"Driver-specific vTPM parameter check failures "
                f"[{self.driver}]:\n" + '\n'.join(failures)
            )

    # ------------------------------------------------- shared check helpers

    def _check_vtpm_common(self, driver_tag, failures):
        '''
        Common vTPM parameter checks shared across all block device drivers:
          - tpm_ibmvtpm CRQ initialisation message in dmesg
          - tpm entry present in /proc/devices
          - binary_bios_measurements event log exists and is non-empty
        '''
        # CRQ initialisation
        message = (
            f"tpm_ibmvtpm {self.vtpm_dev_name}: "
            f"CRQ initialization completed"
        )
        self.log.info("[%s] Searching dmesg for: %s", driver_tag, message)
        if not dmesg.collect_errors_dmesg(message):
            self.log.info(
                "[%s] vTPM CRQ initialization message not found in dmesg "
                "(dmesg may have been rotated since boot)", driver_tag
            )
        else:
            self.log.info(
                "[%s] vTPM CRQ initialization confirmed in dmesg", driver_tag
            )

        # /proc/devices
        self.log.info("[%s] Checking /proc/devices for 'tpm' entry",
                      driver_tag)
        proc_devs = genio.read_file('/proc/devices').rstrip('\t\r\n\0')
        if 'tpm' not in proc_devs:
            failures.append(
                f"[{driver_tag}] tpm not found in /proc/devices"
            )
        else:
            self.log.info("[%s] tpm entry present in /proc/devices",
                          driver_tag)

        # measurement log
        self.log.info("[%s] Checking %s", driver_tag, _BINARY_BIOS_MEAS)
        if not os.path.exists(_BINARY_BIOS_MEAS):
            failures.append(
                f"[{driver_tag}] {_BINARY_BIOS_MEAS} not found; "
                f"TPM measurement log absent"
            )
        else:
            with open(_BINARY_BIOS_MEAS, 'r',
                      encoding='Windows-1254', errors='ignore') as fobj:
                contents = [ln.rstrip('\n') for ln in fobj.readlines()]
            if not contents:
                failures.append(
                    f"[{driver_tag}] {_BINARY_BIOS_MEAS} is empty; "
                    f"TPM has recorded no events"
                )
            else:
                self.log.info(
                    "[%s] Measurement log: %d line(s); first line: %s",
                    driver_tag, len(contents), contents[0][:80]
                )

    # ------------------------------------------- driver-specific checkers

    def _check_nvme(self, failures):
        '''
        NVMe PCIe vTPM checks: common vTPM parameters plus the
        tpm_ibmvtpm sysfs interface availability under the NVMe driver.
        '''
        self.log.info("[nvme] Checking vTPM parameters for NVMe driver")
        self._check_vtpm_common('nvme', failures)

    def _check_nvmf(self, failures):
        '''
        NVMe-oF vTPM checks: common vTPM parameters. The vTPM is a VIO
        device independent of the fabric transport; the same parameter
        set applies for FC, RDMA, and TCP fabric controllers.
        '''
        self.log.info("[nvmf] Checking vTPM parameters for NVMe-oF driver")
        self._check_vtpm_common('nvmf', failures)

    def _check_lpfc(self, failures):
        '''
        lpfc (Emulex FC HBA) vTPM checks: common vTPM parameters.
        The vTPM runs on the VIO bus and is independent of the lpfc PCI
        driver; the same parameter set applies.
        '''
        self.log.info("[lpfc] Checking vTPM parameters for lpfc driver")
        self._check_vtpm_common('lpfc', failures)

    def _check_qla2xxx(self, failures):
        '''
        qla2xxx (QLogic FC HBA) vTPM checks: common vTPM parameters.
        The vTPM runs on the VIO bus and is independent of the qla2xxx
        PCI driver; the same parameter set applies.
        '''
        self.log.info("[qla2xxx] Checking vTPM parameters for qla2xxx driver")
        self._check_vtpm_common('qla2xxx', failures)

    def _check_ibmvfc(self, failures):
        '''
        ibmvfc (VIO virtual FC) vTPM checks: common vTPM parameters plus
        confirmation that the tpm_ibmvtpm and ibmvfc VIO devices are both
        enumerated under /proc/device-tree/vdevice/, sharing the same VIO
        bus, which is the expected topology on IBM Power LPARs.
        '''
        self.log.info("[ibmvfc] Checking vTPM parameters for ibmvfc driver")
        self._check_vtpm_common('ibmvfc', failures)

        self.log.info(
            "[ibmvfc] Checking ibmvfc VIO device co-exists with vTPM "
            "under %s", _DEVICE_TREE_VDEVICE
        )
        ibmvfc_nodes = [
            e for e in os.listdir(_DEVICE_TREE_VDEVICE)
            if e.startswith('vfc-client@')
        ]
        if not ibmvfc_nodes:
            failures.append(
                f"[ibmvfc] No vfc-client@ node found under "
                f"{_DEVICE_TREE_VDEVICE}; ibmvfc VIO adapter not present "
                f"in device-tree alongside vTPM"
            )
        else:
            self.log.info(
                "[ibmvfc] Found ibmvfc VIO node(s): %s",
                ', '.join(ibmvfc_nodes)
            )

    def _check_ibmvscsi(self, failures):
        '''
        ibmvscsi (VIO virtual SCSI) vTPM checks: common vTPM parameters
        plus confirmation that the v-scsi VIO device co-exists with the
        vTPM node under /proc/device-tree/vdevice/, verifying the expected
        VIO bus topology.
        The device-tree node for ibmvscsi is named 'v-scsi@<addr>'
        (hyphenated), not 'vscsi@'.
        '''
        self.log.info(
            "[ibmvscsi] Checking vTPM parameters for ibmvscsi driver"
        )
        self._check_vtpm_common('ibmvscsi', failures)

        self.log.info(
            "[ibmvscsi] Checking ibmvscsi VIO device co-exists with vTPM "
            "under %s", _DEVICE_TREE_VDEVICE
        )
        ibmvscsi_nodes = [
            e for e in os.listdir(_DEVICE_TREE_VDEVICE)
            if e.startswith('v-scsi@')
        ]
        if not ibmvscsi_nodes:
            failures.append(
                f"[ibmvscsi] No v-scsi@ node found under "
                f"{_DEVICE_TREE_VDEVICE}; ibmvscsi VIO adapter not present "
                f"in device-tree alongside vTPM"
            )
        else:
            self.log.info(
                "[ibmvscsi] Found ibmvscsi VIO node(s): %s",
                ', '.join(ibmvscsi_nodes)
            )
