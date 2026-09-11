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

"""Secure Boot parameter validation for NIC drivers on IBM Power LPARs.

:avocado: tags=net,secureboot,privileged
"""

import os
import re

from avocado import Test
from avocado.utils import dmesg, distro, genio, linux, process
from avocado.utils import wait
from avocado.utils.network.hosts import LocalHost, RemoteHost
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.software_manager.manager import SoftwareManager


_VIO_NIC_DRIVERS = frozenset(['ibmvnic', 'ibmveth'])
_VIO_DT_PREFIX = {'ibmvnic': 'vnic@', 'ibmveth': 'l-lan@'}
_DEVICE_TREE_VDEVICE = '/proc/device-tree/vdevice'


class SecureBootNic(Test):
    '''
    Validates NIC driver state after Secure Boot enable on IBM Power LPARs.

    :param driver:      ibmvnic | ibmveth | <pci-driver>
                        (e.g. tg3, mlx5_core)
    :param driver_type: 'pci' for PCIe NIC drivers; omit for VIO NICs
    '''

    def setUp(self):
        '''Install packages, validate Secure Boot state, bring up interface.'''
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
                f"Supported only on RHEL and SUSE; "
                f"detected: {detected_distro.name}"
            )

        lockdown_path = '/sys/kernel/security/lockdown'
        if not genio.is_pattern_in_file(lockdown_path, r'\w'):
            self.cancel(
                "Secure Boot lockdown sysfs not present; "
                "kernel may not support lockdown"
            )
        lockdown_line = genio.read_one_line(lockdown_path)
        match = re.search(r'\[(\w+)\]', lockdown_line)
        active_mode = match.group(1) if match else ''
        if active_mode == 'none':
            self.cancel(
                "Secure Boot is not enabled (lockdown=[none]). "
                "Enable Secure Boot on the LPAR and reboot before running "
                "this test."
            )
        self.log.info("Secure Boot lockdown mode: [%s]", active_mode)

        self.driver = self.params.get('driver', default=None)
        if not self.driver:
            self.cancel(
                "driver is not set. "
                "For VIO NICs choose one of: "
                + ', '.join(sorted(_VIO_NIC_DRIVERS))
                + ". For PCIe NICs set driver_type=pci and "
                "driver=<kernel_driver_name>."
            )
        self.driver = self.driver.strip()

        self.driver_type = (
            self.params.get('driver_type', default='') or ''
        ).strip().lower()

        if self.driver in _VIO_NIC_DRIVERS:
            vio_path = f'/sys/bus/vio/drivers/{self.driver}'
            if not os.path.isdir(vio_path):
                self.cancel(
                    f"VIO driver path not found: {vio_path}; "
                    f"{self.driver} driver not loaded on this LPAR"
                )
        elif self.driver_type == 'pci':
            pci_path = f'/sys/bus/pci/drivers/{self.driver}'
            if not os.path.isdir(pci_path):
                self.cancel(
                    f"PCIe NIC driver '{self.driver}' not found at {pci_path};"
                    f" driver not loaded or not present on this LPAR"
                )
        else:
            self.cancel(
                f"driver '{self.driver}' is not a known VIO NIC "
                f"driver. Known: {', '.join(sorted(_VIO_NIC_DRIVERS))}. "
                f"For a PCIe NIC set driver_type=pci."
            )

        local = LocalHost()
        interfaces = os.listdir('/sys/class/net')
        device = self.params.get('interface', default=None)
        if not device:
            self.cancel("interface is not set in YAML")
        if device in interfaces:
            self.interface = device
        elif (local.validate_mac_addr(device)
              and device in local.get_all_hwaddr()):
            self.interface = local.get_interface_by_hwaddr(device).name
        else:
            self.cancel("interface '%s' not found on this host" % device)

        self.ipaddr = self.params.get('host_ip', default='')
        self.netmask = self.params.get('netmask', default='')
        self.ip_config = self.params.get('ip_config', default=True)
        self.networkinterface = NetworkInterface(self.interface, local)
        if self.ip_config:
            try:
                self.networkinterface.add_ipaddr(self.ipaddr, self.netmask)
                self.networkinterface.save(self.ipaddr, self.netmask)
            except Exception:
                self.networkinterface.save(self.ipaddr, self.netmask)
            self.networkinterface.bring_up()
        if not wait.wait_for(self.networkinterface.is_link_up, timeout=120):
            self.cancel(
                "Link up of %s taking longer than 120 seconds"
                % self.interface
            )

        self.peer = self.params.get('peer_ip', default=None)
        if not self.peer:
            self.cancel("peer_ip is not set in YAML")
        self.peer_user = self.params.get('peer_user', default='root')
        self.peer_password = self.params.get('peer_password', '*',
                                             default=None)
        self.remotehost = RemoteHost(self.peer, self.peer_user,
                                     password=self.peer_password)

        if self.networkinterface.ping_check(self.peer, count=5) is not None:
            self.cancel("No connection to peer %s" % self.peer)

        self.log.info("NIC driver under test : %s", self.driver)
        if self.driver_type:
            self.log.info("NIC driver type       : %s", self.driver_type)

    @staticmethod
    def _cmd_out(cmd):
        '''Run cmd; return decoded stdout.'''
        return process.system_output(
            cmd, shell=True, ignore_status=True
        ).decode('utf-8')

    def _check_lockdown_precondition(self):
        '''Cancel if lockdown sysfs absent or mode is none.
        Returns active mode.'''
        lockdown_path = '/sys/kernel/security/lockdown'
        if not genio.is_pattern_in_file(lockdown_path, r'\w'):
            self.cancel(
                "Lockdown sysfs not present; kernel may not support lockdown"
            )
        lockdown_line = genio.read_one_line(lockdown_path)
        self.log.info("lockdown: %s", lockdown_line)
        match = re.search(r'\[(\w+)\]', lockdown_line)
        active_mode = match.group(1) if match else ''
        if active_mode == 'none':
            self.cancel(
                "Kernel lockdown is [none]; Secure Boot not enabled. "
                "Enable Secure Boot on the LPAR and reboot before running"
            )
        return active_mode

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
            pci_node = os.path.join(dt_root, entry)
            for child in os.listdir(pci_node):
                if child.startswith('ethernet'):
                    return True
        return False

    def test_lockdown_state(self):
        '''Verify lockdown=integrity and IBM DT secure-boot=2
        after SB enable.'''
        active_mode = self._check_lockdown_precondition()

        self.log.info(
            "Checking OS-level Secure Boot state via "
            "linux.is_os_secureboot_enabled()"
        )
        try:
            sb_enabled = linux.is_os_secureboot_enabled()
        except linux.UnsupportedMachineError as exc:
            self.cancel(f"lsprop not available on this machine: {exc}")
        self.log.info("linux.is_os_secureboot_enabled() = %s", sb_enabled)

        failures = []
        if active_mode != 'integrity':
            failures.append(
                f"lockdown: expected [integrity], got [{active_mode}]"
            )
        if not sb_enabled:
            failures.append(
                "DT ibm,secure-boot: '00000002' not found; "
                "secure_boot=2 may not have taken effect"
            )
        if failures:
            self.fail(
                "Kernel lockdown state failures:\n" + '\n'.join(failures)
            )

    def test_interface_visibility(self):
        '''Verify NIC interfaces visible after SB enable and ping peer.'''
        self._check_lockdown_precondition()
        failures = []

        if self.driver in _VIO_NIC_DRIVERS:
            self._check_vio_nic_visibility(failures)
        else:
            self._check_pci_nic_visibility(failures)

        if failures:
            self.fail(
                "NIC interface visibility failures after Secure Boot "
                "enable:\n" + '\n'.join(failures)
            )

        self.log.info("[%s] Pinging %s to confirm interface is up",
                      self.driver, self.peer)
        if self.networkinterface.ping_check(self.peer, count=5) is not None:
            self.fail(
                f"[{self.driver}] ping to {self.peer} via {self.interface} "
                f"failed after Secure Boot enable"
            )

    def test_driver_secureboot_checks(self):
        '''Driver-specific Secure Boot attribute validation.'''
        self._check_lockdown_precondition()
        failures = []

        if self.driver in _VIO_NIC_DRIVERS:
            self._check_vio_nic(failures)
        else:
            self._check_pci_nic(failures)

        if failures:
            self.fail(
                f"Driver-specific Secure Boot check failures "
                f"[{self.driver}]:\n" + '\n'.join(failures)
            )

    def _check_vio_nic_visibility(self, failures):
        '''Check net/ interface registered under every bound VIO slot.'''
        vio_path = f'/sys/bus/vio/drivers/{self.driver}'
        bound = [
            e for e in os.listdir(vio_path)
            if not e.startswith(('bind', 'unbind', 'uevent', 'module'))
            and not e.startswith('.')
        ]
        if not bound:
            failures.append(
                f"[{self.driver}] No VIO devices bound under {vio_path} "
                f"after Secure Boot enable"
            )
            return

        for slot in bound:
            net_dir = os.path.join(vio_path, slot, 'net')
            if not os.path.isdir(net_dir):
                failures.append(
                    f"[{self.driver}] No net/ interface under "
                    f"{vio_path}/{slot} after Secure Boot enable"
                )
                continue
            ifaces = os.listdir(net_dir)
            self.log.info(
                "[%s] Slot %s  net interface(s): %s",
                self.driver, slot, ', '.join(ifaces)
            )

    def _check_pci_nic_visibility(self, failures):
        '''Check at least one PCI device bound to driver
        exposes a net/ interface.'''
        pci_base = '/sys/bus/pci/devices'
        if not os.path.isdir(pci_base):
            failures.append(
                f"[{self.driver}] {pci_base} not found; "
                f"PCI bus not available"
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
            ifaces = os.listdir(net_dir)
            found_any = True
            self.log.info(
                "[%s] %s  net interface(s): %s",
                self.driver, bdf, ', '.join(ifaces)
            )

        if not found_any:
            failures.append(
                f"[{self.driver}] No PCI device bound to '{self.driver}' "
                f"with a net/ interface found after Secure Boot enable"
            )

    def _check_vio_nic(self, failures):
        '''VIO NIC checks: driver binding, device-tree node,
        net/ interface, operstate.'''
        drv = self.driver
        dt_prefix = _VIO_DT_PREFIX[drv]
        vio_path = f'/sys/bus/vio/drivers/{drv}'

        self.log.info("[%s] Checking driver binding under %s", drv, vio_path)
        bound = [
            e for e in os.listdir(vio_path)
            if not e.startswith(('bind', 'unbind', 'uevent', 'module'))
            and not e.startswith('.')
        ]
        if not bound:
            failures.append(
                f"[{drv}] No VIO devices bound under {vio_path} "
                f"after Secure Boot enable"
            )
            return

        self.log.info(
            "[%s] Bound VIO slot(s): %s", drv, ', '.join(bound)
        )

        self.log.info(
            "[%s] Checking %s* node under %s",
            drv, dt_prefix, _DEVICE_TREE_VDEVICE
        )
        if os.path.isdir(_DEVICE_TREE_VDEVICE):
            dt_nodes = [
                e for e in os.listdir(_DEVICE_TREE_VDEVICE)
                if e.startswith(dt_prefix)
            ]
            if not dt_nodes:
                failures.append(
                    f"[{drv}] No {dt_prefix}* node found under "
                    f"{_DEVICE_TREE_VDEVICE}; {drv} VIO adapter not present "
                    f"in device-tree after Secure Boot enable"
                )
            else:
                self.log.info(
                    "[%s] Device-tree node(s): %s",
                    drv, ', '.join(dt_nodes)
                )
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
        else:
            self.log.warning(
                "[%s] %s not found; device-tree check skipped",
                drv, _DEVICE_TREE_VDEVICE
            )

        for slot in bound:
            net_dir = os.path.join(vio_path, slot, 'net')
            if not os.path.isdir(net_dir):
                failures.append(
                    f"[{drv}] No net/ interface registered under "
                    f"{vio_path}/{slot} after Secure Boot enable"
                )
                continue

            ifaces = os.listdir(net_dir)
            self.log.info(
                "[%s] Slot %s  interface(s): %s",
                drv, slot, ', '.join(ifaces)
            )

            if drv == 'ibmvnic':
                pattern = f"ibmvnic {slot}: Partner initialization complete"
                if not dmesg.collect_errors_dmesg(pattern):
                    self.log.info(
                        "[%s] Partner init message for slot %s not in dmesg "
                        "(may have been rotated since boot)", drv, slot
                    )
                else:
                    self.log.info(
                        "[%s] Partner initialization confirmed in dmesg "
                        "for slot %s", drv, slot
                    )

                for iface in ifaces:
                    state_path = os.path.join(
                        '/sys/class/net', iface, 'operstate'
                    )
                    state = (
                        genio.read_file(state_path).strip()
                        if os.path.exists(state_path) else 'unknown'
                    )
                    self.log.info(
                        "[%s] %s (slot %s) operstate=%s",
                        drv, iface, slot, state
                    )
                    if state == 'down':
                        failures.append(
                            f"[{drv}] {iface} (slot {slot}) operstate is "
                            f"'down'; interface not usable after Secure Boot "
                            f"enable"
                        )

    def _check_pci_nic(self, failures):
        '''PCIe NIC checks: device binding, net/ interface,
        ethernet@ DT node, operstate.'''
        drv = self.driver
        pci_base = '/sys/bus/pci/devices'

        self.log.info(
            "[%s] Scanning %s for PCI devices bound to %s",
            drv, pci_base, drv
        )

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
                    "[%s] %s bound to %s but has no net/ subdir (skipping)",
                    drv, bdf, drv
                )
                continue

            ifaces = os.listdir(net_dir)
            found_any = True
            self.log.info(
                "[%s] %s  interface(s): %s", drv, bdf, ', '.join(ifaces)
            )

            if not self._pci_dt_ethernet_exists():
                failures.append(
                    f"[{drv}] No ethernet@ device-tree node found under "
                    f"/proc/device-tree/pci@*/; firmware may not have "
                    f"enumerated the PCIe NIC after Secure Boot enable"
                )
            else:
                self.log.info(
                    "[%s] device-tree ethernet@ node confirmed for %s",
                    drv, bdf
                )

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
                        "[%s] %s is 'down' — may be unplugged or unused port",
                        drv, iface
                    )

        if not found_any:
            failures.append(
                f"[{drv}] No PCI device bound to '{drv}' with a net/ "
                f"interface found after Secure Boot enable"
            )

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
                        "backup file not available, could not restore file.")
        if hasattr(self, 'remotehost'):
            self.remotehost.remote_session.quit()
