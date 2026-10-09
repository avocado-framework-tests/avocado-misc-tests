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
# Copyright: 2026 IBM
# Author: Pavaman Subramaniyam <pavsubra@linux.vnet.ibm.com>
# VLAN Testcase - works without a managed switch using Linux 802.1q
# sub-interfaces on both host and peer.

"""
VLAN tests using Linux kernel 802.1q sub-interfaces (no managed switch needed).

Scenario 1 (test_baseline_ping):
    Verify host and peer can ping each other on the physical test interface.
    No VLAN sub-interfaces involved. Ping should PASS.
    After passing, the connected route and ARP cache are flushed from the
    parent interface on both host and peer so that the VLAN sub-interfaces
    in Tests 2 and 3 can own those addresses exclusively. This is required
    for ibmvnic where the kernel otherwise continues routing via the
    parent's connected route instead of the tagged VLAN path.

Scenario 2 (test_vlan_same_id_ping):
    Create net1.<vlan_id> on both host and peer using the same host_ip/peer_ip.
    Ping between the VLAN sub-interfaces should PASS (same broadcast domain).
    After passing, VLAN sub-interfaces are torn down and their routes/ARP
    flushed so Test 3 starts clean.

Scenario 3 (test_vlan_isolation):
    Create net1.<vlan_id> on host and net1.2230 on peer (different VLAN IDs).
    Ping should FAIL confirming VLAN isolation.
    After the test, VLAN sub-interfaces are removed, the original IP is
    restored on the parent interfaces and a final ping verifies
    end-to-end connectivity.
"""

import os
import time

from avocado import Test
from avocado.utils import process
from avocado.utils.process import CmdError
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.network.hosts import LocalHost, RemoteHost
from avocado.utils.network.exceptions import NWException


class VlanTestWithoutSwitch(Test):
    """
    VLAN tests using Linux 802.1q sub-interfaces without a managed switch.

    :param interface: Host test network interface name or MAC address
    :param peer_interface: Peer test network interface name
    :param host_ip: IP address of the host test interface
    :param peer_ip: IP address of the peer test interface (same subnet)
    :param peer_public_ip: Peer SSH management IP (used to establish SSH)
    :param peer_user: SSH user on the peer (default: root)
    :param peer_password: SSH password for the peer
    :param netmask: Prefix length / netmask (default: 24)
    :param vlan_id: VLAN id used for same-VLAN and isolation tests
    """

    def setUp(self):
        """
        Validate host interface, resolve MAC to interface name if needed,
        read all test parameters and establish SSH session to peer.
        """
        local = LocalHost()
        interfaces = os.listdir('/sys/class/net')
        device = self.params.get("interface", default=None)
        if device in interfaces:
            self.host_intf = device
        elif local.validate_mac_addr(device):
            if device in local.get_all_hwaddr():
                self.host_intf = local.get_interface_by_hwaddr(
                    device).name
        else:
            self.cancel("Host interface '%s' not found" % device)

        self.peer_intf = self.params.get("peer_interface", default=None)
        self.host_ip = self.params.get("host_ip", default=None)
        self.peer_ip = self.params.get("peer_ip", default=None)
        self.peer_public_ip = self.params.get("peer_public_ip", default=None)
        self.peer_user = self.params.get("peer_user", default="root")
        self.peer_password = self.params.get("peer_password", '*',
                                             default=None)
        self.netmask = self.params.get("netmask", default="24")
        self.vlan_id = self.params.get("vlan_id", default="1484")

        if not self.peer_ip:
            self.cancel("peer_ip is required")
        if not self.peer_public_ip:
            self.cancel("peer_public_ip is required")

        # Track VLAN sub-interfaces created during the test for cleanup
        self._host_vlans_created = []
        self._peer_vlans_created = []

        # Set to True once the parent IP has been removed so tearDown
        # knows to restore it if the test fails before Test 3 does so.
        self._parent_ip_removed = False

        # LocalHost NetworkInterface for ping_check on host
        self.networkinterface = NetworkInterface(self.host_intf, local)

        # RemoteHost for peer NetworkInterface operations
        self.remotehost = RemoteHost(self.peer_public_ip, self.peer_user,
                                     password=self.peer_password)
        self.peer_networkinterface = NetworkInterface(self.peer_intf,
                                                      self.remotehost)

        self.log.info("setUp: host=%s(%s) peer_public=%s peer=%s(%s) vlan=%s",
                      self.host_intf, self.host_ip,
                      self.peer_public_ip, self.peer_intf, self.peer_ip,
                      self.vlan_id)

    def _flush_routes_and_arp_host(self, intf):
        """Flush routes for *intf* and flush the entire ARP table on the host.
        'ip neigh flush all' is used instead of 'dev <intf>' because ibmvnic
        can cache neighbour entries against the parent interface even after the
        IP is moved to a VLAN sub-interface; a full flush ensures no stale
        entry remains regardless of which interface it was learned on.
        """
        self.log.info("HOST: flushing routes for %s and ARP table (all)", intf)
        process.system("ip route flush dev %s" % intf,
                       shell=True, sudo=True, ignore_status=True)
        process.system("ip neigh flush all",
                       shell=True, sudo=True, ignore_status=True)

    def _flush_routes_and_arp_peer(self, intf):
        """Flush routes for *intf* and flush the entire ARP table on the peer.
        Same reasoning as _flush_routes_and_arp_host — full flush required for
        ibmvnic to clear entries cached against the parent interface.
        """
        self.log.info("PEER: flushing routes for %s and ARP table (all)", intf)
        self.remotehost.remote_session.cmd(
            "ip route flush dev %s 2>/dev/null; true" % intf)
        self.remotehost.remote_session.cmd(
            "ip neigh flush all 2>/dev/null; true")

    def _remove_parent_ip(self):
        """
        Remove host_ip/peer_ip from the parent interfaces and flush their
        routes/ARP on both host and peer.  Marks _parent_ip_removed = True.
        Safe to call multiple times (no-op if already removed).
        """
        if self._parent_ip_removed:
            return
        self.log.info("Removing parent IPs and flushing routes/ARP "
                      "before VLAN sub-interface assignment")
        process.system(
            "ip addr del %s/%s dev %s 2>/dev/null" % (
                self.host_ip, self.netmask, self.host_intf),
            shell=True, sudo=True, ignore_status=True)
        self._flush_routes_and_arp_host(self.host_intf)
        self.remotehost.remote_session.cmd(
            "ip addr del %s/%s dev %s 2>/dev/null; true" % (
                self.peer_ip, self.netmask, self.peer_intf))
        self._flush_routes_and_arp_peer(self.peer_intf)
        self._parent_ip_removed = True

    def _restore_parent_ip(self):
        """
        Re-add host_ip/peer_ip to the parent interfaces and bring them up.
        Clears _parent_ip_removed.  Safe to call multiple times.
        """
        if not self._parent_ip_removed:
            return
        self.log.info("Restoring original IPs on parent interfaces")
        # Idempotent: delete first in case a partial state left the address.
        process.system(
            "ip addr del %s/%s dev %s 2>/dev/null" % (
                self.host_ip, self.netmask, self.host_intf),
            shell=True, sudo=True, ignore_status=True)
        process.system(
            "ip addr add %s/%s dev %s" % (
                self.host_ip, self.netmask, self.host_intf),
            shell=True, sudo=True, ignore_status=True)
        process.system("ip link set %s up" % self.host_intf,
                       shell=True, sudo=True, ignore_status=True)
        self.remotehost.remote_session.cmd(
            "ip addr del %s/%s dev %s 2>/dev/null; true" % (
                self.peer_ip, self.netmask, self.peer_intf))
        self.remotehost.remote_session.cmd(
            "ip addr add %s/%s dev %s" % (
                self.peer_ip, self.netmask, self.peer_intf))
        self.remotehost.remote_session.cmd(
            "ip link set %s up" % self.peer_intf)
        self._parent_ip_removed = False

    # -------------------------------------------------------------------------
    # Helpers — host commands
    # -------------------------------------------------------------------------
    def _run_host(self, cmd):
        """Run a command on host; fail test on non-zero exit."""
        self.log.info("[HOST] %s", cmd)
        try:
            process.run(cmd, shell=True, sudo=True)
        except CmdError as details:
            self.fail("Host command failed: %s  →  %s" % (cmd, details))

    # -------------------------------------------------------------------------
    # Helpers — peer commands via RemoteHost session
    # -------------------------------------------------------------------------
    def _run_peer(self, cmd, ignore_status=False):
        """Run a command on peer via SSH; fail test on non-zero exit."""
        self.log.info("[PEER] %s", cmd)
        result = self.remotehost.remote_session.cmd(cmd)
        if not ignore_status and result.exit_status != 0:
            self.fail("Peer command failed: %s\n  stdout: %s\n  stderr: %s"
                      % (cmd, result.stdout_text, result.stderr_text))
        return result.stdout_text.strip()

    # -------------------------------------------------------------------------
    # VLAN sub-interface helpers
    # -------------------------------------------------------------------------
    def _delete_vlan_host_safe(self, vlan_id):
        """Delete a host VLAN sub-interface, silently ignore errors."""
        vintf = "%s.%s" % (self.host_intf, vlan_id)
        process.system("ip link delete %s 2>/dev/null" % vintf,
                       shell=True, sudo=True, ignore_status=True)

    def _delete_vlan_peer_safe(self, vlan_id):
        """Delete a peer VLAN sub-interface via SSH, silently ignore errors."""
        vintf = "%s.%s" % (self.peer_intf, vlan_id)
        self.remotehost.remote_session.cmd(
            "ip link delete %s 2>/dev/null; true" % vintf)

    def _create_vlan_intf_host(self, vlan_id, ip, prefix):
        """Create a VLAN sub-interface on the host and bring it up."""
        vintf = "%s.%s" % (self.host_intf, vlan_id)
        self._delete_vlan_host_safe(vlan_id)
        try:
            result = process.run(
                "ip link show %s 2>/dev/null" % vintf, shell=True, sudo=True,
                ignore_status=True)
            if result.exit_status == 0 and vintf in result.stdout_text:
                self.fail(
                    "HOST: interface %s still exists after deletion attempt"
                    % vintf)
        except CmdError as details:
            self.fail(
                "HOST: could not verify deletion of %s: %s" % (vintf, details))
        time.sleep(0.5)
        self._run_host("ip link add link %s name %s type vlan id %s"
                       % (self.host_intf, vintf, vlan_id))
        self._run_host("ip addr add %s/%s dev %s" % (ip, prefix, vintf))
        self._run_host("ip link set %s up" % vintf)
        try:
            result = process.run(
                "ip link show %s" % vintf, shell=True, sudo=True)
            if "state UP" not in result.stdout_text:
                self.fail(
                    "HOST: interface %s did not come UP after 'ip link set up'"
                    " (state: %s)" % (vintf, result.stdout_text.strip()))
        except CmdError as details:
            self.fail(
                "HOST: could not verify state of %s: %s" % (vintf, details))
        self._host_vlans_created.append(vlan_id)
        self.log.info("HOST: created %s  ip=%s/%s", vintf, ip, prefix)

    def _create_vlan_intf_peer(self, vlan_id, ip, prefix):
        """Create a VLAN sub-interface on the peer and bring it up."""
        vintf = "%s.%s" % (self.peer_intf, vlan_id)
        self._delete_vlan_peer_safe(vlan_id)
        result = self.remotehost.remote_session.cmd(
            "ip link show %s 2>/dev/null" % vintf)
        if result.exit_status == 0 and vintf in result.stdout_text:
            self.fail(
                "PEER: interface %s still exists after deletion attempt"
                % vintf)
        time.sleep(0.5)
        self._run_peer("ip link add link %s name %s type vlan id %s"
                       % (self.peer_intf, vintf, vlan_id))
        self._run_peer("ip addr add %s/%s dev %s" % (ip, prefix, vintf))
        self._run_peer("ip link set %s up" % vintf)
        state_out = self._run_peer("ip link show %s" % vintf)
        if "state UP" not in state_out:
            self.fail(
                "PEER: interface %s did not come UP after 'ip link set up'"
                " (state: %s)" % (vintf, state_out))
        self._peer_vlans_created.append(vlan_id)
        self.log.info("PEER: created %s  ip=%s/%s", vintf, ip, prefix)

    def _check_vlan_arp_reachability(self, src_vintf, dst_ip):
        """
        Send a single ARP request from *src_vintf* to *dst_ip* using arping.
        If no ARP reply is received, cancel the test with a clear message
        pointing at the VIOS VLAN trunk configuration.

        On ibmvnic the hypervisor silently drops VLAN-tagged frames for any
        VLAN ID that is not listed as an allowed trunk VLAN on the virtual
        adapter in the VIOS/HMC configuration.  When this happens ping
        reports "Destination Host Unreachable" (local ICMP, not from peer)
        because the ARP request never crosses the virtual fabric.

        Calling this after both VLAN sub-interfaces are UP but before running
        the actual ping test surfaces the real cause immediately.
        """
        self.log.info("HOST: ARP reachability probe %s → %s via %s",
                      src_vintf, dst_ip, src_vintf)
        result = process.run(
            "arping -c 2 -w 4 -I %s %s" % (src_vintf, dst_ip),
            shell=True, sudo=True, ignore_status=True)
        if result.exit_status != 0:
            self.cancel(
                "ARP probe from %s to %s got no reply — VLAN-tagged frames "
                "are not reaching the peer. "
                "For ibmvnic/VIOS: ensure VLAN ID %s is added as an allowed "
                "trunk VLAN on the virtual Ethernet adapter in the VIOS/HMC "
                "configuration (chdev -dev <SEA> -attr taggedvlan=<id_list> "
                "or via HMC vNIC settings) before running this test."
                % (src_vintf, dst_ip, self.vlan_id))
        self.log.info("HOST: ARP probe PASSED — peer MAC resolved via %s",
                      src_vintf)

    # -------------------------------------------------------------------------
    # Test 1 — Baseline: ping on physical NIC (no VLAN sub-interface)
    # -------------------------------------------------------------------------
    def test_baseline_ping(self):
        """
        Scenario 1: Verify host and peer can reach each other on the physical
        test interface (no VLAN sub-interfaces). Ping should PASS.

        Post-test cleanup: the parent IP is removed and routes/ARP flushed
        on both host and peer so that Tests 2 and 3 can assign the same IP
        to the VLAN sub-interface without the kernel routing via the
        parent's connected route (critical fix for ibmvnic).
        """
        self.log.info("=" * 60)
        self.log.info("Test 1: Baseline ping on physical interface")
        self.log.info("=" * 60)

        if self.networkinterface.ping_check(self.peer_ip, count=5) is not None:
            self.fail("Baseline ping host→peer (%s → %s) FAILED"
                      % (self.host_intf, self.peer_ip))
        self.log.info("Baseline ping host→peer PASSED")

        cmd = "ping -I %s %s -c 5" % (self.peer_intf, self.host_ip)
        result = self.remotehost.remote_session.cmd(cmd)
        if result.exit_status != 0:
            self.fail("Baseline ping peer→host (%s → %s) FAILED"
                      % (self.peer_intf, self.host_ip))
        self.log.info("Baseline ping peer→host PASSED")

        # Remove the parent IP and flush routes/ARP so the VLAN sub-interfaces
        # in Tests 2 and 3 own the address cleanly (required for ibmvnic).
        self._remove_parent_ip()
        self.log.info("Test 1 post-cleanup: parent IPs removed, "
                      "routes/ARP flushed")

    # -------------------------------------------------------------------------
    # Test 2 — Same VLAN ID: ping must PASS
    # -------------------------------------------------------------------------
    def test_vlan_same_id_ping(self):
        """
        Scenario 2: Create net1.<vlan_id> on both host and peer using the same
        host_ip/peer_ip. Ping between the sub-interfaces should PASS because
        both endpoints are in the same VLAN broadcast domain.

        Pre-test: ensure parent IP is removed (safety net when this test runs
        without test_baseline_ping having run first).
        Post-test: remove VLAN interfaces and flush their routes/ARP.
        """
        self.log.info("=" * 60)
        self.log.info("Test 2: Same VLAN id (%s) ping", self.vlan_id)
        self.log.info("=" * 60)

        # Safety net: remove parent IP if test_baseline_ping did not run first.
        self._remove_parent_ip()

        self._create_vlan_intf_host(self.vlan_id, self.host_ip,
                                    self.netmask)
        self._create_vlan_intf_peer(self.vlan_id, self.peer_ip,
                                    self.netmask)
        time.sleep(2)

        host_vintf = "%s.%s" % (self.host_intf, self.vlan_id)
        peer_vintf = "%s.%s" % (self.peer_intf, self.vlan_id)

        # ARP probe: cancel early with a clear VIOS message if tagged frames
        # are being dropped by the hypervisor before trying ping.
        self._check_vlan_arp_reachability(host_vintf, self.peer_ip)

        vlan_networkinterface = NetworkInterface(host_vintf,
                                                 LocalHost())
        if vlan_networkinterface.ping_check(self.peer_ip,
                                            count=5) is not None:
            self.fail("Same-VLAN ping host→peer (%s → %s) FAILED"
                      % (host_vintf, self.peer_ip))
        self.log.info("Same-VLAN ping host→peer PASSED")

        cmd = "ping -I %s %s -c 5" % (peer_vintf, self.host_ip)
        result = self.remotehost.remote_session.cmd(cmd)
        if result.exit_status != 0:
            self.fail("Same-VLAN ping peer→host (%s → %s) FAILED"
                      % (peer_vintf, self.host_ip))
        self.log.info("Same-VLAN ping peer→host PASSED")

        # Remove VLAN interfaces and flush their routes/ARP so Test 3 starts
        # from a clean state with no stale routes or ARP entries.
        self.log.info("Test 2 post-cleanup: removing VLAN interfaces "
                      "and flushing routes/ARP")
        host_vintf = "%s.%s" % (self.host_intf, self.vlan_id)
        peer_vintf = "%s.%s" % (self.peer_intf, self.vlan_id)
        self._flush_routes_and_arp_host(host_vintf)
        self._delete_vlan_host_safe(self.vlan_id)
        self._flush_routes_and_arp_peer(peer_vintf)
        self._delete_vlan_peer_safe(self.vlan_id)
        self._host_vlans_created = [
            v for v in self._host_vlans_created if v != self.vlan_id]
        self._peer_vlans_created = [
            v for v in self._peer_vlans_created if v != self.vlan_id]
        self.log.info("Test 2 post-cleanup complete")

    # -------------------------------------------------------------------------
    # Test 3 — Different VLAN IDs: ping must FAIL (isolation test)
    # -------------------------------------------------------------------------
    def test_vlan_isolation(self):
        """
        Scenario 3: Create net1.<vlan_id> on host and net1.2230 on peer
        (different VLAN IDs). Ping should FAIL confirming that packets tagged
        with different VLAN IDs remain isolated broadcast domains.

        Pre-test: ensure parent IP is removed (safety net).
        Post-test: remove VLAN interfaces, flush routes/ARP, restore original
        IP on the parent interface and verify end-to-end ping to the peer.
        """
        self.log.info("=" * 60)
        self.log.info("Test 3: VLAN isolation (host vlan=%s, peer vlan=2230)",
                      self.vlan_id)
        self.log.info("=" * 60)

        alt_vlan = "2230"

        # Safety net: remove parent IP if previous tests did not do so.
        self._remove_parent_ip()

        self._create_vlan_intf_host(self.vlan_id, self.host_ip,
                                    self.netmask)
        self._create_vlan_intf_peer(alt_vlan, self.peer_ip, self.netmask)
        time.sleep(2)

        host_vintf = "%s.%s" % (self.host_intf, self.vlan_id)
        peer_vintf = "%s.%s" % (self.peer_intf, alt_vlan)

        vlan_networkinterface = NetworkInterface(host_vintf, LocalHost())
        try:
            vlan_networkinterface.ping_check(self.peer_ip, count=5)
            self.fail("Cross-VLAN ping host(%s)→peer(%s) should FAIL \
                      but PASSED" % (host_vintf, self.peer_ip))
        except NWException:
            self.log.info("Cross-VLAN ping host→peer correctly FAILED "
                          "(isolation OK)")

        cmd = "ping -I %s %s -c 5" % (peer_vintf, self.host_ip)
        result = self.remotehost.remote_session.cmd(cmd)
        if result.exit_status == 0:
            self.fail("Cross-VLAN ping peer(%s)→host(%s) should FAIL \
                      but PASSED"
                      % (peer_vintf, self.host_ip))
        self.log.info("Cross-VLAN ping peer→host correctly FAILED "
                      "(isolation OK)")

        # --- Post-test cleanup: remove VLAN interfaces and flush routes/ARP --
        self.log.info("Test 3 post-cleanup: removing VLAN interfaces "
                      "and flushing routes/ARP")
        self._flush_routes_and_arp_host(host_vintf)
        self._delete_vlan_host_safe(self.vlan_id)
        self._flush_routes_and_arp_peer(peer_vintf)
        self._delete_vlan_peer_safe(alt_vlan)
        self._host_vlans_created = [
            v for v in self._host_vlans_created if v != self.vlan_id]
        self._peer_vlans_created = [
            v for v in self._peer_vlans_created if v != alt_vlan]

        # --- Restore original parent IPs and verify connectivity -------------
        self._restore_parent_ip()
        time.sleep(2)
        self.log.info("Test 3: verifying parent interface ping after restore")
        if self.networkinterface.ping_check(self.peer_ip, count=5) is not None:
            self.fail(
                "Post-restore ping host→peer (%s → %s) FAILED"
                % (self.host_intf, self.peer_ip))
        self.log.info("Post-restore ping PASSED — parent interface OK")

    # -------------------------------------------------------------------------
    # tearDown — remove all VLAN sub-interfaces created during this test
    # -------------------------------------------------------------------------
    def tearDown(self):
        """
        Remove VLAN sub-interfaces created on host and peer.
        Forcibly clean up all known VLAN IDs even if tracking missed any.
        If the parent IP was removed during testing but not yet restored
        (e.g. test failed mid-way), restore it here.
        Ensure the physical interface remains up after cleanup.
        """
        self.log.info("tearDown: cleaning up VLAN sub-interfaces")

        for vid in list(self._host_vlans_created):
            self._delete_vlan_host_safe(vid)
        for vid in [self.vlan_id, "2230"]:
            self._delete_vlan_host_safe(vid)
        # Validate every host VLAN sub-interface that was attempted for
        # deletion is actually gone; warn (do not fail) so tearDown
        # always completes.
        all_host_vids = set(
            list(self._host_vlans_created) + [self.vlan_id, "2230"])
        for vid in all_host_vids:
            vintf = "%s.%s" % (self.host_intf, vid)
            try:
                result = process.run(
                    "ip link show %s 2>/dev/null" % vintf,
                    shell=True, sudo=True, ignore_status=True)
                if result.exit_status == 0 and vintf in result.stdout_text:
                    self.log.warning(
                        "HOST: interface %s still exists after tearDown "
                        "deletion", vintf)
            except CmdError as details:
                self.log.warning(
                    "HOST: could not verify deletion of %s in tearDown: %s",
                    vintf, details)

        if hasattr(self, 'remotehost') and self.remotehost:
            for vid in list(self._peer_vlans_created):
                self._delete_vlan_peer_safe(vid)
            for vid in [self.vlan_id, "2230"]:
                self._delete_vlan_peer_safe(vid)

        # If a test failed before Test 3 could restore the parent IP,
        # restore it now so the interface is left in a usable state.
        if hasattr(self, '_parent_ip_removed') and self._parent_ip_removed:
            self.log.info("tearDown: parent IP was not restored — "
                          "restoring now")
            self._restore_parent_ip()

        if hasattr(self, 'remotehost') and self.remotehost:
            try:
                self.remotehost.remote_session.quit()
            except Exception:
                pass

        process.system("ip link set %s up" % self.host_intf,
                       shell=True, sudo=True, ignore_status=True)
        # Validate the physical host interface came back up after tearDown.
        try:
            result = process.run(
                "ip link show %s" % self.host_intf, shell=True, sudo=True)
            if "state UP" not in result.stdout_text:
                self.log.warning(
                    "HOST: physical interface %s did not come UP in tearDown"
                    " (state: %s)", self.host_intf,
                    result.stdout_text.strip())
        except CmdError as details:
            self.log.warning(
                "HOST: could not verify state of %s in tearDown: %s",
                self.host_intf, details)
        self.log.info("tearDown complete")
