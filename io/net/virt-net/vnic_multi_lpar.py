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
# Copyright: 2024 IBM
# Author: Vaishnavi <vaishnavi@linux.vnet.ibm.com>

'''
Tests for vNIC hot-add and hot-remove across two LPARs sharing the same
SR-IOV physical adapter (or different ports on the same adapter).
'''

import re
import time
import netifaces  # pylint: disable=import-error
from avocado import Test
from avocado.utils import process
from avocado.utils import distro
from avocado.utils import dmesg
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils.process import CmdError
from avocado.utils.network.exceptions import NWException
from avocado import skipIf, skipUnless
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.network.hosts import LocalHost
from avocado.utils.ssh import Session
from avocado.utils import wait

IS_POWER_NV = 'PowerNV' in open('/proc/cpuinfo', 'r').read()
IS_KVM_GUEST = 'qemu' in open('/proc/cpuinfo', 'r').read()


class VnicMultiLpar(Test):

    '''
    Add a vNIC device to two separate LPARs (LPAR1 = local, LPAR2 = remote)
    backed by the same SR-IOV adapter.

    test_multi_lpar_same_adapter:
        - Add vNIC (adapter A, port 0) to LPAR1 and LPAR2
        - Ping from LPAR1 to peer; ping from LPAR2 to peer
        - Remove vNIC from both LPARs

    test_multi_lpar_different_ports:
        - Add vNIC (adapter A, port 0) to LPAR1
        - Add vNIC (adapter A, port 1) to LPAR2
        - Ping from LPAR1 to peer; ping from LPAR2 to peer
        - Remove vNIC from both LPARs
    '''

    @skipUnless("ppc" in distro.detect().arch,
                "supported only on Power platform")
    @skipIf(IS_POWER_NV or IS_KVM_GUEST,
            "This test is not supported on KVM guest or PowerNV platform")
    def setUp(self):
        '''
        Install packages and gather test parameters.
        '''
        self._install_packages()
        self.hmc_ip = wait.wait_for(
            lambda: self._get_mcp_component("HMCIPAddr"), timeout=30)
        if not self.hmc_ip:
            self.log.info("HMCIPAddr not found via lsrsrc IBM.MCP, "
                          "falling back to lssrc -ls mcproxy for hostname")
            self.hmc_ip = self.get_hmc_from_mcproxy()
        if not self.hmc_ip:
            self.cancel("HMC IP not obtained")
        self.hmc_username = self.params.get("hmc_username", default=None)
        self.hmc_pwd = self.params.get("hmc_pwd", default=None)

        # Local LPAR name (the machine running this test)
        self.lpar1 = self._get_partition_name("Partition Name")
        if not self.lpar1:
            self.cancel("Could not get local LPAR name from lparstat")

        self.session_hmc = Session(self.hmc_ip, user=self.hmc_username,
                                   password=self.hmc_pwd)
        self.session_hmc.cleanup_master()
        if not self.session_hmc.connect():
            self.cancel("Failed to connect to HMC")

        self.server = self.params.get("manageSystem", default=None)
        if not self.server:
            self.cancel("manageSystem parameter not set")

        # Remote LPAR2 credentials and name
        self.lpar2 = self.params.get("lpar2_name", default=None)
        if not self.lpar2:
            self.cancel("lpar2_name parameter not set")
        self.lpar2_ip = self.params.get("lpar2_ip", default=None)
        self.lpar2_user = self.params.get("lpar2_user", default="root")
        self.lpar2_pwd = self.params.get("lpar2_pwd", default=None)
        if not self.lpar2_ip or not self.lpar2_pwd:
            self.cancel("lpar2_ip / lpar2_pwd not set")

        # Resolve LPAR IDs from HMC
        self.lpar1_id = self._get_lpar_id(self.lpar1)
        self.lpar2_id = self._get_lpar_id(self.lpar2)

        # SR-IOV adapter and VIOS
        self.vios_name = self.params.get("vios_name", default=None)
        if not self.vios_name:
            self.cancel("vios_name parameter not set")
        self.vios_id = self._get_lpar_id(self.vios_name)

        self.sriov_adapter = self.params.get("sriov_adapter", default=None)
        if not self.sriov_adapter:
            self.cancel("sriov_adapter parameter not set")
        self.adapter_id = self._resolve_adapter_id(self.sriov_adapter)

        self.bandwidth = self.params.get("bandwidth", default=2)
        self.auto_failover = self.params.get("auto_failover", default="1")

        # Per-LPAR slot, MAC, IP, netmask
        self.lpar1_slot = str(self.params.get("lpar1_slot_num", default=None))
        self.lpar2_slot = str(self.params.get("lpar2_slot_num", default=None))
        if not self.lpar1_slot or not self.lpar2_slot:
            self.cancel("lpar1_slot_num and lpar2_slot_num must be set")
        for slot in (self.lpar1_slot, self.lpar2_slot):
            if int(slot) < 3 or int(slot) > 2999:
                self.cancel("Slot %s invalid. Valid range: 3-2999" % slot)

        self.lpar1_mac = self.params.get(
            "lpar1_mac_id", default="02:04:01:00:00:01").replace(':', '')
        self.lpar2_mac = self.params.get(
            "lpar2_mac_id", default="02:04:01:00:00:02").replace(':', '')

        self.lpar1_ip = self.params.get("lpar1_device_ip", default=None)
        self.lpar2_ip_dev = self.params.get("lpar2_device_ip", default=None)
        self.lpar1_netmask = self.params.get("lpar1_netmask",
                                             default="255.255.255.0")
        self.lpar2_netmask = self.params.get("lpar2_netmask",
                                             default="255.255.255.0")
        self.peer_ip = self.params.get("peer_ip", default=None)
        if not all([self.lpar1_ip, self.lpar2_ip_dev, self.peer_ip]):
            self.cancel(
                "lpar1_device_ip, lpar2_device_ip, peer_ip must be set")

        dmesg.clear_dmesg()
        self.local = LocalHost()

        # SSH session to LPAR2 (opened lazily inside each test method)
        self.session_lpar2 = None

    # ── static helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _get_mcp_component(component):
        '''Probe IBM.MCP for the given component.'''
        for line in process.system_output(
                'lsrsrc IBM.MCP %s' % component,
                ignore_status=True, shell=True,
                sudo=True).decode("utf-8").splitlines():
            if component in line:
                return line.split()[-1].strip('{}\"')
        return ''

    @staticmethod
    def _get_partition_name(component):
        '''Return local partition name from lparstat -i.'''
        for line in process.system_output(
                'lparstat -i', ignore_status=True,
                shell=True, sudo=True).decode("utf-8").splitlines():
            if component in line:
                return line.split(':')[-1].strip()
        return ''

    @staticmethod
    def _find_device(mac_addrs):
        '''Find local network device matching the given 12-char hex MAC.'''
        mac = ':'.join(mac_addrs[i:i+2] for i in range(0, 12, 2))
        for device in netifaces.interfaces():
            addrs = netifaces.ifaddresses(device)
            if 17 in addrs and mac in addrs[17][0]['addr']:
                return device
        return ''

    @staticmethod
    def get_hmc_from_mcproxy():
        '''
        Fallback: parse 'lssrc -ls mcproxy' for the HMC hostname when
        'lsrsrc IBM.MCP HMCIPAddr' returns no IP address.
        Looks for a line of the form:
            Hostname: ://example.com
        and returns the hostname string, or '' if not found.
        '''
        for line in process.system_output('lssrc -ls mcproxy',
                                          ignore_status=True, shell=True,
                                          sudo=True).decode("utf-8") \
                                                    .splitlines():
            match = re.match(r'\s*Hostname:\s*(\S+)', line)
            if match:
                return match.group(1)
        return ''

    # ── instance helpers ─────────────────────────────────────────────────────

    def _get_lpar_id(self, lpar_name):
        '''Resolve an LPAR name to its numeric ID via HMC.'''
        cmd = ('lssyscfg -m %s -r lpar --filter lpar_names=%s -F lpar_id'
               % (self.server, lpar_name))
        return self.session_hmc.cmd(cmd).stdout_text.split()[0]

    def _resolve_adapter_id(self, adapter_loc):
        '''Translate an SR-IOV adapter location code to its HMC adapter_id.'''
        cmd = ('lshwres -m %s -r sriov --rsubtype adapter'
               ' -F phys_loc:adapter_id' % self.server)
        for line in self.session_hmc.cmd(cmd).stdout_text.splitlines():
            if adapter_loc in line:
                return line.split(':')[1]
        self.cancel("SR-IOV adapter %s not found on %s"
                    % (adapter_loc, self.server))

    def _lpar_vnic_add(self, lpar_id, slot, mac, sriov_port, priority="1"):
        '''Add a vNIC to the specified LPAR via HMC chhwres.'''
        backing = ("backing_devices=sriov/%s/%s/%s/%s/%s/%s"
                   % (self.vios_name, self.vios_id, self.adapter_id,
                      sriov_port, self.bandwidth, priority))
        cmd = ('chhwres -m %s --id %s -r virtualio --rsubtype vnic '
               '-o a -s %s -a "auto_priority_failover=%s,mac_addr=%s,%s"'
               % (self.server, lpar_id, slot,
                  self.auto_failover, mac, backing))
        output = self.session_hmc.cmd(cmd)
        if output.exit_status != 0:
            self.log.debug(output.stderr)
            self.fail("vNIC add failed for lpar_id=%s slot=%s"
                      % (lpar_id, slot))
        else:
            self.log.info("vNIC added successfully for lpar_id=%s slot=%s",
                          lpar_id, slot)

    def _lpar_vnic_remove(self, lpar_id, slot):
        '''Remove a vNIC from the specified LPAR via HMC chhwres.'''
        cmd = ('chhwres -m %s --id %s -r virtualio --rsubtype vnic -o r -s %s'
               % (self.server, lpar_id, slot))
        output = self.session_hmc.cmd(cmd)
        if output.exit_status != 0:
            self.log.debug(output.stderr)
            self.log.error("vNIC remove failed for lpar_id=%s slot=%s",
                           lpar_id, slot)

    def _lpar_vnic_listed(self, lpar_name, slot):
        '''Return True when lshwres shows the vNIC in the given slot.'''
        cmd = ('lshwres -r virtualio -m %s --rsubtype vnic '
               '--filter "lpar_names=%s,slots=%s"'
               % (self.server, lpar_name, slot))
        try:
            output = self.session_hmc.cmd(cmd).stdout_text
        except CmdError as details:
            self.log.debug(str(details))
            return False
        return 'slot_num=%s' % slot in output

    def _configure_local_vnic(self, mac, device_ip, netmask):
        '''Configure IP on the local (LPAR1) vNIC interface.

        Returns (device_name, NetworkInterface).

        Flushes any leftover address from a previous run before assigning so
        that a re-run after a partial failure does not trip over
        "Address already assigned".
        '''
        device = self._find_device(mac)
        if not device:
            self.fail("Local interface with MAC %s not found" % mac)
        ni = NetworkInterface(device, self.local)
        time.sleep(5)
        # Remove any stale address silently — harmless if none is set.
        try:
            ni.remove_ipaddr(device_ip, netmask)
        except Exception:
            pass
        try:
            ni.add_ipaddr(device_ip, netmask)
            ni.save(device_ip, netmask)
        except NWException as exc:
            self.fail("Failed to configure IP %s on local %s: %s"
                      % (device_ip, device, exc))
        ni.bring_up()
        if not wait.wait_for(ni.is_link_up, timeout=120):
            self.fail("Local interface %s did not come up" % device)
        return device, ni

    def _configure_remote_vnic(self, mac, device_ip, netmask):
        '''Configure IP on the remote (LPAR2) vNIC interface via SSH.

        Uses a quoting-safe single command (no awk/grep-oP patterns that SSH
        would strip) and parses the output in Python.
        '''
        mac_colon = ':'.join(mac[i:i+2] for i in range(0, 12, 2))
        # ibmvnic may take a few seconds to register the interface after
        # HMC add completes; wait before probing.
        time.sleep(10)
        # "ip -o link show" emits one line per interface; each line is:
        #   <idx>: <ifname>: <flags> ... link/ether <mac> ...
        # No shell metacharacters needed - grep -i on a plain MAC is safe.
        out = self.session_lpar2.cmd(
            "ip -o link show | grep -i %s" % mac_colon,
            ignore_status=True).stdout_text.strip()
        if not out:
            self.fail("LPAR2 interface with MAC %s not found" % mac_colon)
        # Parse the device name from the first matching line:
        #   "2: env10: <BROADCAST,...> ... link/ether 02:04:02:00:00:02 ..."
        device = out.splitlines()[0].split(':')[1].strip()
        self.session_lpar2.cmd(
            "ip addr add %s/%s dev %s" % (device_ip, netmask, device),
            ignore_status=True)
        self.session_lpar2.cmd("ip link set %s up" % device)
        self.log.info("LPAR2: configured %s with IP %s", device, device_ip)
        return device

    def _check_dmesg_error(self):
        '''Check dmesg for known ibmvnic error patterns.'''
        skip_errors = [
            'uevent: failed to send synthetic uevent',
            'Invalid request detected while CRQ is inactive',
            'failed to send uevent', 'registration failed',
            'CRQ-init failed, -11']
        self.log.info("Gathering kernel errors if any")
        try:
            dmesg.collect_errors_by_level(level_check=4,
                                          skip_errors=skip_errors)
        except Exception as exc:
            self.log.info(exc)
            self.fail("test failed, check dmesg log in debug log")

    def _install_packages(self):
        '''Install packages required by virt-net tests.'''
        smm = SoftwareManager()
        detected_distro = distro.detect()
        packages = ['ksh', 'src', 'rsct.basic', 'rsct.core.utils',
                    'rsct.core', 'DynamicRM', 'powerpc-utils']
        self.log.info("Test is running on: %s", detected_distro.name)
        for pkg in packages:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel('%s is needed for the test to be run' % pkg)

    # ── test methods ─────────────────────────────────────────────────────────

    def test_multi_lpar_same_adapter(self):
        '''
        Add a vNIC backed by adapter A (port 0) to LPAR1 and to LPAR2.
        Ping from LPAR1 and verify LPAR2 can ping its peer.
        Remove the vNIC from both LPARs.

        YAML: vnic_multi_lpar_same_adapter.yaml
        Required keys: manageSystem, hmc_username, hmc_pwd, vios_name,
          sriov_adapter, lpar2_name, lpar2_ip, lpar2_user, lpar2_pwd,
          lpar1_slot_num, lpar2_slot_num, lpar1_mac_id, lpar2_mac_id,
          lpar1_device_ip, lpar2_device_ip, lpar1_netmask, lpar2_netmask,
          peer_ip, sriov_port, bandwidth, auto_failover

        :avocado: tags=net,vnic,dlpar,multi_lpar,privileged,power
        '''
        sriov_port = str(self.params.get("sriov_port", default="0"))

        self.session_lpar2 = Session(self.lpar2_ip, user=self.lpar2_user,
                                     password=self.lpar2_pwd)
        self.session_lpar2.cleanup_master()
        if not wait.wait_for(self.session_lpar2.connect, timeout=30):
            self.cancel("Failed to connect to LPAR2 at %s" % self.lpar2_ip)

        ping_failures = []
        lpar1_added = False
        lpar2_added = False
        lpar1_device = None
        lpar2_device = None

        try:
            # ── Phase 1: add vNIC to LPAR1 ───────────────────────────────────
            self.log.info("Adding vNIC to LPAR1 slot=%s mac=%s port=%s",
                          self.lpar1_slot, self.lpar1_mac, sriov_port)
            self._lpar_vnic_add(self.lpar1_id, self.lpar1_slot,
                                self.lpar1_mac, sriov_port)
            if not self._lpar_vnic_listed(self.lpar1, self.lpar1_slot):
                self.fail("lshwres does not list vNIC for LPAR1 after add")
            lpar1_added = True
            lpar1_device, lpar1_ni = self._configure_local_vnic(
                self.lpar1_mac, self.lpar1_ip, self.lpar1_netmask)

            # ── Phase 2: add vNIC to LPAR2 ───────────────────────────────────
            self.log.info("Adding vNIC to LPAR2 slot=%s mac=%s port=%s",
                          self.lpar2_slot, self.lpar2_mac, sriov_port)
            self._lpar_vnic_add(self.lpar2_id, self.lpar2_slot,
                                self.lpar2_mac, sriov_port)
            if not self._lpar_vnic_listed(self.lpar2, self.lpar2_slot):
                self.fail("lshwres does not list vNIC for LPAR2 after add")
            lpar2_added = True
            lpar2_device = self._configure_remote_vnic(
                self.lpar2_mac, self.lpar2_ip_dev, self.lpar2_netmask)

            # ── Phase 3: ping checks ─────────────────────────────────────────
            self.log.info("Ping check: LPAR1 interface %s → peer %s",
                          lpar1_device, self.peer_ip)
            if lpar1_ni.ping_check(self.peer_ip, count=5) is not None:
                msg = "LPAR1 ping to %s failed" % self.peer_ip
                self.log.error(msg)
                ping_failures.append(msg)
            else:
                self.log.info("LPAR1 ping OK")

            self.log.info("Ping check: LPAR2 interface %s → peer %s",
                          lpar2_device, self.peer_ip)
            ping_out = self.session_lpar2.cmd(
                "ping -c 5 %s" % self.peer_ip, ignore_status=True)
            if ping_out.exit_status != 0:
                msg = "LPAR2 ping to %s failed" % self.peer_ip
                self.log.error(msg)
                ping_failures.append(msg)
            else:
                self.log.info("LPAR2 ping OK")

        finally:
            # ── Phase 4: remove from both LPARs (always runs) ────────────────
            if lpar1_added:
                self.log.info("Removing vNIC from LPAR1 slot=%s",
                              self.lpar1_slot)
                self._lpar_vnic_remove(self.lpar1_id, self.lpar1_slot)
            if lpar2_added:
                self.log.info("Removing vNIC from LPAR2 slot=%s",
                              self.lpar2_slot)
                self._lpar_vnic_remove(self.lpar2_id, self.lpar2_slot)

        if ping_failures:
            self.fail("Ping failures (all vNICs removed):\n"
                      + "\n".join(ping_failures))
        self._check_dmesg_error()

    def test_multi_lpar_different_ports(self):
        '''
        Add a vNIC backed by adapter A port 0 to LPAR1 and adapter A port 1
        to LPAR2.  Both share the same physical card but use different ports.
        Ping from LPAR1 and LPAR2 to their peer, then remove from both.

        YAML: vnic_multi_lpar_different_ports.yaml
        Required keys: same as test_multi_lpar_same_adapter plus
          lpar1_sriov_port (port for LPAR1 vNIC) and
          lpar2_sriov_port (port for LPAR2 vNIC)

        :avocado: tags=net,vnic,dlpar,multi_lpar,privileged,power
        '''
        lpar1_port = str(self.params.get("lpar1_sriov_port", default="0"))
        lpar2_port = str(self.params.get("lpar2_sriov_port", default="1"))

        self.session_lpar2 = Session(self.lpar2_ip, user=self.lpar2_user,
                                     password=self.lpar2_pwd)
        self.session_lpar2.cleanup_master()
        if not wait.wait_for(self.session_lpar2.connect, timeout=30):
            self.cancel("Failed to connect to LPAR2 at %s" % self.lpar2_ip)

        ping_failures = []
        lpar1_added = False
        lpar2_added = False
        lpar1_device = None

        try:
            # ── Phase 1: add vNIC to LPAR1 (port 0) ──────────────────────────
            self.log.info("Adding vNIC to LPAR1 slot=%s mac=%s port=%s",
                          self.lpar1_slot, self.lpar1_mac, lpar1_port)
            self._lpar_vnic_add(self.lpar1_id, self.lpar1_slot,
                                self.lpar1_mac, lpar1_port)
            if not self._lpar_vnic_listed(self.lpar1, self.lpar1_slot):
                self.fail("lshwres does not list vNIC for LPAR1 after add")
            lpar1_added = True
            lpar1_device, lpar1_ni = self._configure_local_vnic(
                self.lpar1_mac, self.lpar1_ip, self.lpar1_netmask)

            # ── Phase 2: add vNIC to LPAR2 (port 1) ──────────────────────────
            self.log.info("Adding vNIC to LPAR2 slot=%s mac=%s port=%s",
                          self.lpar2_slot, self.lpar2_mac, lpar2_port)
            self._lpar_vnic_add(self.lpar2_id, self.lpar2_slot,
                                self.lpar2_mac, lpar2_port)
            if not self._lpar_vnic_listed(self.lpar2, self.lpar2_slot):
                self.fail("lshwres does not list vNIC for LPAR2 after add")
            lpar2_added = True
            lpar2_device = self._configure_remote_vnic(
                self.lpar2_mac, self.lpar2_ip_dev, self.lpar2_netmask)

            # ── Phase 3: ping checks ─────────────────────────────────────────
            self.log.info("Ping check: LPAR1 interface %s → peer %s",
                          lpar1_device, self.peer_ip)
            if lpar1_ni.ping_check(self.peer_ip, count=5) is not None:
                msg = "LPAR1 ping to %s failed" % self.peer_ip
                self.log.error(msg)
                ping_failures.append(msg)
            else:
                self.log.info("LPAR1 ping OK")

            self.log.info("Ping check: LPAR2 interface %s → peer %s",
                          lpar2_device, self.peer_ip)
            ping_out = self.session_lpar2.cmd(
                "ping -c 5 %s" % self.peer_ip, ignore_status=True)
            if ping_out.exit_status != 0:
                msg = "LPAR2 ping to %s failed" % self.peer_ip
                self.log.error(msg)
                ping_failures.append(msg)
            else:
                self.log.info("LPAR2 ping OK")

        finally:
            # ── Phase 4: remove from both LPARs (always runs) ────────────────
            if lpar1_added:
                self.log.info("Removing vNIC from LPAR1 slot=%s",
                              self.lpar1_slot)
                self._lpar_vnic_remove(self.lpar1_id, self.lpar1_slot)
            if lpar2_added:
                self.log.info("Removing vNIC from LPAR2 slot=%s",
                              self.lpar2_slot)
                self._lpar_vnic_remove(self.lpar2_id, self.lpar2_slot)

        if ping_failures:
            self.fail("Ping failures (all vNICs removed):\n"
                      + "\n".join(ping_failures))
        self._check_dmesg_error()

    def tearDown(self):
        if hasattr(self, 'session_lpar2') and self.session_lpar2:
            try:
                self.session_lpar2.quit()
            except Exception:
                pass
        if hasattr(self, 'session_hmc'):
            try:
                self.session_hmc.quit()
            except Exception:
                pass
