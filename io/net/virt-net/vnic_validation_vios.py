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
# Author: Shaik Abdulla <shaik.abdulla1@ibm.com>

"""
vNIC Lifecycle Validation:
  1. Add a vNIC to the LPAR via HMC (chhwres) with a primary SRIOV backing
     device, and optionally a secondary backing device for failover.
  2. Verify the interface is present and operationally up on the Host OS.
  3. Login to VIOS and confirm the vNIC server mapping (lsmap -vnic) is
     correctly established.
  4. Delete the vNIC from the LPAR via HMC:
       a. If a secondary backing device was added, remove it first.
       b. Then remove the primary vNIC slot.
  5. Re-login to VIOS and confirm there are no stale vNIC server entries
     remaining for the deleted slot.
"""

import time

from avocado import Test
from avocado.utils import cpu
from avocado.utils import dmesg
from avocado.utils import genio
from avocado.utils import process
from avocado.utils import wait
from avocado.utils.network.hosts import LocalHost
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils.ssh import Session

try:
    _CPUINFO = genio.read_file('/proc/cpuinfo')
except OSError:
    _CPUINFO = ''

IS_POWER_NV = 'PowerNV' in _CPUINFO
IS_KVM_GUEST = 'qemu' in _CPUINFO


class VnicLifecycle(Test):
    """
    Validates the complete lifecycle of a vNIC on a PowerVM LPAR:
      - Add vNIC via HMC with one or more SRIOV backing devices,
        verify on Host OS (link up + optional ping)
      - Verify mapping on VIOS.
      - Remove vNIC via HMC: secondary backing devices first,
        then the vNIC slot
      - Verify no stale entries remain on VIOS.
    """

    def setUp(self):
        """
        Gather required parameters and establish SSH sessions to HMC and VIOS.
        """
        if "powerpc" not in cpu.get_arch():
            self.cancel("supported only on Power (ppc64le) platform")
        if IS_POWER_NV or IS_KVM_GUEST:
            self.cancel(
                "test is not supported on KVM guest or PowerNV platform")

        self._install_packages()
        self.hmc_ip = self.params.get("hmc_ip", default=None)
        if not self.hmc_ip:
            self.hmc_ip = self._get_mcp_component("HMCIPAddr")
        if not self.hmc_ip:
            self.cancel(
                "Could not determine HMC IP via lsrsrc IBM.MCP "
                "or hmc_ip param")
        self.hmc_username = self.params.get("hmc_username", default=None)
        self.hmc_pwd = self.params.get("hmc_pwd", default=None)
        if not self.hmc_username or not self.hmc_pwd:
            self.cancel("hmc_username and hmc_pwd are required in YAML")

        self.session_hmc = Session(self.hmc_ip, user=self.hmc_username,
                                   password=self.hmc_pwd)
        self.session_hmc.cleanup_master()
        if not self.session_hmc.connect():
            self.cancel("Failed to connect to HMC %s" % self.hmc_ip)
        self.server = self.params.get("manageSystem", default=None)
        if not self.server:
            self.cancel("manageSystem is required in YAML")
        self.lpar = self._get_partition_name("Partition Name")
        if not self.lpar:
            self.cancel("Could not determine LPAR name from lparstat -i")

        cmd = ('lssyscfg -m %s -r lpar --filter lpar_names=%s -F lpar_id'
               % (self.server, self.lpar))
        out = self.session_hmc.cmd(cmd)
        if out.exit_status != 0 or not out.stdout_text.strip():
            self.cancel("Could not retrieve lpar_id for %s" % self.lpar)
        self.lpar_id = out.stdout_text.strip().splitlines()[0]
        slot_raw = self.params.get("slot_num", default=None)
        if not slot_raw:
            self.cancel("slot_num is required in YAML")
        self.slot_num = str(slot_raw)
        if not (3 <= int(self.slot_num) <= 2999):
            self.cancel(
                "slot_num must be in range 3-2999 (got %s)" % self.slot_num)

        self.mac_id = self.params.get("mac_id", default=None)
        if not self.mac_id:
            self.cancel(
                "mac_id is required in YAML (format: aabbccddeeff)")
        self.mac_id = self.mac_id.replace(':', '')
        self.vios_name = self.params.get("vios_name", default=None)
        if not self.vios_name:
            self.cancel("vios_name is required in YAML")
        adapters_raw = self.params.get("sriov_adapter", default=None)
        if not adapters_raw:
            self.cancel(
                "sriov_adapter (physical location code) is required in YAML")
        adapters = str(adapters_raw).split()

        ports_raw = str(self.params.get("sriov_port", default="0")).split()
        bws_raw = str(self.params.get("bandwidth", default="2")).split()
        prios_raw = str(self.params.get("priority", default="50")).split()
        self.auto_failover = str(
            self.params.get("auto_failover", default="1"))
        cmd = ('lssyscfg -m %s -r lpar --filter lpar_names=%s -F lpar_id'
               % (self.server, self.vios_name))
        out = self.session_hmc.cmd(cmd)
        if out.exit_status != 0 or not out.stdout_text.strip():
            self.cancel(
                "Could not retrieve lpar_id for VIOS %s" % self.vios_name)
        self.vios_id = out.stdout_text.strip().splitlines()[0]
        self.backing_devices = []
        for idx, phys_loc in enumerate(adapters):
            port = ports_raw[idx] if idx < len(ports_raw) else ports_raw[-1]
            bw = bws_raw[idx] if idx < len(bws_raw) else bws_raw[-1]
            # Default priorities: 50 for primary, 51+ for each subsequent
            default_prio = str(50 + idx)
            prio = prios_raw[idx] if idx < len(prios_raw) else default_prio
            adapter_id = self._resolve_adapter_id(phys_loc)
            if not adapter_id:
                self.cancel(
                    "SRIOV adapter '%s' not found on %s"
                    % (phys_loc, self.server))
            self.backing_devices.append({
                'phys_loc': phys_loc,
                'adapter_id': adapter_id,
                'port': port,
                'bandwidth': bw,
                'priority': prio,
            })
            label = "primary" if idx == 0 else "secondary[%d]" % idx
            self.log.info(
                "Backing device %s: adapter=%s port=%s bw=%s prio=%s",
                label, phys_loc, port, bw, prio)
        self.vios_ip = self.params.get("vios_ip", default=None)
        self.vios_user = self.params.get("vios_username", default=None)
        self.vios_pwd = self.params.get("vios_pwd", default=None)
        if not all([self.vios_ip, self.vios_user, self.vios_pwd]):
            self.cancel(
                "vios_ip, vios_username and vios_pwd are required in YAML")
        self.session_vios = Session(self.vios_ip, user=self.vios_user,
                                    password=self.vios_pwd)
        self.session_vios.cleanup_master()
        if not wait.wait_for(self.session_vios.connect, timeout=30):
            self.cancel("Failed to connect to VIOS %s" % self.vios_ip)
        self.device_ip = self.params.get("device_ip", default=None)
        self.netmask = self.params.get("netmask", default=None)
        self.peer_ip = self.params.get("peer_ip", default=None)
        self.num_iterations = int(
            self.params.get("num_iterations", default=1))
        if self.num_iterations < 1:
            self.cancel(
                "num_iterations must be >= 1 (got %s)" % self.num_iterations)
        self.local = LocalHost()
        dmesg.clear_dmesg()

    def _resolve_adapter_id(self, phys_loc):
        """
        Look up the SRIOV adapter_id for the given physical location code.

        :param phys_loc: Physical location code string
                         (e.g. 'U78DA.001.XYZ-P1')
        :returns: adapter_id string, or None if not found.
        """
        cmd = ('lshwres -m %s -r sriov --rsubtype adapter '
               '-F phys_loc:adapter_id' % self.server)
        out = self.session_hmc.cmd(cmd)
        for line in out.stdout_text.splitlines():
            if phys_loc in line:
                parts = line.split(':')
                if len(parts) >= 2:
                    return parts[1].strip()
        return None

    def _backing_str(self, dev):
        """
        Return the chhwres backing_devices string for a single backing device
        dict (as stored in self.backing_devices).

        Format: sriov/<vios_name>/<vios_id>/<adapter_id>/<port>/<bw>/<priority>
        """
        return ("sriov/%s/%s/%s/%s/%s/%s"
                % (self.vios_name, self.vios_id,
                   dev['adapter_id'], dev['port'],
                   dev['bandwidth'], dev['priority']))

    @staticmethod
    def _get_mcp_component(component):
        """Query IBM.MCP RSCT class for the requested component."""
        for line in process.system_output(
                'lsrsrc IBM.MCP %s' % component,
                ignore_status=True, shell=True, sudo=True
        ).decode("utf-8").splitlines():
            if component in line:
                return line.split()[-1].strip('{}\"')
        return ''

    @staticmethod
    def _get_partition_name(component):
        """Return the partition name from lparstat -i."""
        for line in process.system_output(
                'lparstat -i', ignore_status=True, shell=True, sudo=True
        ).decode("utf-8").splitlines():
            if component in line:
                return line.split(':')[-1].strip()
        return ''

    def _install_packages(self):
        """Install packages required for vNIC operations."""
        smm = SoftwareManager()
        pkgs = ['ksh', 'src', 'rsct.basic', 'rsct.core.utils',
                'rsct.core', 'DynamicRM', 'powerpc-utils']
        for pkg in pkgs:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel('%s is required for this test' % pkg)

    def _hmc_add_vnic(self, failures):
        """
        Add the vNIC on HMC using chhwres with the primary backing device only
        (index 0 of self.backing_devices).

        backing_devices format:
            sriov/<vios_name>/<vios_id>/<adapter_id>/<port>/<bandwidth>/<priority>

        Secondary backing devices (index >= 1) are added separately via
        _hmc_add_secondary_backings() after the vNIC slot is created.

        :param failures: list to append failure messages to.
        :returns: True on success, False on failure.
        """
        primary = self.backing_devices[0]
        cmd = ('chhwres -m %s --id %s -r virtualio --rsubtype vnic '
               '-o a -s %s '
               '-a "auto_priority_failover=%s,mac_addr=%s,backing_devices=%s"'
               % (self.server, self.lpar_id, self.slot_num,
                  self.auto_failover, self.mac_id,
                  self._backing_str(primary)))
        self.log.info("Adding vNIC: slot=%s mac=%s primary_adapter=%s",
                      self.slot_num, self.mac_id, primary['phys_loc'])
        out = self.session_hmc.cmd(cmd)
        if out.exit_status != 0:
            failures.append(
                "HMC vNIC add failed (slot %s): %s"
                % (self.slot_num, out.stderr_text))
            return False
        return True

    def _hmc_add_secondary_backings(self, failures):
        """
        Add every secondary backing device (index >= 1) to the vNIC slot.

        Uses ``chhwres -o s`` once per device to append each backing entry.
        Only called when self.backing_devices has more than one entry.

        :param failures: list to append failure messages to.
        :returns: True if all secondaries were added, False otherwise.
        """
        success = True
        for idx, dev in enumerate(self.backing_devices[1:], start=1):
            cmd = ('chhwres -m %s --id %s -r virtualio --rsubtype vnic '
                   '-o s -s %s '
                   '-a "backing_devices+=%s"'
                   % (self.server, self.lpar_id, self.slot_num,
                      self._backing_str(dev)))
            self.log.info(
                "Adding secondary backing device [%d] to slot %s: "
                "adapter=%s port=%s",
                idx, self.slot_num, dev['phys_loc'], dev['port'])
            out = self.session_hmc.cmd(cmd)
            if out.exit_status != 0:
                failures.append(
                    "HMC secondary backing [%d] add failed (slot %s): %s"
                    % (idx, self.slot_num, out.stderr_text))
                success = False
            else:
                self.log.info(
                    "Secondary backing device [%d] added to slot %s",
                    idx, self.slot_num)
        return success

    def _hmc_remove_secondary_backings(self, failures):
        """
        Remove all secondary backing devices (index >= 1) from the vNIC slot
        in reverse order.

        Uses ``chhwres -o s`` with ``backing_devices-=`` once per device.
        Must be called **before** _hmc_remove_vnic() to avoid orphan entries.

        :param failures: list to append failure messages to (pass None to
                         log warnings instead of recording failures, e.g.
                         during best-effort cleanup in tearDown).
        :returns: True if all removals succeeded, False otherwise.
        """
        success = True
        for idx, dev in reversed(list(
                enumerate(self.backing_devices[1:], start=1))):
            cmd = ('chhwres -m %s --id %s -r virtualio --rsubtype vnic '
                   '-o s -s %s '
                   '-a "backing_devices-=%s"'
                   % (self.server, self.lpar_id, self.slot_num,
                      self._backing_str(dev)))
            self.log.info(
                "Removing secondary backing device [%d] from "
                "slot %s: adapter=%s port=%s",
                idx, self.slot_num, dev['phys_loc'], dev['port'])
            out = self.session_hmc.cmd(cmd)
            if out.exit_status != 0:
                msg = ("HMC secondary backing [%d] remove failed "
                       "(slot %s): %s"
                       % (idx, self.slot_num, out.stderr_text))
                if failures is not None:
                    failures.append(msg)
                else:
                    self.log.warning(msg)
                success = False
            else:
                self.log.info(
                    "Secondary backing device [%d] removed from slot %s",
                    idx, self.slot_num)
        return success

    def _hmc_remove_vnic(self, failures):
        """
        Remove the vNIC slot from HMC using chhwres.

        All secondary backing devices must already have been removed via
        _hmc_remove_secondary_backings() before this call.

        :param failures: list to append failure messages to (pass None to
                         log warnings instead, e.g. during tearDown cleanup).
        :returns: True on success, False on failure.
        """
        cmd = ('chhwres -m %s --id %s -r virtualio --rsubtype vnic '
               '-o r -s %s'
               % (self.server, self.lpar_id, self.slot_num))
        self.log.info("Removing vNIC: slot=%s", self.slot_num)
        out = self.session_hmc.cmd(cmd)
        if out.exit_status != 0:
            msg = ("HMC vNIC remove failed (slot %s): %s"
                   % (self.slot_num, out.stderr_text))
            if failures is not None:
                failures.append(msg)
            else:
                self.log.warning(msg)
            return False
        return True

    def _hmc_slot_in_use(self):
        """Return True if the slot is already consumed on HMC."""
        cmd = ('lshwres -r virtualio -m %s --rsubtype vnic '
               '--filter "lpar_names=%s" -F slot_num'
               % (self.server, self.lpar))
        out = self.session_hmc.cmd(cmd)
        used = [s.strip() for s in out.stdout_text.splitlines() if s.strip()]
        return self.slot_num in used

    def _find_iface_by_mac(self):
        """
        Return the Linux network interface name matching self.mac_id,
        or empty string if not found.

        Uses ``LocalHost.get_interface_by_hwaddr()`` which iterates all
        interfaces via ``NetworkInterface.get_hwaddr()`` (reads
        /sys/class/net/<iface>/address) -- no netifaces dependency needed.
        """
        mac = ':'.join(self.mac_id[i:i+2] for i in range(0, 12, 2))
        iface_obj = self.local.get_interface_by_hwaddr(mac)
        return iface_obj.name if iface_obj else ''

    def _wait_for_iface(self, present=True, timeout=120):
        """
        Poll until the interface with self.mac_id appears (present=True)
        or disappears (present=False) from the OS.

        :param present: True to wait for the interface to appear,
                        False to wait for it to disappear.
        :param timeout: Maximum seconds to wait (default 120).
        :returns: Interface name when waiting for presence, else ''.
        """
        if present:
            return wait.wait_for(
                self._find_iface_by_mac,
                timeout=timeout, step=5,
                text="waiting for iface") or ''
        gone = wait.wait_for(
            lambda: not self._find_iface_by_mac(),
            timeout=timeout, step=5,
            text="waiting for iface to disappear")
        return '' if gone else self._find_iface_by_mac()

    def _vios_lsmap_vnic(self):
        """Run 'ioscli lsmap -all -vnic' on VIOS and return stdout."""
        out = self.session_vios.cmd("ioscli lsmap -all -vnic")
        return out.stdout_text

    def _step_add_and_verify_hostos(self, failures):
        """
        Add vNIC via HMC and verify the interface appears on Host OS.

        Sequence:
          1. Pre-flight: if the slot is already in use, remove it cleanly
             (secondary backings first, then the slot).
          2. Add the vNIC with the primary backing device.
          3. Add any secondary backing devices in order.
          4. Wait for the interface to appear and come up on the Host OS.

        :param failures: list to append failure messages to.
        :returns: Interface name string, or '' if interface did not appear.
        """
        if self._hmc_slot_in_use():
            self.log.warning(
                "Slot %s already in use - removing it first", self.slot_num)
            if len(self.backing_devices) > 1:
                self._hmc_remove_secondary_backings(failures=None)
            cmd = ('chhwres -m %s --id %s -r virtualio --rsubtype vnic '
                   '-o r -s %s'
                   % (self.server, self.lpar_id, self.slot_num))
            out = self.session_hmc.cmd(cmd)
            if out.exit_status != 0:
                self.log.warning("Pre-run slot cleanup failed: %s",
                                 out.stderr_text)
            time.sleep(10)

        if not self._hmc_add_vnic(failures):
            return ''
        if len(self.backing_devices) > 1:
            self._hmc_add_secondary_backings(failures)
        self.log.info("Waiting for interface to appear on Host OS ...")
        iface = self._wait_for_iface(present=True, timeout=120)
        if not iface:
            failures.append(
                "Interface for MAC %s did not appear on Host OS "
                "within 120 s after vNIC add" % self.mac_id)
            return ''
        self.log.info("Interface %s appeared on Host OS", iface)
        networkinterface = NetworkInterface(iface, self.local)
        networkinterface.bring_up()
        if not wait.wait_for(networkinterface.is_link_up, timeout=60):
            failures.append(
                "Interface %s did not come up (link state DOWN)" % iface)
        else:
            self.log.info("Interface %s is UP", iface)
        if self.device_ip and self.netmask:
            try:
                networkinterface.add_ipaddr(self.device_ip, self.netmask)
            except Exception as err:
                self.log.debug("add_ipaddr failed for %s: %s", iface, err)
                if self.device_ip not in (
                        networkinterface.get_ipaddrs() or []):
                    networkinterface.save(self.device_ip, self.netmask)
                else:
                    self.log.debug(
                        "IP %s already present on %s, skipping nmcli save",
                        self.device_ip, iface)
            if self.peer_ip:
                if networkinterface.ping_check(
                        self.peer_ip, count=5) is not None:
                    failures.append(
                        "Ping to peer %s failed after vNIC add"
                        % self.peer_ip)
                else:
                    self.log.info("Ping to peer %s succeeded", self.peer_ip)

        return iface

    def _step_verify_vios_mapping(self, iface, failures):
        """
        Confirm VIOS shows a vNIC server entry that references our LPAR's
        vNIC (identified by client device name or LPAR id).

        :param iface: Host OS interface name to look for.
        :param failures: list to append failure messages to.
        """
        self.log.info("Verifying vNIC mapping on VIOS ...")
        lsmap_out = self._vios_lsmap_vnic()
        found_mapping = False
        for line in lsmap_out.splitlines():
            if ('Client device name:' + iface in line or
                    'Client device name: ' + iface in line):
                found_mapping = True
                self.log.info("VIOS mapping confirmed: %s", line.strip())
                break
            if self.lpar_id in line and 'vnicserver' in line.lower():
                found_mapping = True
                self.log.info(
                    "VIOS vNIC server entry found for lpar_id %s: %s",
                    self.lpar_id, line.strip())
                break

        if not found_mapping:
            self.log.debug(
                "Full VIOS lsmap -all -vnic output:\n%s", lsmap_out)
            failures.append(
                "VIOS does not show a vNIC mapping for interface %s "
                "(MAC %s, LPAR id %s)"
                % (iface, self.mac_id, self.lpar_id))

    def _step_delete_and_verify_hostos(self, iface, failures):
        """
        Remove vNIC via HMC and confirm the interface is gone from Host OS.

        Removal order:
          1. Remove all secondary backing devices (reverse order).
          2. Remove the primary vNIC slot.

        :param iface: Host OS interface name (used for log messages).
        :param failures: list to append failure messages to.
        """
        if len(self.backing_devices) > 1:
            self.log.info(
                "Step 3a: Removing %d secondary backing device(s) "
                "first (slot %s)",
                len(self.backing_devices) - 1, self.slot_num)
            self._hmc_remove_secondary_backings(failures)

        self.log.info("Step 3b: Removing primary vNIC slot %s", self.slot_num)
        self._hmc_remove_vnic(failures)

        self.log.info(
            "Waiting for interface %s to disappear from Host OS ...", iface)
        remaining = self._wait_for_iface(present=False, timeout=120)
        if remaining:
            failures.append(
                "Interface %s is still present on Host OS 120 s after "
                "vNIC removal" % iface)
        else:
            self.log.info(
                "Interface %s successfully removed from Host OS", iface)

        # Double-check HMC no longer lists the slot
        if self._hmc_slot_in_use():
            failures.append(
                "HMC still lists slot %s after vNIC removal" % self.slot_num)
        else:
            self.log.info("HMC confirmed slot %s is free", self.slot_num)

    def _step_verify_vios_clean(self, iface, failures):
        """
        After vNIC removal, confirm there are no stale vNIC server entries
        on VIOS that still reference the deleted interface **for our LPAR**.

        The lsmap -all -vnic output covers all LPARs on the system.  Many
        LPARs can independently have an interface named e.g. "env3", so
        matching on the client device name alone produces false positives.
        We must also confirm the physloc belongs to our LPAR by checking
        that the "Client device physloc" line in the same block contains
        "V<lpar_id>-" (the VIOS physloc encodes the client LPAR id).

        :param iface: Host OS interface name that was deleted.
        :param failures: list to append failure messages to.
        """
        self.log.info("Checking VIOS for stale vNIC entries ...")
        time.sleep(5)
        lsmap_out = self._vios_lsmap_vnic()
        stale_lines = []
        lpar_physloc_marker = 'V%s-' % self.lpar_id
        block = []
        for line in lsmap_out.splitlines():
            if line.strip() == '':
                self._check_stale_block(
                    block, iface, lpar_physloc_marker, stale_lines)
                block = []
            else:
                block.append(line)
        if block:
            self._check_stale_block(
                block, iface, lpar_physloc_marker, stale_lines)

        if stale_lines:
            self.log.debug(
                "VIOS lsmap output after removal:\n%s", lsmap_out)
            failures.append(
                "Stale vNIC entries found on VIOS after deletion:\n%s"
                % '\n'.join(stale_lines))
        else:
            self.log.info(
                "VIOS is clean - no stale entries for interface %s", iface)

    @staticmethod
    def _check_stale_block(block, iface, lpar_physloc_marker, stale_lines):
        """
        Inspect a single lsmap block and append matching lines to stale_lines.

        :param block: list of lines in the current lsmap block.
        :param iface: interface name to look for.
        :param lpar_physloc_marker: physloc substring identifying our LPAR.
        :param stale_lines: list to append stale 'Client device name' lines to.
        """
        block_text = '\n'.join(block)
        name_match = ('Client device name:' + iface in block_text or
                      'Client device name: ' + iface in block_text)
        lpar_match = lpar_physloc_marker in block_text
        if name_match and lpar_match:
            for bline in block:
                if 'Client device name:' in bline:
                    stale_lines.append(bline.strip())

    def test_vnic_lifecycle(self):
        """
        End-to-end vNIC lifecycle (repeated num_iterations times):
          1. Add vNIC on Host OS (primary + any secondary backing devices) and
             verify interface is up.
          2. Verify correct mapping on VIOS.
          3. Delete vNIC from Host OS (secondary backings first, then slot).
          4. Verify VIOS has no stale entries.

        Set ``num_iterations`` in the YAML file to repeat the full cycle
        more than once (default: 1).
        Set space-separated values in ``sriov_adapter`` (and optionally
        ``sriov_port``, ``bandwidth``, ``priority``) to configure multiple
        backing devices.
        """
        all_failures = []

        for iteration in range(1, self.num_iterations + 1):
            if self.num_iterations > 1:
                self.log.info("*" * 60)
                self.log.info(
                    "Iteration %d / %d", iteration, self.num_iterations)
                self.log.info("*" * 60)

            failures = []
            self.log.info("=" * 60)
            self.log.info("Step 1: Add vNIC and verify on Host OS")
            self.log.info("=" * 60)
            iface = self._step_add_and_verify_hostos(failures)
            self.log.info("=" * 60)
            self.log.info("Step 2: Verify mapping on VIOS")
            self.log.info("=" * 60)
            if iface:
                self._step_verify_vios_mapping(iface, failures)
            else:
                failures.append(
                    "Step 2 skipped: no interface found after vNIC add")
            self.log.info("=" * 60)
            self.log.info(
                "Step 3: Delete vNIC and verify removal on Host OS "
                "(secondary backings first, then slot)")
            self.log.info("=" * 60)
            self._step_delete_and_verify_hostos(
                iface if iface else 'unknown', failures)
            self.log.info("=" * 60)
            self.log.info("Step 4: Verify no stale entries on VIOS")
            self.log.info("=" * 60)
            self._step_verify_vios_clean(
                iface if iface else 'unknown', failures)

            if failures:
                all_failures.append(
                    "Iteration %d failures:\n%s"
                    % (iteration,
                       '\n'.join('  - %s' % f for f in failures)))
                self.log.warning(
                    "Iteration %d FAILED (%d issue(s))",
                    iteration, len(failures))
            else:
                self.log.info("Iteration %d PASSED", iteration)

        self._check_dmesg()

        if all_failures:
            self.fail("vNIC lifecycle test FAILED:\n%s"
                      % '\n'.join(all_failures))
        self.log.info(
            "vNIC lifecycle test PASSED - %d iteration(s) all OK",
            self.num_iterations)

    def _check_dmesg(self):
        """Scan dmesg for known ibmvnic / virtualIO error strings."""
        skip_errors = [
            'uevent: failed to send synthetic uevent',
            'Invalid request detected while CRQ is inactive',
            'failed to send uevent',
            'registration failed',
            'CRQ-init failed, -11',
        ]
        self.log.info("Scanning dmesg for errors ...")
        dmesg.collect_errors_by_level(
            level_check=4, skip_errors=skip_errors)

    def tearDown(self):
        """
        Best-effort cleanup: if the vNIC slot is still present on HMC,
        remove it (secondary backings first, then the slot) so subsequent
        runs start from a clean state.
        """
        if hasattr(self, 'session_hmc'):
            try:
                if self._hmc_slot_in_use():
                    self.log.info(
                        "tearDown: removing leftover vNIC slot %s",
                        self.slot_num)
                    if len(getattr(self, 'backing_devices', [])) > 1:
                        self._hmc_remove_secondary_backings(failures=None)
                    self._hmc_remove_vnic(failures=None)
            except Exception as exc:
                self.log.warning("tearDown HMC cleanup failed: %s", exc)
            self.session_hmc.quit()

        if hasattr(self, 'local') and hasattr(self, 'device_ip'):
            iface = self._find_iface_by_mac()
            if iface and self.device_ip and self.netmask:
                try:
                    ni = NetworkInterface(iface, self.local)
                    ni.remove_ipaddr(self.device_ip, self.netmask)
                except Exception as exc:
                    self.log.warning("tearDown IP cleanup failed: %s", exc)

        if hasattr(self, 'session_vios'):
            self.session_vios.quit()
