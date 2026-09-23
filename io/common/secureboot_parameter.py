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
# Author: Vaishnavi Bhat <vaishnavi@linux.vnet.ibm.com>

"""Secure Boot Validation for Block Devices and NICs on IBM Power LPARs.

Verifies block device / NIC visibility and kernel lockdown enforcement after a
Secure Boot enable transition (ppc64le, RHEL/SUSE).

Block driver values: nvme, nvmf, lpfc, qla2xxx, ibmvfc, ibmvscsi.
NIC: pass interface name or MAC address; driver and type are auto-detected.
"""

import json
import os
import re

from avocado import Test
from avocado.utils import dmesg, distro, genio, linux, process
from avocado.utils import wait
from avocado.utils.network.hosts import LocalHost, RemoteHost
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.software_manager.manager import SoftwareManager


# ── NIC module-level constants ───────────────────────────────────────────────
_VIO_NIC_DRIVERS = frozenset(['ibmvnic', 'ibmveth'])
_VIO_DT_PREFIX = {'ibmvnic': 'vnic@', 'ibmveth': 'l-lan@'}
_DEVICE_TREE_VDEVICE = '/proc/device-tree/vdevice'

# ── Block device module-level constants ──────────────────────────────────────
_SCSI_DRIVERS = frozenset(['lpfc', 'qla2xxx', 'ibmvfc', 'ibmvscsi'])
_FC_HBA_DRIVERS = frozenset(['lpfc', 'qla2xxx'])
_VIO_DRIVERS = frozenset(['ibmvfc', 'ibmvscsi'])
_VALID_DRIVERS = frozenset(['nvme', 'nvmf', 'lpfc', 'qla2xxx',
                            'ibmvfc', 'ibmvscsi'])
_NVME_DRIVERS = frozenset(['nvme', 'nvmf']) | _FC_HBA_DRIVERS
_LOCKDOWN_KEYWORDS = frozenset([
    'permission denied', 'operation not permitted', 'eperm', 'lockdown',
    'invalid command opcode',
])
_FABRIC_TRANSPORTS = frozenset(['fc', 'rdma', 'tcp', 'loop'])
_PCI_ADDR_RE = re.compile(
    r'^[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-9]$', re.IGNORECASE
)


# ── Shared module-level helpers (used by both test classes) ──────────────────

def _check_lockdown_precondition(test_instance):
    '''Module-level helper: read /sys/kernel/security/lockdown, cancel if
    absent or [none]. Returns the active lockdown mode string (e.g.
    "integrity"). Called by both SecureBootBlockDevice and SecureBootNic
    to avoid duplicating the guard logic.
    '''
    lockdown_path = '/sys/kernel/security/lockdown'
    if not genio.is_pattern_in_file(lockdown_path, r'\w'):
        test_instance.cancel(
            'Lockdown sysfs not present; kernel may not support lockdown'
        )
    lockdown_line = genio.read_one_line(lockdown_path)
    test_instance.log.info('lockdown: %s', lockdown_line)
    match = re.search(r'\[(\w+)\]', lockdown_line)
    active_mode = match.group(1) if match else ''
    if active_mode == 'none':
        test_instance.cancel(
            'Kernel lockdown is [none]; Secure Boot not enabled. '
            'Enable Secure Boot on the LPAR and reboot before running'
        )
    return active_mode


def _test_lockdown_state(test_instance):
    '''Module-level helper: verify lockdown=integrity and IBM DT
    secure-boot=2. Called by both SecureBootBlockDevice.test_lockdown_state
    and SecureBootNic.test_lockdown_state to avoid code duplication.
    '''
    active_mode = _check_lockdown_precondition(test_instance)

    test_instance.log.info(
        'Checking OS-level Secure Boot state via '
        'linux.is_os_secureboot_enabled()'
    )
    try:
        sb_enabled = linux.is_os_secureboot_enabled()
    except linux.UnsupportedMachineError as exc:
        test_instance.cancel(
            'lsprop not available on this machine: %s' % exc
        )
    test_instance.log.info(
        'linux.is_os_secureboot_enabled() = %s', sb_enabled
    )

    failures = []
    if active_mode != 'integrity':
        failures.append(
            'lockdown: expected [integrity], got [%s]' % active_mode
        )
    if not sb_enabled:
        failures.append(
            "DT ibm,secure-boot: '00000002' not found; "
            'secure_boot=2 may not have taken effect'
        )
    if failures:
        test_instance.fail('Kernel lockdown state failures:\n'
                           + '\n'.join(failures))


class SecureBootBlockDevice(Test):

    '''
    Secure Boot parameter validation for block device stacks on IBM Power
    LPARs (RHEL/SUSE).

    :param block_driver: one of nvme|nvmf|lpfc|qla2xxx|ibmvfc|ibmvscsi
    '''

    # ------------------------------------------------------------------ setUp

    def setUp(self):
        '''
        Validate distro, read block_driver, check required tools, and
        populate self.block_devices with discovered device paths.
        Sets self.driver, self.block_devices, and self.nvmf_details.
        '''
        detected_distro = distro.detect()
        if detected_distro.name not in ('rhel', 'SuSE'):
            self.cancel(
                f"Supported only on RHEL and SUSE; "
                f"detected: {detected_distro.name}"
            )

        self.driver = self.params.get('block_driver', default=None)
        if not self.driver:
            self.cancel(
                "block_driver is not set. "
                "Choose one of: " + ', '.join(sorted(_VALID_DRIVERS))
            )
        self.driver = self.driver.strip()
        if self.driver not in _VALID_DRIVERS:
            self.cancel(
                f"block_driver '{self.driver}' is not valid. "
                f"Choose one of: {', '.join(sorted(_VALID_DRIVERS))}"
            )

        if self.driver in _NVME_DRIVERS:
            if process.system('command -v nvme',
                              shell=True, ignore_status=True):
                self.cancel("nvme-cli not found; install nvme-cli and re-run")

        self.nvmf_details = []
        self.block_devices = self._discover_devices()

        if not self.block_devices:
            self.cancel(
                f"No block devices found for driver '{self.driver}'"
            )

        self.log.info("Driver under test  : %s", self.driver)
        self.log.info("Block devices found: %s",
                      ', '.join(self.block_devices))

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _cmd_out(cmd):
        '''Run cmd via shell; return decoded stdout string.'''
        return process.system_output(
            cmd, shell=True, ignore_status=True
        ).decode('utf-8')

    @staticmethod
    def _run_cmd(cmd):
        '''Run cmd via shell; return (result, combined_lower) tuple.'''
        result = process.run(cmd, shell=True, ignore_status=True)
        combined = (result.stdout + result.stderr).decode('utf-8').lower()
        return result, combined

    @staticmethod
    def _is_blocked_by_lockdown(combined_output):
        '''Return True if combined_output contains a lockdown keyword.'''
        return any(kw in combined_output for kw in _LOCKDOWN_KEYWORDS)

    @staticmethod
    def _unique(items):
        '''Return a deduplicated list preserving insertion order.'''
        return list(dict.fromkeys(items))

    def _nvme_devs(self):
        '''Return block devices whose basename starts with "nvme".'''
        return [d for d in self.block_devices
                if os.path.basename(d).startswith('nvme')]

    def _scsi_devs(self):
        '''Return block devices whose basename starts with "sd".'''
        return [d for d in self.block_devices
                if os.path.basename(d).startswith('sd')]

    @staticmethod
    def _nvme_ctrl_transport(ctrl):
        '''Read transport from sysfs; return "pcie", "fc", "tcp", etc.'''
        name = os.path.basename(ctrl)
        transport_path = f'/sys/class/nvme/{name}/transport'
        if os.path.isfile(transport_path):
            return genio.read_one_line(transport_path).strip().lower()
        return 'pcie'

    def _pcie_nvme_devs(self):
        '''Return only PCIe-attached NVMe controllers from block_devices.'''
        return [d for d in self._nvme_devs()
                if self._nvme_ctrl_transport(d) == 'pcie']

    # -------------------------------------------------------------- discovery

    def _discover_devices(self):
        '''
        Dispatch to the appropriate discovery helper based on self.driver.
        Returns a deduplicated list of /dev/... device paths.
        '''
        dispatch = {
            'nvme': self._discover_nvme_pcie,
            'nvmf': self._discover_nvmf,
        }
        if self.driver in dispatch:
            return dispatch[self.driver]()
        if self.driver in _FC_HBA_DRIVERS:
            return self._discover_by_pci_driver(self.driver)
        if self.driver in _VIO_DRIVERS:
            return self._discover_by_vio_driver(self.driver)
        return []

    def _nvme_subsys_json(self):
        '''
        Return parsed output of 'nvme list-subsys -o json', or an empty
        list when the command is not available or returns no output.
        '''
        raw = self._cmd_out('nvme list-subsys -o json').strip()
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except ValueError:
            self.log.warning("Could not parse nvme list-subsys JSON output")
            return []
        # nvme-cli 2.x dict: {"Subsystems": [...]}
        if isinstance(data, dict):
            return data.get('Subsystems', [])
        # nvme-cli 2.x list: [{"HostNQN":..., "Subsystems": [...]}, ...]
        # nvme-cli 1.x list: [{"NQN":..., "Paths": [...]}, ...]
        # Distinguish by checking whether the first element has "Subsystems".
        if isinstance(data, list) and data:
            if 'Subsystems' in data[0]:
                subsystems = []
                for host in data:
                    subsystems.extend(host.get('Subsystems', []))
                return subsystems
            return data
        return []

    def _nvme_ctrl_name(self, name):
        '''Strip namespace suffix from an NVMe device name string.'''
        return re.sub(r'n\d+$', '', '/dev/' + name.split('/')[-1])

    def _discover_nvme_pcie(self):
        '''
        Return /dev/nvmeX PCIe-attached controllers (transport=pcie) that
        have at least one namespace visible in nvme list. Controllers with
        no namespaces are excluded — there is nothing to validate.
        '''
        # Build the set of controllers that have namespaces in nvme list.
        # nvme list lines start with /dev/nvmeXnY; strip the namespace suffix
        # to get the controller name (e.g. /dev/nvme5n1 -> /dev/nvme5).
        nvme_list_out = self._cmd_out('nvme list')
        ctrls_with_ns = self._unique(
            re.sub(r'n\d+$', '', line.split()[0])
            for line in nvme_list_out.splitlines()
            if line.startswith('/dev/nvme')
        )

        candidates = []
        for subsys in self._nvme_subsys_json():
            entries = (subsys.get('Paths', [])
                       + subsys.get('Controllers', []))
            for entry in entries:
                if entry.get('Transport', '').lower() not in ('pcie', ''):
                    continue
                name = entry.get('Name', '')
                if name:
                    candidates.append(self._nvme_ctrl_name(name))

        if candidates:
            # Keep only those that have at least one namespace.
            devices = [d for d in self._unique(candidates)
                       if d in ctrls_with_ns]
            if devices:
                return devices
            self.log.info(
                "nvme list-subsys PCIe candidates %s have no namespaces; "
                "falling back to nvme list", candidates
            )

        self.log.info("nvme list-subsys JSON yielded no PCIe controllers; "
                      "falling back to nvme list")
        return ctrls_with_ns

    def _discover_nvmf(self):
        '''
        Return /dev/nvmeX controllers that are NVMe-oF (transport != pcie).
        Populates self.nvmf_details with per-controller fabric metadata.
        '''
        devices = []
        for subsys in self._nvme_subsys_json():
            nqn = subsys.get('NQN', '')
            # nvme-cli 2.x uses 'Paths'; nvme-cli 1.x uses 'Controllers'
            entries = subsys.get('Paths', []) + subsys.get('Controllers', [])
            for entry in entries:
                transport = entry.get('Transport', '').lower()
                if transport not in _FABRIC_TRANSPORTS:
                    continue
                name = entry.get('Name', '')
                if not name:
                    continue
                dev = self._nvme_ctrl_name(name)
                if dev not in devices:
                    devices.append(dev)
                    self.nvmf_details.append({
                        'dev': dev,
                        'nqn': nqn,
                        'trtype': transport,
                        'traddr': entry.get('Address', ''),
                        'trsvcid': entry.get('ServiceID', ''),
                    })
        return devices

    def _find_block_devices_under(self, base_path):
        '''
        Return deduplicated /dev/sdX whole-disk paths found under base_path.
        Uses find -L to follow PCI/VIO driver symlinks; excludes partitions.
        '''
        cmd = (
            f'find -L {base_path} -maxdepth 8 -name "sd*" '
            f'-path "*/block/sd*" 2>/dev/null'
        )
        names = (
            os.path.basename(line.strip())
            for line in self._cmd_out(cmd).splitlines()
            if line.strip()
        )
        return self._unique(
            f'/dev/{n}' for n in names if not re.search(r'\d', n)
        )

    def _discover_by_pci_driver(self, driver):
        '''
        Walk /sys/bus/pci/drivers/<driver>/ to collect sdX devices and
        any NVMe-oF FC controllers bound to that driver. PCIe-only NVMe
        controllers are excluded (handled by _discover_nvme_pcie).
        '''
        driver_path = f'/sys/bus/pci/drivers/{driver}'
        if not os.path.isdir(driver_path):
            self.log.warning("PCI driver path not found: %s", driver_path)
            return []

        devices = self._find_block_devices_under(driver_path)
        nvmf_devs = self._discover_nvmf()
        devices = self._unique(devices + nvmf_devs)

        if nvmf_devs:
            self.log.info("[%s] %d NVMe-oF FC controller(s) discovered",
                          driver, len(nvmf_devs))
        else:
            self.log.info("[%s] No NVMe-oF FC controllers found "
                          "(PCIe-only system)", driver)
        return devices

    def _discover_by_vio_driver(self, driver):
        '''
        Walk /sys/bus/vio/drivers/<driver>/ to collect SCSI block devices
        (sdX) for Power VIO-backed adapters (ibmvfc, ibmvscsi).

        Uses find -L to follow the VIO bus symlinks reliably.
        '''
        driver_path = f'/sys/bus/vio/drivers/{driver}'
        if not os.path.isdir(driver_path):
            self.log.warning("VIO driver path not found: %s", driver_path)
            return []
        return self._find_block_devices_under(driver_path)

    def _resolve_siblings(self, dev, checked_nqns):
        '''
        Resolve the set of sibling controller base-names that share the same
        NVMe subsystem NQN as *dev*.

        Returns ``(skip, siblings)`` where *skip* is ``True`` when the NQN
        has already been processed (caller should ``continue``), and
        *siblings* is a list of ``os.path.basename`` strings for all
        controllers in the subsystem (or ``[basename(dev)]`` for PCIe-only
        controllers that have no NQN entry in ``nvmf_details``).
        '''
        name = os.path.basename(dev)
        nqn = next(
            (d['nqn'] for d in self.nvmf_details if d['dev'] == dev), None
        )
        if nqn and nqn in checked_nqns:
            return True, []
        if nqn:
            checked_nqns.add(nqn)
            siblings = [
                os.path.basename(d['dev'])
                for d in self.nvmf_details if d['nqn'] == nqn
            ]
        else:
            siblings = [name]
        return False, siblings

    def test_lockdown_state(self):
        '''Verify lockdown=integrity and IBM DT secure-boot=2 after SB.'''
        _test_lockdown_state(self)

    def test_device_visibility(self):
        '''
        Verify all discovered block devices remain visible after Secure Boot
        enable. Checks lsblk for all drivers; nvme list and nvme list-subsys
        for NVMe/NVMe-oF; lsscsi for SCSI-type drivers.
        '''
        failures = []
        lsblk_out = self._cmd_out('lsblk -o NAME,TRAN,TYPE')
        self.log.info("lsblk output:\n%s", lsblk_out)

        # NVMe-oF multipath: multiple controller char devices (nvme3, nvme4)
        # may share one subsystem NQN; namespaces are surfaced only through
        # the primary controller (nvme3n1 ...).  Check per NQN: at least one
        # controller in the subsystem has visible namespaces in lsblk / nvme
        # list.  PCIe NVMe uses the same per-controller namespace check but
        # without multipath so each controller has its own nvmeXnY entries.
        nvme_devs = self._nvme_devs()
        if nvme_devs:
            checked_nqns = set()
            for dev in nvme_devs:
                # Find all sibling controllers sharing the same NQN.
                skip, siblings = self._resolve_siblings(dev, checked_nqns)
                if skip:
                    continue
                ns_visible = any(
                    re.search(r'\b' + re.escape(s) + r'n\d', lsblk_out)
                    for s in siblings
                )
                if not ns_visible:
                    failures.append(
                        f"lsblk: no namespaces visible for NVMe subsystem "
                        f"with controllers {siblings} "
                        f"after Secure Boot enable"
                    )

        for dev in self.block_devices:
            name = os.path.basename(dev)
            if name.startswith('nvme'):
                continue
            if name not in lsblk_out:
                failures.append(
                    f"lsblk: {dev} not found in block-device tree "
                    f"after Secure Boot enable"
                )

        if self.driver in _NVME_DRIVERS:
            self.log.info("Checking nvme list for NVMe/NVMe-oF controllers")
            nvme_list_out = self._cmd_out('nvme list')
            self.log.info(nvme_list_out)
            nvme_list_lines = [ln for ln in nvme_list_out.splitlines()
                               if ln.startswith('/dev/')]
            # For multipath NVMe-oF check per NQN: at least one controller's
            # namespaces appear in nvme list. PCIe: each ctrl is independent.
            checked_nqns = set()
            for ctrl in nvme_devs:
                skip, siblings = self._resolve_siblings(ctrl, checked_nqns)
                if skip:
                    continue
                if not any(
                    ln.startswith(f'/dev/{s}n') for s in siblings
                    for ln in nvme_list_lines
                ):
                    failures.append(
                        f"nvme list: no namespaces visible for NVMe "
                        f"subsystem with controllers {siblings} "
                        f"after Secure Boot enable"
                    )
            self.log.info("Checking nvme list-subsys for NQN entries")
            subsys_out = self._cmd_out('nvme list-subsys')
            self.log.info(subsys_out)
            if 'NQN=' not in subsys_out:
                failures.append(
                    "nvme list-subsys: no NQN entries found "
                    "after Secure Boot enable"
                )

        if self.driver in _SCSI_DRIVERS:
            self.log.info("Checking lsscsi for SCSI block devices")
            lsscsi_out = self._cmd_out('lsscsi')
            self.log.info(lsscsi_out)
            failures.extend(
                f"lsscsi: {dev} not found after Secure Boot enable"
                for dev in self._scsi_devs()
                if os.path.basename(dev) not in lsscsi_out
            )

        if failures:
            self.fail(
                "Device visibility failures after Secure Boot enable:\n"
                + '\n'.join(failures)
            )

    def test_lockdown_enforcement(self):
        '''
        Verify lockdown=integrity blocks raw NVMe hardware access via
        nvme show-regs -H (LOCKDOWN_PCI_ACCESS). Skipped for pure SCSI
        drivers when no NVMe controllers are present.
        '''
        _check_lockdown_precondition(self)

        failures = []
        nvme_devs = self._nvme_devs()

        if not nvme_devs:
            self.log.info(
                "No NVMe controllers present for driver '%s'; "
                "lockdown state already verified in test_lockdown_state",
                self.driver
            )
            return

        for ctrl in nvme_devs:
            transport = self._nvme_ctrl_transport(ctrl)
            if transport != 'pcie':
                self.log.info(
                    "Skipping nvme show-regs %s (transport=%s; "
                    "LOCKDOWN_PCI_ACCESS does not apply to fabric)",
                    ctrl, transport
                )
                continue
            self.log.info(
                "Checking nvme show-regs %s -H is blocked by lockdown",
                ctrl
            )
            self._assert_show_regs_blocked(ctrl, failures, tag='')

        if failures:
            self.fail(
                "Lockdown enforcement failures:\n" + '\n'.join(failures)
            )

    def test_driver_secureboot_checks(self):
        '''
        Dispatch to the _check_<driver> method for driver-specific Secure
        Boot attribute validation. Fails if any check appends to failures.
        '''
        dispatch = {
            'nvme': self._check_nvme,
            'nvmf': self._check_nvmf,
            'lpfc': self._check_lpfc,
            'qla2xxx': self._check_qla2xxx,
            'ibmvfc': self._check_ibmvfc,
            'ibmvscsi': self._check_ibmvscsi,
        }
        failures = []
        dispatch[self.driver](failures)
        if failures:
            self.fail(
                f"Driver-specific Secure Boot check failures "
                f"[{self.driver}]:\n" + '\n'.join(failures)
            )

    # ------------------------------------------------- shared check helpers

    def _assert_show_regs_blocked(self, ctrl, failures, tag):
        '''Assert nvme show-regs <ctrl> -H is blocked by lockdown.'''
        result, combined = self._run_cmd(f'nvme show-regs {ctrl} -H')
        self.log.info("%snvme show-regs output: '%s' rc=%d",
                      f"[{tag}] " if tag else "",
                      combined.strip(), result.exit_status)
        if self._is_blocked_by_lockdown(combined):
            self.log.info("%snvme show-regs %s -H correctly blocked",
                          f"[{tag}] " if tag else "", ctrl)
        else:
            prefix = f"[{tag}] " if tag else ""
            failures.append(
                f"{prefix}LOCKDOWN BYPASS: nvme show-regs {ctrl} -H "
                f"succeeded under lockdown=integrity; expected EPERM or "
                f"NVMe Invalid Command Opcode (0x1)"
            )

    def _check_vio_devices(self, driver_tag, expected_state, failures):
        '''
        Check that every VIO device under /sys/bus/vio/drivers/<driver_tag>/
        has its state attribute equal to expected_state (case-insensitive).
        '''
        vio_path = f'/sys/bus/vio/drivers/{driver_tag}'
        if not os.path.isdir(vio_path):
            failures.append(
                f"[{driver_tag}] VIO driver path not found: {vio_path}"
            )
            return False
        for vdev in sorted(os.listdir(vio_path)):
            state_path = os.path.join(vio_path, vdev, 'state')
            if not os.path.isfile(state_path):
                continue
            vstate = genio.read_one_line(state_path).strip()
            self.log.info("[%s] VIO device %s state = %s",
                          driver_tag, vdev, vstate)
            if vstate.lower() != expected_state.lower():
                failures.append(
                    f"[{driver_tag}] VIO device {vdev} state is "
                    f"'{vstate}', expected '{expected_state}'"
                )
        return True

    def _check_service_active(self, service, driver_tag, failures):
        '''
        Verify a systemd service is active after Secure Boot reboot.
        Skips silently when the unit is not found (exit code 4).
        '''
        self.log.info("[%s] Checking systemctl is-active %s",
                      driver_tag, service)
        result, _ = self._run_cmd(f'systemctl is-active {service}')
        state = (result.stdout + result.stderr).decode('utf-8').strip()
        self.log.info("[%s] systemctl is-active %s = '%s' (rc=%d)",
                      driver_tag, service, state, result.exit_status)
        if result.exit_status == 4 or 'not-found' in state.lower():
            self.log.info("[%s] %s not found on this system — skipping",
                          driver_tag, service)
            return
        if result.exit_status != 0:
            failures.append(
                f"[{driver_tag}] systemctl is-active {service} "
                f"returned '{state}' (rc={result.exit_status}); "
                f"service not active after Secure Boot enable"
            )

    def _check_fc_host_state(self, driver_tag, failures):
        '''
        Check port_state=Online for fc_host entries owned by driver_tag.
        Matches hosts by bound PCI address in their realpath, falling back
        to symbolic_name substring match.
        '''
        fc_host_base = '/sys/class/fc_host'
        if not os.path.isdir(fc_host_base):
            failures.append(
                f"[{driver_tag}] /sys/class/fc_host not found; "
                f"FC host sysfs not available"
            )
            return

        pci_driver_path = f'/sys/bus/pci/drivers/{driver_tag}'
        bound_pci = {
            e.lower()
            for e in os.listdir(pci_driver_path)
            if os.path.isdir(pci_driver_path) and _PCI_ADDR_RE.match(e)
        } if os.path.isdir(pci_driver_path) else set()

        checked = 0
        for host in sorted(os.listdir(fc_host_base)):
            host_path = os.path.join(fc_host_base, host)
            real = os.path.realpath(host_path).lower()
            sym_path = os.path.join(host_path, 'symbolic_name')
            sym = (genio.read_one_line(sym_path).lower()
                   if os.path.isfile(sym_path) else '')

            if not (any(p in real for p in bound_pci)
                    or driver_tag.lower() in sym):
                continue

            port_state_path = os.path.join(host_path, 'port_state')
            if not os.path.isfile(port_state_path):
                failures.append(
                    f"[{driver_tag}] {host}/port_state not found"
                )
                continue
            state = genio.read_one_line(port_state_path).strip()
            self.log.info("[%s] %s port_state = %s (pci=%s)",
                          driver_tag, host, state,
                          [p for p in bound_pci if p in real])
            checked += 1
            if state != 'Online':
                failures.append(
                    f"[{driver_tag}] {host} port_state is '{state}', "
                    f"expected 'Online' after Secure Boot enable"
                )

        if checked == 0:
            self.log.info(
                "[%s] No fc_host entries matched bound PCI addresses %s",
                driver_tag, bound_pci
            )

    # ------------------------------------------- driver-specific checkers

    def _check_nvme(self, failures):
        '''
        NVMe PCIe Secure Boot checks: verifies nvme list-subsys NQN entries,
        nvme id-ctrl succeeds (admin allowed under integrity lockdown), and
        nvme show-regs is blocked by lockdown.
        '''
        self.log.info("[nvme] Checking nvme list-subsys NQN entries")
        subsys_out = self._cmd_out('nvme list-subsys')
        self.log.info(subsys_out)
        if 'NQN=' not in subsys_out:
            failures.append("[nvme] nvme list-subsys: no NQN entries found")

        for ctrl in self.block_devices:
            self.log.info("[nvme] Checking nvme id-ctrl %s", ctrl)
            result, combined = self._run_cmd(f'nvme id-ctrl {ctrl}')
            if result.exit_status != 0:
                if self._is_blocked_by_lockdown(combined):
                    failures.append(
                        f"[nvme] nvme id-ctrl {ctrl} unexpectedly blocked "
                        f"under lockdown=integrity (admin CQE allowed)"
                    )
                else:
                    failures.append(
                        f"[nvme] nvme id-ctrl {ctrl} failed "
                        f"(rc={result.exit_status}): {combined[:200]}"
                    )
            self.log.info("[nvme] Confirming nvme show-regs %s -H "
                          "is blocked (double-check)", ctrl)
            self._assert_show_regs_blocked(ctrl, failures, tag='nvme')

    def _check_nvmf(self, failures):
        '''
        NVMe-oF Secure Boot checks: verifies nvme list-subsys retains NQN,
        trtype, and traddr for each fabric controller, and that nvme
        show-regs is blocked by lockdown.
        '''
        self.log.info("[nvmf] Checking fabric controller metadata preserved")
        subsystems = self._nvme_subsys_json()
        if not subsystems:
            failures.append(
                "[nvmf] nvme list-subsys returned no subsystems "
                "after Secure Boot enable"
            )
            return

        observed = {}
        for subsys in subsystems:
            nqn = subsys.get('NQN', '')
            for path in subsys.get('Paths', []):
                transport = path.get('Transport', '').lower()
                if transport in _FABRIC_TRANSPORTS:
                    observed.setdefault(nqn, []).append({
                        'trtype': transport,
                        'traddr': path.get('Address', ''),
                    })

        for detail in self.nvmf_details:
            nqn, expected_tr, expected_addr = (
                detail['nqn'], detail['trtype'], detail['traddr']
            )
            if nqn not in observed:
                failures.append(
                    f"[nvmf] NQN '{nqn}' missing from nvme list-subsys "
                    f"after Secure Boot enable"
                )
                continue
            if not any(e['trtype'] == expected_tr
                       and e['traddr'] == expected_addr
                       for e in observed[nqn]):
                failures.append(
                    f"[nvmf] NQN '{nqn}' transport entry "
                    f"trtype={expected_tr} traddr={expected_addr} "
                    f"not found after Secure Boot enable"
                )

        for ctrl in self._pcie_nvme_devs():
            self.log.info("[nvmf] Confirming nvme show-regs %s -H "
                          "is blocked by lockdown (PCIe only)", ctrl)
            self._assert_show_regs_blocked(ctrl, failures, tag='nvmf')

    def _check_lpfc(self, failures):
        '''
        lpfc Secure Boot checks: multipathd active, FC host port_state
        Online, lpfc_enable_fc4_type sysfs param present, and NVMe-oF FC
        checks delegated to _check_nvmf if fabric controllers were found.
        '''
        self._check_service_active('multipathd.service', 'lpfc', failures)
        self.log.info("[lpfc] Checking FC host port states")
        self._check_fc_host_state('lpfc', failures)

        lpfc_fc4_path = '/sys/module/lpfc/parameters/lpfc_enable_fc4_type'
        self.log.info("[lpfc] Checking %s", lpfc_fc4_path)
        if os.path.isfile(lpfc_fc4_path):
            self.log.info("[lpfc] lpfc_enable_fc4_type = %s",
                          genio.read_one_line(lpfc_fc4_path).strip())
        else:
            failures.append(
                f"[lpfc] {lpfc_fc4_path} not found; lpfc module may "
                f"not be loaded or parameter not exposed"
            )

        if self.nvmf_details:
            self.log.info(
                "[lpfc] Delegating NVMe-oF FC checks to _check_nvmf"
            )
            self._check_nvmf(failures)

    def _check_qla2xxx(self, failures):
        '''
        qla2xxx Secure Boot checks: multipathd active, FC host port_state
        Online, WWPN sysfs entry non-empty, and NVMe-oF FC checks delegated
        to _check_nvmf if fabric controllers were found.
        '''
        self._check_service_active('multipathd.service', 'qla2xxx', failures)
        self.log.info("[qla2xxx] Checking FC host port states and WWPNs")
        self._check_fc_host_state('qla2xxx', failures)

        fc_host_base = '/sys/class/fc_host'
        if os.path.isdir(fc_host_base):
            for host in sorted(os.listdir(fc_host_base)):
                sym_path = os.path.join(fc_host_base, host, 'symbolic_name')
                if not os.path.isfile(sym_path):
                    continue
                if 'qla2xxx' not in genio.read_one_line(sym_path).lower():
                    continue
                port_name_path = os.path.join(fc_host_base, host, 'port_name')
                if os.path.isfile(port_name_path):
                    wwpn = genio.read_one_line(port_name_path).strip()
                    self.log.info("[qla2xxx] %s port_name (WWPN) = %s",
                                  host, wwpn)
                    if not wwpn or wwpn == '0x0000000000000000':
                        failures.append(
                            f"[qla2xxx] {host} port_name is '{wwpn}'; WWPN "
                            f"may not have been restored after SB reboot"
                        )
                else:
                    failures.append(
                        f"[qla2xxx] {host}/port_name not found"
                    )

        if self.nvmf_details:
            self.log.info(
                "[qla2xxx] Delegating NVMe-oF FC checks to _check_nvmf"
            )
            self._check_nvmf(failures)

    def _check_ibmvfc(self, failures):
        '''
        ibmvfc Secure Boot checks: FC host port_state Online for all
        ibmvfc-owned fc_hosts and VIO device state=OK.
        '''
        self.log.info("[ibmvfc] Checking FC host port states")
        fc_host_base = '/sys/class/fc_host'
        if not os.path.isdir(fc_host_base):
            failures.append("[ibmvfc] /sys/class/fc_host not found")
        else:
            for host in sorted(os.listdir(fc_host_base)):
                host_path = os.path.join(fc_host_base, host)
                if 'ibmvfc' not in os.path.realpath(host_path):
                    continue
                port_state_path = os.path.join(host_path, 'port_state')
                if not os.path.isfile(port_state_path):
                    failures.append(
                        f"[ibmvfc] {host}/port_state not found"
                    )
                    continue
                state = genio.read_one_line(port_state_path).strip()
                self.log.info("[ibmvfc] %s port_state = %s", host, state)
                if state != 'Online':
                    failures.append(
                        f"[ibmvfc] {host} port_state is '{state}', "
                        f"expected 'Online'"
                    )

        self.log.info("[ibmvfc] Checking VIO device state entries")
        self._check_vio_devices('ibmvfc', 'OK', failures)

    def _check_ibmvscsi(self, failures):
        '''
        ibmvscsi Secure Boot checks: VIO device state=Running and all
        discovered sdX devices still enumerated in lsscsi.
        '''
        self.log.info("[ibmvscsi] Checking VIO device state entries")
        if not self._check_vio_devices('ibmvscsi', 'Running', failures):
            return

        self.log.info("[ibmvscsi] Checking lsscsi for vSCSI block devices")
        lsscsi_out = self._cmd_out('lsscsi')
        self.log.info(lsscsi_out)
        failures.extend(
            f"[ibmvscsi] lsscsi: {dev} not found after Secure Boot enable"
            for dev in self._scsi_devs()
            if os.path.basename(dev) not in lsscsi_out
        )


# ══════════════════════════════════════════════════════════════════════════════
# SecureBootNic — NIC driver validation after Secure Boot enable
# ══════════════════════════════════════════════════════════════════════════════

class SecureBootNic(Test):
    '''
    Validates NIC driver state after Secure Boot enable on IBM Power LPARs.

    The interface parameter accepts either an interface name (e.g. env3,
    bond0) or a MAC address. The driver name and bus type (vio / pci) are
    auto-detected from the sysfs driver symlink:

      /sys/class/net/<iface>/device/driver ->
      .../bus/{vio|pci}/drivers/<drv>

    :param interface: interface name or MAC address of the NIC under test
    :param hbond:     set True when interface is a member of an HNV bond
    '''

    # ------------------------------------------------------------------ setUp

    def setUp(self):
        '''Install pkgs, resolve interface + driver, check Secure Boot.'''
        smm = SoftwareManager()
        detected_distro = distro.detect()
        pkgs = ['ethtool', 'net-tools']
        if detected_distro.name == 'Ubuntu':
            pkgs.extend(['openssh-client', 'iputils-ping'])
        elif detected_distro.name == 'SuSE':
            pkgs.extend(['openssh', 'iputils'])
        else:
            pkgs.extend(['openssh-clients', 'iputils'])
        for pkg in pkgs:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel('%s package is needed to test' % pkg)

        if detected_distro.name not in ('rhel', 'SuSE'):
            self.cancel(
                'Supported only on RHEL and SUSE; '
                'detected: %s' % detected_distro.name
            )

        lockdown_path = '/sys/kernel/security/lockdown'
        if not genio.is_pattern_in_file(lockdown_path, r'\w'):
            self.cancel(
                'Secure Boot lockdown sysfs not present; '
                'kernel may not support lockdown'
            )
        lockdown_line = genio.read_one_line(lockdown_path)
        match = re.search(r'\[(\w+)\]', lockdown_line)
        active_mode = match.group(1) if match else ''
        if active_mode == 'none':
            self.cancel(
                'Secure Boot is not enabled (lockdown=[none]). '
                'Enable Secure Boot on the LPAR and reboot before running '
                'this test.'
            )
        self.log.info('Secure Boot lockdown mode: [%s]', active_mode)

        # ── Resolve interface name from name or MAC ────────────────────────
        local = LocalHost()
        self._local = local
        device = self.params.get('interface', default=None)
        if not device:
            self.cancel('interface is not set in YAML')
        self.hbond = self.params.get('hbond', default=False)
        interfaces = os.listdir('/sys/class/net')

        if device in interfaces:
            # interface name given directly (bond name or regular interface)
            self.interface = device
        elif (local.validate_mac_addr(device)
              and device in local.get_all_hwaddr()):
            if self.hbond:
                # is_bond() tells if MAC hit the bond master directly.
                iface = local.get_interface_by_hwaddr(device)
                if iface.is_bond():
                    self.interface = iface.name
                else:
                    # got the slave; resolve its bond master
                    bond_master = iface.get_bond_master()
                    if not bond_master:
                        self.cancel(
                            'Could not resolve bond master for slave %s'
                            % iface.name
                        )
                    self.interface = bond_master
            else:
                # regular interface identified by MAC address
                self.interface = local.get_interface_by_hwaddr(device).name
        else:
            self.cancel("interface '%s' not found on this host" % device)

        # ── Derive driver name and bus type from sysfs ────────────────────
        drv_link = self._resolve_drv_link()
        drv_target = os.readlink(drv_link)
        self.driver = os.path.basename(drv_target)
        self.driver_type = 'vio' if '/vio/' in drv_target else 'pci'
        self.log.info(
            'Interface %s  driver=%s  bus=%s',
            self.interface, self.driver, self.driver_type
        )

        # ── Validate driver path on the correct bus ───────────────────────
        if self.driver_type == 'vio':
            vio_path = '/sys/bus/vio/drivers/%s' % self.driver
            if not os.path.isdir(vio_path):
                self.cancel(
                    'VIO driver path not found: %s; '
                    '%s driver not loaded on this LPAR'
                    % (vio_path, self.driver)
                )
        else:
            pci_path = '/sys/bus/pci/drivers/%s' % self.driver
            if not os.path.isdir(pci_path):
                self.cancel(
                    "PCIe NIC driver '%s' not found at %s; "
                    'driver not loaded or not present on this LPAR'
                    % (self.driver, pci_path)
                )

        # ── IP / peer setup ───────────────────────────────────────────────
        self.ipaddr = self.params.get('host_ip', default='')
        self.netmask = self.params.get('netmask', default='')
        self.ip_config = self.params.get('ip_config', default=True)
        if self.hbond:
            self.networkinterface = NetworkInterface(
                self.interface, local, if_type='Bond')
        else:
            self.networkinterface = NetworkInterface(self.interface, local)
        if self.ip_config:
            try:
                self.networkinterface.add_ipaddr(self.ipaddr, self.netmask)
                self.networkinterface.save(self.ipaddr, self.netmask)
            except Exception:
                self.networkinterface.save(self.ipaddr, self.netmask)
            self.networkinterface.bring_up()
        if not wait.wait_for(self.networkinterface.is_link_up, timeout=120):
            self.fail(
                'Link up of %s taking longer than 120 seconds'
                % self.interface
            )

        self.peer = self.params.get('peer_ip', default=None)
        if not self.peer:
            self.cancel('peer_ip is not set in YAML')
        self.peer_user = self.params.get('peer_user', default='root')
        self.peer_password = self.params.get('peer_password', '*',
                                             default=None)
        self.remotehost = RemoteHost(self.peer, self.peer_user,
                                     password=self.peer_password)

        if self.networkinterface.ping_check(self.peer, count=5) is not None:
            self.cancel('No connection to peer %s' % self.peer)

    # --------------------------------------------------------- setUp helpers

    def _resolve_drv_link(self):
        '''
        Return the path to the device/driver symlink for self.interface.
        For bond/hbond masters the symlink lives on the first slave.
        Cancels the test if no usable symlink can be found.
        '''
        drv_link = f'/sys/class/net/{self.interface}/device/driver'
        if os.path.islink(drv_link):
            return drv_link

        slaves_path = f'/sys/class/net/{self.interface}/bonding/slaves'
        if not os.path.isfile(slaves_path):
            self.cancel(
                f'Cannot determine driver for {self.interface}: '
                f'{drv_link} is not a symlink and no bonding/slaves file '
                f'found; interface may be virtual (loopback, vlan, etc.)'
            )
        slaves_raw = genio.read_file(slaves_path).strip()
        if not slaves_raw:
            self.cancel(
                f'Bond {self.interface} has no slaves; '
                f'cannot determine driver'
            )
        first_slave = slaves_raw.split()[0]
        slave_link = f'/sys/class/net/{first_slave}/device/driver'
        if not os.path.islink(slave_link):
            self.cancel(
                f'Cannot determine driver for bond {self.interface}: '
                f'slave {first_slave} has no device/driver symlink'
            )
        self.log.info(
            'Bond/hbond %s: resolving driver from slave %s',
            self.interface, first_slave
        )
        return slave_link

    # ----------------------------------------------------------------- helpers

    @staticmethod
    def _cmd_out(cmd):
        '''Run cmd; return decoded stdout.'''
        return process.system_output(
            cmd, shell=True, ignore_status=True
        ).decode('utf-8')

    @staticmethod
    def _pci_dt_ethernet_exists():
        '''Return True if an ethernet@ node exists under
        /proc/device-tree/pci@*/.'''
        dt_root = '/proc/device-tree'
        if not os.path.isdir(dt_root):
            return False
        for entry in os.listdir(dt_root):
            if not entry.startswith('pci@'):
                continue
            for child in os.listdir(os.path.join(dt_root, entry)):
                if child.startswith('ethernet'):
                    return True
        return False

    # --------------------------------------------------------------- test_*

    def test_lockdown_state(self):
        '''Verify lockdown=integrity and IBM DT secure-boot=2 after SB.'''
        _test_lockdown_state(self)

    def test_interface_visibility(self):
        '''Verify NIC interfaces visible after SB enable and ping peer.'''
        _check_lockdown_precondition(self)
        failures = []

        if self.driver_type == 'vio':
            self._check_vio_nic_visibility(failures)
        else:
            self._check_pci_nic_visibility(failures)

        if failures:
            self.fail(
                'NIC interface visibility failures after Secure Boot '
                'enable:\n' + '\n'.join(failures)
            )

        self.log.info('[%s] Pinging %s to confirm interface is up',
                      self.driver, self.peer)
        if self.networkinterface.ping_check(self.peer, count=5) is not None:
            self.fail(
                '[%s] ping to %s via %s failed after Secure Boot enable'
                % (self.driver, self.peer, self.interface)
            )

    def test_driver_secureboot_checks(self):
        '''Driver-specific Secure Boot attribute validation.'''
        _check_lockdown_precondition(self)
        failures = []

        if self.driver_type == 'vio':
            self._check_vio_nic(failures)
        else:
            self._check_pci_nic(failures)

        if failures:
            self.fail(
                'Driver-specific Secure Boot check failures [%s]:\n'
                % self.driver + '\n'.join(failures)
            )

    # ----------------------------------------- visibility check helpers

    def _check_vio_nic_visibility(self, failures):
        '''Check net/ interface registered under every bound VIO slot.'''
        vio_path = '/sys/bus/vio/drivers/%s' % self.driver
        bound = [
            e for e in os.listdir(vio_path)
            if not e.startswith(('bind', 'unbind', 'uevent', 'module'))
            and not e.startswith('.')
        ]
        if not bound:
            failures.append(
                '[%s] No VIO devices bound under %s '
                'after Secure Boot enable' % (self.driver, vio_path)
            )
            return
        for slot in bound:
            net_dir = os.path.join(vio_path, slot, 'net')
            if not os.path.isdir(net_dir):
                failures.append(
                    '[%s] No net/ interface under %s/%s '
                    'after Secure Boot enable'
                    % (self.driver, vio_path, slot)
                )
                continue
            self.log.info('[%s] Slot %s  net interface(s): %s',
                          self.driver, slot,
                          ', '.join(os.listdir(net_dir)))

    def _check_pci_nic_visibility(self, failures):
        '''Check at least one PCI device bound to driver
        exposes a net/ interface.'''
        pci_base = '/sys/bus/pci/devices'
        if not os.path.isdir(pci_base):
            failures.append(
                '[%s] %s not found; PCI bus not available'
                % (self.driver, pci_base)
            )
            return
        found_any = False
        for bdf in os.listdir(pci_base):
            drv_link = os.path.join(pci_base, bdf, 'driver')
            if not os.path.islink(drv_link):
                continue
            if os.path.basename(os.readlink(drv_link)) != self.driver:
                continue
            net_dir = os.path.join(pci_base, bdf, 'net')
            if not os.path.isdir(net_dir):
                continue
            found_any = True
            self.log.info('[%s] %s  net interface(s): %s',
                          self.driver, bdf,
                          ', '.join(os.listdir(net_dir)))
        if not found_any:
            failures.append(
                "[%s] No PCI device bound to '%s' with a net/ interface "
                'found after Secure Boot enable'
                % (self.driver, self.driver)
            )

    # ----------------------------------------- driver-specific checkers

    def _check_vio_nic(self, failures):
        '''VIO NIC checks: driver binding, device-tree node,
        net/ interface, operstate.'''
        drv = self.driver
        vio_path = '/sys/bus/vio/drivers/%s' % drv

        self.log.info('[%s] Checking driver binding under %s', drv, vio_path)
        bound = [
            e for e in os.listdir(vio_path)
            if not e.startswith(('bind', 'unbind', 'uevent', 'module'))
            and not e.startswith('.')
        ]
        if not bound:
            failures.append(
                '[%s] No VIO devices bound under %s '
                'after Secure Boot enable' % (drv, vio_path)
            )
            return
        self.log.info('[%s] Bound VIO slot(s): %s', drv, ', '.join(bound))

        # device-tree check (VIO NICs only)
        if drv in _VIO_DT_PREFIX:
            dt_prefix = _VIO_DT_PREFIX[drv]
            self.log.info('[%s] Checking %s* node under %s',
                          drv, dt_prefix, _DEVICE_TREE_VDEVICE)
            if os.path.isdir(_DEVICE_TREE_VDEVICE):
                dt_nodes = [
                    e for e in os.listdir(_DEVICE_TREE_VDEVICE)
                    if e.startswith(dt_prefix)
                ]
                if not dt_nodes:
                    failures.append(
                        '[%s] No %s* node found under %s; '
                        '%s VIO adapter not present in device-tree '
                        'after Secure Boot enable'
                        % (drv, dt_prefix, _DEVICE_TREE_VDEVICE, drv)
                    )
                else:
                    self.log.info('[%s] Device-tree node(s): %s',
                                  drv, ', '.join(dt_nodes))
                    if drv == 'ibmvnic':
                        for node in dt_nodes:
                            hcn_path = os.path.join(
                                _DEVICE_TREE_VDEVICE, node, 'ibm,hcn-mode'
                            )
                            if os.path.exists(hcn_path):
                                mode = genio.read_file(
                                    hcn_path).rstrip('\x00\n')
                                self.log.info('[%s] %s ibm,hcn-mode=%s',
                                              drv, node, mode)
            else:
                self.log.warning('[%s] %s not found; device-tree check '
                                 'skipped', drv, _DEVICE_TREE_VDEVICE)

        for slot in bound:
            net_dir = os.path.join(vio_path, slot, 'net')
            if not os.path.isdir(net_dir):
                failures.append(
                    '[%s] No net/ interface registered under %s/%s '
                    'after Secure Boot enable' % (drv, vio_path, slot)
                )
                continue
            ifaces = os.listdir(net_dir)
            self.log.info('[%s] Slot %s  interface(s): %s',
                          drv, slot, ', '.join(ifaces))

            if drv == 'ibmvnic':
                pattern = 'ibmvnic %s: Partner initialization complete' % slot
                if not dmesg.collect_errors_dmesg(pattern):
                    self.log.info(
                        '[%s] Partner init message for slot %s not in dmesg '
                        '(may have been rotated since boot)', drv, slot
                    )
                else:
                    self.log.info(
                        '[%s] Partner initialization confirmed in dmesg '
                        'for slot %s', drv, slot
                    )
                for iface in ifaces:
                    state_path = '/sys/class/net/%s/operstate' % iface
                    state = (
                        genio.read_file(state_path).strip()
                        if os.path.exists(state_path) else 'unknown'
                    )
                    self.log.info('[%s] %s (slot %s) operstate=%s',
                                  drv, iface, slot, state)
                    if state == 'down':
                        failures.append(
                            '[%s] %s (slot %s) operstate is '
                            "'down'; interface not usable after Secure Boot "
                            'enable' % (drv, iface, slot)
                        )

    def _check_pci_nic(self, failures):
        '''PCIe NIC checks: device binding, net/ interface,
        ethernet@ DT node, operstate.'''
        drv = self.driver
        pci_base = '/sys/bus/pci/devices'

        self.log.info('[%s] Scanning %s for PCI devices bound to %s',
                      drv, pci_base, drv)
        found_any = False
        for bdf in sorted(os.listdir(pci_base)):
            drv_link = os.path.join(pci_base, bdf, 'driver')
            if not os.path.islink(drv_link):
                continue
            if os.path.basename(os.readlink(drv_link)) != drv:
                continue
            net_dir = os.path.join(pci_base, bdf, 'net')
            if not os.path.isdir(net_dir):
                self.log.info(
                    '[%s] %s bound to %s but has no net/ subdir (skipping)',
                    drv, bdf, drv
                )
                continue
            ifaces = os.listdir(net_dir)
            found_any = True
            self.log.info('[%s] %s  interface(s): %s',
                          drv, bdf, ', '.join(ifaces))

            if not self._pci_dt_ethernet_exists():
                failures.append(
                    '[%s] No ethernet@ device-tree node found under '
                    '/proc/device-tree/pci@*/; firmware may not have '
                    'enumerated the PCIe NIC after Secure Boot enable' % drv
                )
            else:
                self.log.info(
                    '[%s] device-tree ethernet@ node confirmed for %s',
                    drv, bdf
                )
            for iface in ifaces:
                state_path = '/sys/class/net/%s/operstate' % iface
                state = (
                    genio.read_file(state_path).strip()
                    if os.path.exists(state_path) else 'unknown'
                )
                self.log.info('[%s] %s (bdf=%s) operstate=%s',
                              drv, iface, bdf, state)
                if state == 'down':
                    self.log.info(
                        "[%s] %s is 'down' — may be unplugged or unused port",
                        drv, iface
                    )
        if not found_any:
            failures.append(
                "[%s] No PCI device bound to '%s' with a net/ "
                'interface found after Secure Boot enable'
                % (drv, drv)
            )

    # ---------------------------------------------------------------- tearDown

    def tearDown(self):
        '''Remove IP config and close remote session.'''
        if hasattr(self, 'networkinterface') and hasattr(self, 'ip_config'):
            if self.ip_config:
                self.networkinterface.remove_ipaddr(self.ipaddr, self.netmask)
                try:
                    self.networkinterface.restore_from_backup()
                except Exception:
                    self.networkinterface.remove_cfg_file()
                    self.log.info(
                        'backup file not available, could not restore file.')
        if hasattr(self, 'remotehost'):
            self.remotehost.remote_session.quit()
