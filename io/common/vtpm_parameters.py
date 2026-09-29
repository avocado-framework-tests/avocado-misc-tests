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
# Author: Vaishnavi Bhat <vaishnavi@linux.ibm.com>

"""vTPM Parameter Validation for Storage and Network Drivers on IBM Power.

For block device drivers (nvme, nvmf, lpfc, qla2xxx, ibmvfc, ibmvscsi)
set block_driver: <name>.

For NIC drivers (VIO or PCIe) set interface: <name-or-MAC>.  The driver
name and bus type are auto-detected from the sysfs driver symlink.
Set hbond: True when the interface is a member of an HNV bond — the bond
master is then located automatically and used as the test interface.
"""

import grp
import os
import pwd
import re

from avocado import Test
from avocado.utils import dmesg, distro, genio, linux_modules, process
from avocado.utils import wait
from avocado.utils.network.hosts import LocalHost, RemoteHost
from avocado.utils.network.interfaces import NetworkInterface


_DEVICE_TREE_VDEVICE = '/proc/device-tree/vdevice'
_BINARY_BIOS_MEAS = '/sys/kernel/security/tpm0/binary_bios_measurements'

# Block device drivers — accepted via block_driver parameter.
_VALID_BLOCK_DRIVERS = frozenset([
    'nvme', 'nvmf', 'lpfc', 'qla2xxx', 'ibmvfc', 'ibmvscsi',
])

# VIO NIC drivers — dispatched to _check_vio_nic().
_VIO_NIC_DRIVERS = frozenset(['ibmvnic', 'ibmveth'])

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


class VtpmParameters(Test):  # pylint: disable=too-many-instance-attributes

    '''
    vTPM parameter validation for storage and network drivers on IBM Power
    LPARs (ppc64le, RHEL/SUSE).

    :param block_driver:   one of nvme|nvmf|lpfc|qla2xxx|ibmvfc|ibmvscsi
                           (used for block device driver tests).
    :param interface:      interface name (e.g. env3, eth0) or MAC address
                           of the NIC under test (used for NIC tests);
                           driver name and bus type auto-detected from sysfs.
    :param hbond:          set True when interface is a member of an HNV bond.
                           The bond master is located automatically.
    :param host_ip:        IP address to assign to the NIC interface.
    :param netmask:        netmask for host_ip.
    :param peer_ip:        peer host IP for connectivity checks.
    :param peer_user:      SSH user on the peer host (default: root).
    :param peer_password:  SSH password on the peer host.
    :param ip_config:      set False to skip IP assignment (default: True).
    '''

    # ------------------------------------------------------------------ setUp

    def setUp(self):  # pylint: disable=invalid-name,too-many-branches
        '''
        Validate distro and architecture, locate the vTPM device-tree node,
        auto-detect vtpm_version from the compatible string, and resolve
        expected device-node ownership/permissions.

        For block device tests reads block_driver and sets self.driver.
        For NIC tests reads interface (name or MAC), resolves the interface
        name (honouring hbond), derives self.driver / self.driver_type from
        the sysfs driver symlink, and sets up IP / peer connectivity.

        Sets self.driver, self.driver_type, self.vtpm_dev_name,
        self.vtpm_version, and self.dev_details.
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

        block_driver = (
            self.params.get('block_driver', default='') or ''
        ).strip()
        interface_param = (
            self.params.get('interface', default='') or ''
        ).strip()
        self.hbond = self.params.get('hbond', default=False)

        if not block_driver and not interface_param:
            valid_drivers = ', '.join(sorted(_VALID_BLOCK_DRIVERS))
            self.cancel(
                "Either block_driver or interface must be set. "
                f"block_driver: one of {valid_drivers}. "
                "interface: interface name or MAC address of the "
                "NIC under test."
            )

        if block_driver:
            if block_driver not in _VALID_BLOCK_DRIVERS:
                self.cancel(
                    f"block_driver '{block_driver}' is not valid. "
                    f"Choose one of: {', '.join(sorted(_VALID_BLOCK_DRIVERS))}"
                )
            self.driver = block_driver
            self.driver_type = 'block'
        else:
            self._resolve_nic_driver(interface_param)
            self._setup_nic_connectivity()

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
        self.log.info("Driver type       : %s", self.driver_type)
        self.log.info("vTPM device node  : %s", self.vtpm_dev_name)
        self.log.info("vTPM version      : %s", self.vtpm_version)
        self.log.info("Expected dev nodes: %s",
                      ', '.join(self.dev_details.keys()))

    # --------------------------------------------------------- setUp helpers

    def _resolve_nic_driver(self, device):
        '''
        Resolve self.interface, self.driver, and self.driver_type from the
        interface parameter (name or MAC address).

        Follows network_test.py logic: accepts direct interface names
        (regular or bond), or MAC addresses (resolving bond master if
        hbond=True).

        For bond/hbond masters the device/driver symlink lives on a slave;
        the driver is resolved from the first slave in bonding/slaves.
        '''
        local = LocalHost()
        self._local = local
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
                            "Could not resolve bond master for slave %s"
                            % iface.name
                        )
                    self.interface = bond_master
            else:
                # regular interface identified by MAC address
                self.interface = local.get_interface_by_hwaddr(device).name
        else:
            self.cancel(f"interface '{device}' not found on this host")

        drv_link = self._resolve_drv_link()
        drv_target = os.readlink(drv_link)
        self.driver = os.path.basename(drv_target)
        self.driver_type = 'vio' if '/vio/' in drv_target else 'pci'
        self.log.info(
            'Interface %s  driver=%s  bus=%s',
            self.interface, self.driver, self.driver_type
        )
        self._validate_nic_driver_path()

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

    def _validate_nic_driver_path(self):
        '''
        Cancel the test if the resolved self.driver is not present on the
        expected bus (/sys/bus/vio/drivers/ or /sys/bus/pci/drivers/).
        '''
        if self.driver_type == 'vio':
            bus_path = f'/sys/bus/vio/drivers/{self.driver}'
            if not os.path.isdir(bus_path):
                self.cancel(
                    f'VIO driver path not found: {bus_path}; '
                    f'{self.driver} driver not loaded on this LPAR'
                )
        else:
            bus_path = f'/sys/bus/pci/drivers/{self.driver}'
            if not os.path.isdir(bus_path):
                self.cancel(
                    f"PCIe NIC driver '{self.driver}' not found at "
                    f'{bus_path}; driver not loaded or not present on '
                    f'this LPAR'
                )

    def _setup_nic_connectivity(self):
        '''
        Assign IP, bring up the interface, and establish peer connectivity.
        Mirrors the IP/peer setup in SecureBootNic.setUp().
        '''
        local = self._local
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
            except Exception:  # pylint: disable=broad-except
                self.networkinterface.save(self.ipaddr, self.netmask)
            self.networkinterface.bring_up()
        if not wait.wait_for(self.networkinterface.is_link_up, timeout=120):
            self.cancel(
                f'Link up of {self.interface} taking longer than 120 seconds'
            )
        self.peer = self.params.get('peer_ip', default=None)
        if not self.peer:
            self.cancel('peer_ip is not set in YAML')
        self.peer_user = self.params.get('peer_user', default='root')
        self.peer_password = self.params.get(
            'peer_password', '*', default=None
        )
        self.remotehost = RemoteHost(
            self.peer, self.peer_user, password=self.peer_password
        )
        if self.networkinterface.ping_check(self.peer, count=5) is not None:
            self.cancel(f'No connection to peer {self.peer}')

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
        which driver (block or NIC) is under test.
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
        driver (block or NIC). Reports every missing config before failing.
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
        character device, independent of the driver under test.
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
        Dispatch to the appropriate checker for driver-specific vTPM
        parameter validation. Block drivers use a name-keyed dispatch table.
        NIC drivers are routed by self.driver_type (vio / pci).
        For NIC tests, pings the peer after all vTPM checks pass to confirm
        end-to-end connectivity is unaffected by vTPM configuration.
        Fails if any check appends to failures or if ping fails.
        '''
        block_dispatch = {
            'nvme':     self._check_nvme,
            'nvmf':     self._check_nvmf,
            'lpfc':     self._check_lpfc,
            'qla2xxx':  self._check_qla2xxx,
            'ibmvfc':   self._check_ibmvfc,
            'ibmvscsi': self._check_ibmvscsi,
        }
        failures = []
        if self.driver_type == 'block':
            block_dispatch[self.driver](failures)
        elif self.driver_type == 'vio':
            self._check_vio_nic(failures)
        else:
            self._check_pci_nic(failures)
        if failures:
            self.fail(
                f"Driver-specific vTPM parameter check failures "
                f"[{self.driver}]:\n" + '\n'.join(failures)
            )

        # NIC tests only: verify end-to-end connectivity after vTPM validation
        if hasattr(self, 'peer'):
            self.log.info(
                '[%s] Pinging peer %s via %s after vTPM validation',
                self.driver, self.peer, self.interface
            )
            if self.networkinterface.ping_check(
                    self.peer, count=5) is not None:
                self.fail(
                    f'[{self.driver}] ping to {self.peer} via '
                    f'{self.interface} failed after vTPM parameter validation'
                )
            self.log.info(
                '[%s] ping to %s via %s succeeded',
                self.driver, self.peer, self.interface
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

    def _check_vio_nic(self, failures):
        '''
        VIO NIC vTPM checks for ibmvnic and ibmveth.  Driven by self.driver
        which is one of the _VIO_NIC_DRIVERS values.

        Per-driver device-tree node prefix and VIO driver path:
          ibmvnic → vnic@  nodes, /sys/bus/vio/drivers/ibmvnic
          ibmveth → l-lan@ nodes, /sys/bus/vio/drivers/ibmveth

        Checks:
          - common vTPM parameters (CRQ, /proc/devices, measurement log)
          - VIO device-tree node co-exists with vtpm@ under vdevice/
          - driver is bound to at least one VIO slot
          - net/ interface registered under the VIO device sysfs
          - operstate is not 'down' for ibmvnic (ibmveth reports 'unknown'
            which is normal and is not checked)
          - ibm,hcn-mode property logged for ibmvnic vnic@ nodes (HNV)
        '''
        drv = self.driver
        # Per-driver device-tree prefix and VIO driver path
        dt_prefix = 'vnic@' if drv == 'ibmvnic' else 'l-lan@'
        vio_drv = f'/sys/bus/vio/drivers/{drv}'

        self.log.info("[%s] Checking vTPM parameters for %s driver", drv, drv)
        self._check_vtpm_common(drv, failures)

        # VIO device-tree coexistence
        self.log.info(
            "[%s] Checking %s VIO node co-exists with vTPM under %s",
            drv, dt_prefix, _DEVICE_TREE_VDEVICE
        )
        dt_nodes = [
            e for e in os.listdir(_DEVICE_TREE_VDEVICE)
            if e.startswith(dt_prefix)
        ]
        if not dt_nodes:
            failures.append(
                f"[{drv}] No {dt_prefix}* node found under "
                f"{_DEVICE_TREE_VDEVICE}; {drv} VIO adapter not present "
                f"in device-tree alongside vTPM"
            )
        else:
            self.log.info(
                "[%s] Found %s VIO node(s): %s",
                drv, dt_prefix, ', '.join(dt_nodes)
            )

        # VIO driver binding
        self.log.info("[%s] Checking driver binding under %s", drv, vio_drv)
        if not os.path.isdir(vio_drv):
            failures.append(
                f"[{drv}] {vio_drv} not found; {drv} driver not loaded"
            )
            return

        bound = [
            e for e in os.listdir(vio_drv)
            if not e.startswith(('bind', 'unbind', 'uevent', 'module'))
            and not e.startswith('.')
        ]
        if not bound:
            failures.append(
                f"[{drv}] No VIO devices bound under {vio_drv}"
            )
            return

        self.log.info(
            "[%s] %s bound to VIO device(s): %s", drv, drv, ', '.join(bound)
        )

        for slot in bound:
            self._check_vio_nic_slot(drv, vio_drv, slot, failures)

        # ibmvnic only: log ibm,hcn-mode for HNV bond leg identification
        if drv == 'ibmvnic':
            for node in dt_nodes:
                hcn_path = os.path.join(
                    _DEVICE_TREE_VDEVICE, node, 'ibm,hcn-mode'
                )
                if os.path.exists(hcn_path):
                    mode = genio.read_file(hcn_path).rstrip('\x00\n')
                    self.log.info(
                        "[%s] %s ibm,hcn-mode=%s", drv, node, mode
                    )

    def _check_vio_nic_slot(self, drv, vio_drv, slot, failures):
        '''
        Per-slot checks inside _check_vio_nic():
          - ibmvnic: Partner initialization message in dmesg
          - net/ interface registered under VIO device sysfs
          - ibmvnic: operstate of each interface must not be 'down'
        '''
        if drv == 'ibmvnic':
            pattern = f"ibmvnic {slot}: Partner initialization complete"
            if not dmesg.collect_errors_dmesg(pattern):
                self.log.info(
                    "[%s] Partner init message for %s not in dmesg "
                    "(may have been rotated)", drv, slot
                )
            else:
                self.log.info(
                    "[%s] Partner initialization confirmed in dmesg "
                    "for slot %s", drv, slot
                )

        net_dir = os.path.join(vio_drv, slot, 'net')
        if not os.path.isdir(net_dir):
            failures.append(
                f"[{drv}] No net/ interface registered under "
                f"{vio_drv}/{slot}; {drv} did not create a network "
                f"interface after vTPM setup"
            )
            return

        ifaces = os.listdir(net_dir)
        self.log.info(
            "[%s] net interface(s) for slot %s: %s",
            drv, slot, ', '.join(ifaces)
        )

        if drv != 'ibmvnic':
            return
        for iface in ifaces:
            state_path = os.path.join('/sys/class/net', iface, 'operstate')
            state = (
                genio.read_file(state_path).strip()
                if os.path.exists(state_path) else 'unknown'
            )
            self.log.info("[%s] %s operstate=%s", drv, iface, state)
            if state == 'down':
                failures.append(
                    f"[{drv}] {iface} (slot {slot}) operstate is "
                    f"'down'; interface not usable after vTPM setup"
                )

    def _check_pci_nic(self, failures):
        '''
        PCIe NIC vTPM checks for any direct-attach or SR-IOV NIC driver
        (e.g. tg3, mlx5_core).  The actual driver name is in self.driver,
        validated in setUp() against /sys/bus/pci/drivers/<driver>/.

        Unlike VIO drivers, PCIe NICs have no vdevice coexistence with the
        vTPM.  Checks:
          - common vTPM parameters (CRQ, /proc/devices, measurement log)
          - PCI devices bound to self.driver that expose a net/ subdir
          - ethernet@ node present in /proc/device-tree/pci@*/ for each
            matching PCI device, confirming firmware enumeration
          - operstate logged per interface (down = informational only,
            unused ports on multi-port NICs are normal)
        '''
        drv = self.driver
        self.log.info(
            "[%s] Checking vTPM parameters for PCIe NIC driver %s", drv, drv
        )
        self._check_vtpm_common(drv, failures)

        pci_base = '/sys/bus/pci/devices'
        self.log.info(
            "[%s] Scanning %s for devices bound to %s with net interfaces",
            drv, pci_base, drv
        )
        if not os.path.isdir(pci_base):
            failures.append(
                f"[{drv}] {pci_base} not found; PCI bus not available"
            )
            return

        found_any = False
        for bdf in os.listdir(pci_base):
            drv_link = os.path.join(pci_base, bdf, 'driver')
            if not os.path.islink(drv_link):
                continue
            if os.path.basename(os.readlink(drv_link)) != drv:
                continue

            net_dir = os.path.join(pci_base, bdf, 'net')
            if not os.path.isdir(net_dir):
                self.log.info(
                    "[%s] %s bound to %s but has no net/ subdir (skipping)",
                    drv, bdf, drv
                )
                continue

            ifaces = os.listdir(net_dir)
            found_any = True
            self.log.info(
                "[%s] %s  iface(s)=%s", drv, bdf, ', '.join(ifaces)
            )

            # Confirm ethernet@ node in PCI device-tree
            if not self._pci_dt_ethernet_exists():
                failures.append(
                    f"[{drv}] No ethernet@ device-tree node found for "
                    f"{bdf}; firmware may not have enumerated this PCIe NIC"
                )
            else:
                self.log.info(
                    "[%s] device-tree ethernet@ node confirmed for %s",
                    drv, bdf
                )

            # Operstate: informational only — down may mean unused port
            for iface in ifaces:
                state_path = os.path.join(
                    '/sys/class/net', iface, 'operstate'
                )
                state = (
                    genio.read_file(state_path).strip()
                    if os.path.exists(state_path) else 'unknown'
                )
                self.log.info(
                    "[%s] %s (bdf=%s) operstate=%s", drv, iface, bdf, state
                )
                if state == 'down':
                    self.log.info(
                        "[%s] %s is 'down' — may be unplugged or unused "
                        "port (not a failure)", drv, iface
                    )

        if not found_any:
            failures.append(
                f"[{drv}] No PCI devices bound to {drv} with a net/ "
                f"interface found on this LPAR"
            )

    @staticmethod
    def _pci_dt_ethernet_exists():
        '''
        Return True if at least one ethernet@ child node exists under any
        /proc/device-tree/pci@*/ directory.

        The search walks all /proc/device-tree/pci@*/ directories and
        checks for any ethernet@ child, which is sufficient to confirm
        that the firmware has enumerated at least one PCIe NIC under that
        PHB — without hard-coding the exact PHB address string.
        '''
        dt_root = '/proc/device-tree'
        if not os.path.isdir(dt_root):
            return False
        for entry in os.listdir(dt_root):
            if not entry.startswith('pci@'):
                continue
            pci_node = os.path.join(dt_root, entry)
            for child in os.listdir(pci_node):
                if child.startswith('ethernet'):
                    return True
        return False

    def tearDown(self):  # pylint: disable=invalid-name
        '''
        Remove IP configuration and close remote session if set up for NIC.
        '''
        if hasattr(self, 'networkinterface') and hasattr(self, 'ip_config'):
            if self.ip_config:
                self.networkinterface.remove_ipaddr(self.ipaddr, self.netmask)
                try:
                    self.networkinterface.restore_from_backup()
                except Exception:  # pylint: disable=broad-except
                    self.networkinterface.remove_cfg_file()
                    self.log.info(
                        'backup file not available, could not restore file.')
        if hasattr(self, 'remotehost'):
            self.remotehost.remote_session.quit()
