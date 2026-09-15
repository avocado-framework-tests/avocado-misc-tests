#!/usr/bin/python

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
# Author: Vaishnavi <vaishnavi@linux.ibm.com>

"""
HNV DLPAR add/remove loop tests, with and without kernel lockdown.
"""

import os
import re
import netifaces

from avocado import Test
from avocado.utils import process
from avocado.utils import genio
from avocado.utils.ssh import Session
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.network.hosts import LocalHost


class HnvAddRemove(Test):
    """
    HNV DLPAR add/remove in a loop, with optional kernel lockdown check.
    Backup device is either veth (hnv_add_remove_veth.yaml) or
    vNIC (hnv_add_remove_vnic.yaml).
    """

    def setUp(self):
        smm = SoftwareManager()
        for pkg in ['src', 'rsct.basic', 'rsct.core.utils', 'NetworkManager',
                    'rsct.core', 'DynamicRM', 'powerpc-utils', 'ksh']:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel('%s is needed for the test to be run' % pkg)

        self.hmc_ip = self.get_mcp_component("HMCIPAddr")
        if not self.hmc_ip:
            self.hmc_ip = self.get_hmc_from_mcproxy()
        if not self.hmc_ip:
            self.cancel("HMC IP not got")

        self.hmc_pwd = self.params.get("hmc_pwd", default=None)
        self.hmc_username = self.params.get("hmc_username", default=None)

        self.lpar = self.get_partition_name("Partition Name")
        if not self.lpar:
            self.cancel("LPAR Name not got from lparstat command")

        self.session = Session(self.hmc_ip, user=self.hmc_username,
                               password=self.hmc_pwd)
        if not self.session.connect():
            self.fail("failed connection to HMC")

        cmd = 'lssyscfg -r sys -F name'
        self.server = ''
        for line in self.session.cmd(cmd).stdout_text.splitlines():
            if line in self.lpar:
                self.server = line
                break
        if not self.server:
            self.cancel("Managed System not got")

        self.sriov_adapter = self.params.get(
            'sriov_adapter', default=None).split(' ')
        self.sriov_port = self.params.get(
            'sriov_port', default=None).split(' ')
        self.mac_id = [mac.replace(':', '') for mac in self.params.get(
            'mac_id', default="02:03:03:03:03:01").split(' ')]
        self.ipaddr = self.params.get('host_ip', default='').split(' ')
        self.netmask = self.params.get('netmasks', default='').split(' ')
        if self.params.get('netmasks'):
            self.prefix = self._netmask_to_cidr(self.netmask[0])
        self.peer_ip = self.params.get('peer_ips', default='').split(' ')

        migratable = self.params.get('migratable', default=True)
        self.migratable = 1 if migratable else 0
        if not self.migratable:
            self.cancel("HNV requires migratable=true in YAML")

        # Backup device: veth or vnic (mutually exclusive YAMLs)
        self.backup_veth_vnetwork = self.params.get(
            'backup_veth_vnetwork', default=None)
        self.vnic_sriov_adapter = self.params.get(
            'vnic_sriov_adapter', default=None)

        if self.backup_veth_vnetwork:
            self.backup_device_type = 'veth'
        elif self.vnic_sriov_adapter:
            self.backup_device_type = 'vnic'
            self.vnic_port_id = self.params.get('vnic_port_id', default=None)
            self.vnic_adapter_id = self._get_adapter_id(
                self.vnic_sriov_adapter)
            self.priority = self.params.get('failover_priority', default='50')
            self.max_capacity = self.params.get('max_capacity', default='10')
            self.capacity = self.params.get('capacity', default='2')
            self.vios_name = self.params.get('vios_name', default=None)
            cmd = ('lssyscfg -m %s -r lpar --filter lpar_names=%s -F lpar_id'
                   % (self.server, self.vios_name))
            self.vios_id = self.session.cmd(cmd).stdout_text.split()[0]
            self.backup_vnic_backing_device = (
                'sriov/%s/%s/%s/%s/%s/%s/%s' % (
                    self.vios_name, self.vios_id, self.vnic_adapter_id,
                    self.vnic_port_id, self.capacity,
                    self.priority, self.max_capacity))
        else:
            self.cancel("Provide backup_veth_vnetwork or vnic_sriov_adapter")

        self.local = LocalHost()
        self.num_of_dlpar = int(self.params.get('num_of_dlpar', default=1))

        # Lockdown
        self.lockdown_path = "/sys/kernel/security/lockdown"
        self.lockdown_mode = self.params.get(
            'lockdown_mode', default='integrity')
        self.lockdown_enable = self.params.get(
            'lockdown_enable', default=False)

        if self.lockdown_enable:
            if not self._check_lockdown_support():
                self.cancel("Kernel lockdown not supported (%s not found)"
                            % self.lockdown_path)
            if self._get_lockdown_state() != self.lockdown_mode:
                if not self._set_lockdown_mode(self.lockdown_mode):
                    self.fail("Failed to set lockdown to %s"
                              % self.lockdown_mode)
            self.log.info("Lockdown active: %s", self._get_lockdown_state())

    # ---- Test methods ------------------------------------------------

    def test_hnv_dlpar_loop(self):
        """Add and remove HNV logical device num_of_dlpar times."""
        for i in range(self.num_of_dlpar):
            self.log.info("HNV DLPAR iteration %d of %d",
                          i + 1, self.num_of_dlpar)
            self._hnv_add()
            self._hnv_remove()

    def test_hnv_dlpar_loop_with_lockdown(self):
        """
        Same loop as test_hnv_dlpar_loop with kernel lockdown enabled.
        Asserts lockdown state is preserved before and after every iteration.
        Requires lockdown_enable: true in YAML.
        """
        if not self.lockdown_enable:
            self.cancel("Set lockdown_enable: true in YAML to run this test")

        for i in range(self.num_of_dlpar):
            self.log.info("HNV DLPAR (lockdown=%s) iteration %d of %d",
                          self.lockdown_mode, i + 1, self.num_of_dlpar)
            current = self._get_lockdown_state()
            if current != self.lockdown_mode:
                self.fail("Lockdown changed to '%s' before iteration %d"
                          % (current, i + 1))
            self._hnv_add()
            self._hnv_remove()
            current = self._get_lockdown_state()
            if current != self.lockdown_mode:
                self.fail("Lockdown changed to '%s' after iteration %d"
                          % (current, i + 1))

    def test_hnv_max_logical_ports(self):
        """
        Validate the 10-port HNV limit.
        - Adds ports one by one (HMC assigns MACs) until total reaches 10.
        - Verifies an 11th add is rejected by HMC.
        - For each newly added bond: assign ipaddr[0], ping peer, flush IP.
          The same IP is reused across all bonds sequentially.
        - Removes all newly added ports and confirms count restored.
        """
        slot = self.sriov_adapter[0]
        port = self.sriov_port[0]
        ipaddr = self.ipaddr[0]
        peer_ip = self.peer_ip[0]
        cidr = '%s/%s' % (ipaddr, self.prefix)
        added_macs = []

        existing_count = self._count_hnv_ports()
        self.log.info("Existing migratable ports: %d", existing_count)
        to_add = 10 - existing_count
        if to_add <= 0:
            self.cancel(
                "Already at or above 10 migratable ports (%d present)"
                % existing_count)

        try:
            # --- Phase 1: add ports up to 10 -------------------------
            self.log.info("Adding %d port(s) to reach limit of 10", to_add)
            for i in range(to_add):
                self._device_add_remove(slot, port, None, '', 'add')
                mac = self._get_latest_port_mac(added_macs)
                added_macs.append(mac)
                self.log.info("Added port %d of %d, MAC=%s",
                              i + 1, to_add, mac)

            count = self._count_hnv_ports()
            if count != 10:
                self.fail("Expected 10 ports after add, got %d" % count)

            # --- Phase 2: verify 11th add is rejected -----------------
            self.log.info("Attempting to add 11th port (must be rejected)")
            self._device_add_remove(
                slot, port, None, '', 'add', expect_fail=True)
            if self._count_hnv_ports() != 10:
                self.fail("Port count changed after rejected 11th add")
            self.log.info("11th add correctly rejected by HMC")

            # --- Phase 3: assign IP, ping, flush -- one bond at a time
            for idx, mac in enumerate(added_macs):
                bond = self._get_hnv_bond(mac)
                self.log.info("Bond %d/%d: %s (MAC %s)",
                              idx + 1, len(added_macs), bond, mac)

                ret = process.run(
                    'ip addr add %s dev %s' % (cidr, bond),
                    ignore_status=True, sudo=True)
                if ret.exit_status:
                    self.fail("ip addr add failed on %s: %s"
                              % (bond, ret.stderr_text))

                if NetworkInterface(bond, self.local).ping_check(
                        peer_ip, count=5) is not None:
                    self.fail("Ping failed on bond %s" % bond)
                self.log.info("Ping OK on bond %s", bond)

                ret = process.run(
                    'ip addr flush dev %s' % bond,
                    ignore_status=True, sudo=True)
                if ret.exit_status:
                    self.fail("ip addr flush failed on %s: %s"
                              % (bond, ret.stderr_text))
                self.log.info("IP flushed from bond %s", bond)

        finally:
            # --- Phase 4: remove all newly added ports ----------------
            # Runs unconditionally -- whether ping passed or failed.
            self.log.info("Removing %d added port(s)", len(added_macs))
            for mac in added_macs:
                try:
                    logical_port_id = self._get_logical_port_id(mac)
                    self._device_add_remove(
                        slot, '', '', logical_port_id, 'remove')
                except Exception as exc:
                    self.log.warning("Failed to remove port MAC %s: %s",
                                     mac, exc)
            remaining = self._count_hnv_ports()
            if remaining != existing_count:
                self.log.warning(
                    "Cleanup incomplete: expected %d ports, got %d",
                    existing_count, remaining)
            else:
                self.log.info("Restored to %d port(s)", existing_count)

    # ---- HNV add / remove --------------------------------------------

    def _hnv_add(self):
        """Add HNV logical device, bring up bond, verify ping."""
        for slot, port, mac, ipaddr, netmask, peer_ip in zip(
                self.sriov_adapter, self.sriov_port, self.mac_id,
                self.ipaddr, self.netmask, self.peer_ip):
            if self._list_device(mac):
                self.cancel("Device %s already present" % mac)
            self._device_add_remove(slot, port, mac, '', 'add')
            if not self._list_device(mac):
                self.fail("failed to list logical device after add")
            bond_device = self._get_hnv_bond(mac)
            ret = process.run(
                'nmcli c mod id %s ipv4.method manual ipv4.address %s/%s'
                % (bond_device, ipaddr, self.prefix), ignore_status=True)
            if ret.exit_status:
                self.fail("nmcli ip config failed with %s" % ret.exit_status)
            ret = process.run('nmcli c up %s' % bond_device,
                              ignore_status=True)
            if ret.exit_status:
                self.fail("nmcli c up failed with %s" % ret.exit_status)
            if NetworkInterface(bond_device, self.local).ping_check(
                    peer_ip, count=5) is not None:
                self.fail("ping check failed for hnv bond device")

    def _hnv_remove(self):
        """Bring down bond and remove the HNV logical device."""
        for mac, slot in zip(self.mac_id, self.sriov_adapter):
            bond_device = self._get_hnv_bond(mac)
            for cmd in ['nmcli c down %s' % bond_device,
                        'nmcli c del %s' % bond_device]:
                ret = process.run(cmd, ignore_status=True)
                if ret.exit_status:
                    self.fail("'%s' failed with %s" % (cmd, ret.exit_status))
            logical_port_id = self._get_logical_port_id(mac)
            self._device_add_remove(slot, '', '', logical_port_id, 'remove')
            if self._list_device(mac):
                self.fail("failed to remove migratable logical device")

    def _device_add_remove(self, slot, port, mac, logical_id, operation,
                           expect_fail=False):
        """Issue chhwres add or remove for an HNV (migratable) logical port.

        When expect_fail=True the caller expects HMC to reject the command
        (e.g. 11th port add); a zero exit status is treated as a failure.
        """
        adapter_id = self._get_adapter_id(slot)

        if self.backup_device_type == 'veth':
            backup_str = (',backup_device_type=%s,'
                          'backup_veth_vnetwork=%s'
                          % (self.backup_device_type,
                             self.backup_veth_vnetwork))
        else:
            backup_str = (',backup_device_type=%s,'
                          'backup_vnic_backing_device=%s'
                          % (self.backup_device_type,
                             self.backup_vnic_backing_device))

        if operation == 'add':
            if mac:
                cmd = ('chhwres -r sriov -m %s --rsubtype logport '
                       '-o a -p %s -a "adapter_id=%s,phys_port_id=%s,'
                       'logical_port_type=eth,mac_addr=%s,'
                       'migratable=%s%s"'
                       % (self.server, self.lpar, adapter_id, port,
                          mac, self.migratable, backup_str))
            else:
                # HMC auto-assigns MAC
                cmd = ('chhwres -r sriov -m %s --rsubtype logport '
                       '-o a -p %s -a "adapter_id=%s,phys_port_id=%s,'
                       'logical_port_type=eth,migratable=%s%s"'
                       % (self.server, self.lpar, adapter_id, port,
                          self.migratable, backup_str))
        else:
            cmd = ('chhwres -r sriov -m %s --rsubtype logport '
                   '-o r -p %s -a "adapter_id=%s,logical_port_id=%s"'
                   % (self.server, self.lpar, adapter_id, logical_id))

        self.log.debug("chhwres %s: %s", operation, cmd)
        result = self.session.cmd(cmd)
        if expect_fail:
            if result.exit_status == 0:
                self.fail("Expected HMC to reject %s but it succeeded"
                          % operation)
        elif result.exit_status != 0:
            self.fail("SR-IOV %s failed: %s"
                      % (operation, result.stdout_text))

    # ---- SR-IOV query helpers ----------------------------------------

    def _get_adapter_id(self, slot):
        output = self.session.cmd(
            "lshwres -m %s -r sriov --rsubtype adapter "
            "-F phys_loc:adapter_id" % self.server)
        for line in output.stdout_text.splitlines():
            if slot in line:
                return line.split(':')[-1]
        self.cancel("adapter not found at slot %s" % slot)

    def _get_logical_port_id(self, mac):
        output = self.session.cmd(
            "lshwres -r sriov --rsubtype logport -m %s "
            "--level eth | grep %s | grep %s" % (self.server, self.lpar, mac))
        return output.stdout_text.split(',')[6].split('=')[-1]

    def _list_device(self, mac):
        output = self.session.cmd(
            'lshwres -r sriov --rsubtype logport -m %s '
            '--level eth --filter "lpar_names=%s"' % (self.server, self.lpar))
        return mac in output.stdout_text

    def _count_hnv_ports(self):
        """Return count of migratable logical ports on this LPAR."""
        output = self.session.cmd(
            'lshwres -r sriov --rsubtype logport -m %s '
            '--level eth --filter "lpar_names=%s" -F migratable'
            % (self.server, self.lpar))
        return sum(1 for line in output.stdout_text.splitlines()
                   if line.strip() == '1')

    def _get_latest_port_mac(self, known_macs):
        """Return MAC of the most recently added migratable port."""
        output = self.session.cmd(
            'lshwres -r sriov --rsubtype logport -m %s '
            '--level eth --filter "lpar_names=%s" -F mac_addr,migratable'
            % (self.server, self.lpar))
        for line in reversed(output.stdout_text.splitlines()):
            parts = line.strip().split(',')
            if len(parts) == 2 and parts[1].strip() == '1':
                mac = parts[0].strip().replace(':', '')
                if mac not in known_macs:
                    return mac
        self.fail("Could not determine MAC of newly added port")

    def _get_hnv_bond(self, mac):
        for bond in genio.read_one_line(
                "/sys/class/net/bonding_masters").split():
            if mac in netifaces.ifaddresses(
                    bond)[17][0]['addr'].replace(':', ''):
                return bond
        self.fail("No bond found for MAC %s" % mac)

    # ---- Lockdown helpers --------------------------------------------

    def _check_lockdown_support(self):
        """Return True if /sys/kernel/security/lockdown exists."""
        return os.path.exists(self.lockdown_path)

    def _get_lockdown_state(self):
        """Return active lockdown level: none | integrity | confidentiality."""
        try:
            output = process.system_output(
                'cat %s' % self.lockdown_path,
                shell=True, sudo=True).decode('utf-8')
            for level in ('none', 'integrity', 'confidentiality'):
                if '[%s]' % level in output:
                    return level
        except Exception as exc:
            self.log.error("Failed to read lockdown state: %s", exc)
        return None

    def _set_lockdown_mode(self, mode):
        """Write mode to lockdown sysfs and confirm. Returns True on
        success."""
        if not self._check_lockdown_support():
            return False
        if self._get_lockdown_state() == mode:
            return True
        try:
            process.run('echo "%s" > %s' % (mode, self.lockdown_path),
                        shell=True, sudo=True)
            return self._get_lockdown_state() == mode
        except Exception as exc:
            self.log.error("Error setting lockdown to %s: %s", mode, exc)
            return False

    # ---- Static utilities --------------------------------------------

    @staticmethod
    def _netmask_to_cidr(netmask):
        return sum(bin(int(b)).count('1') for b in netmask.split('.'))

    @staticmethod
    def get_mcp_component(component):
        """Probe IBM.MCP for component and return its value."""
        for line in process.system_output(
                'lsrsrc IBM.MCP %s' % component,
                ignore_status=True, shell=True,
                sudo=True).decode('utf-8').splitlines():
            if component in line:
                return line.split()[-1].strip('{}\"')
        return ''

    @staticmethod
    def get_hmc_from_mcproxy():
        """Return HMC hostname from lssrc -ls mcproxy, or ''."""
        for line in process.system_output(
                'lssrc -ls mcproxy',
                ignore_status=True, shell=True,
                sudo=True).decode('utf-8').splitlines():
            match = re.match(r'\s*Hostname:\s*(\S+)', line)
            if match:
                return match.group(1)
        return ''

    @staticmethod
    def get_partition_name(component):
        """Return partition name from lparstat -i."""
        for line in process.system_output(
                'lparstat -i', ignore_status=True,
                shell=True, sudo=True).decode('utf-8').splitlines():
            if component in line:
                return line.split(':')[-1].strip()
        return ''

    def tearDown(self):
        if hasattr(self, 'session') and self.session:
            self.session.quit()
