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

Scenario 2 (test_vlan_same_id_ping):
    Create net1.<vlan_id> on both host and peer using dedicated VLAN IPs.
    Ping between the VLAN sub-interfaces should PASS (same broadcast domain).

Scenario 3 (test_vlan_isolation):
    Create net1.<vlan_id> on host and net1.2230 on peer (different VLAN IDs).
    Ping should FAIL confirming VLAN isolation.
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
    :param host_vlan_ip: Host IP assigned to the VLAN sub-interface
    :param peer_vlan_ip: Peer IP assigned to the VLAN sub-interface
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

        if self.host_intf.startswith('ib'):
            self.cancel("VLAN is not supported on IB interface")

        self.peer_intf = self.params.get("peer_interface", default=None)
        self.host_ip = self.params.get("host_ip", default=None)
        self.peer_ip = self.params.get("peer_ip", default=None)
        self.host_vlan_ip = self.params.get("host_vlan_ip", default=None)
        self.peer_vlan_ip = self.params.get("peer_vlan_ip", default=None)
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
        time.sleep(0.5)
        self._run_host("ip link add link %s name %s type vlan id %s"
                       % (self.host_intf, vintf, vlan_id))
        self._run_host("ip addr add %s/%s dev %s" % (ip, prefix, vintf))
        self._run_host("ip link set %s up" % vintf)
        self._host_vlans_created.append(vlan_id)
        self.log.info("HOST: created %s  ip=%s/%s", vintf, ip, prefix)

    def _create_vlan_intf_peer(self, vlan_id, ip, prefix):
        """Create a VLAN sub-interface on the peer and bring it up."""
        vintf = "%s.%s" % (self.peer_intf, vlan_id)
        self._delete_vlan_peer_safe(vlan_id)
        time.sleep(0.5)
        self._run_peer("ip link add link %s name %s type vlan id %s"
                       % (self.peer_intf, vintf, vlan_id))
        self._run_peer("ip addr add %s/%s dev %s" % (ip, prefix, vintf))
        self._run_peer("ip link set %s up" % vintf)
        self._peer_vlans_created.append(vlan_id)
        self.log.info("PEER: created %s  ip=%s/%s", vintf, ip, prefix)

    # -------------------------------------------------------------------------
    # Test 1 — Baseline: ping on physical NIC (no VLAN sub-interface)
    # -------------------------------------------------------------------------
    def test_baseline_ping(self):
        """
        Scenario 1: Verify host and peer can reach each other on the physical
        test interface (no VLAN sub-interfaces). Ping should PASS.
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

    # -------------------------------------------------------------------------
    # Test 2 — Same VLAN ID: ping must PASS
    # -------------------------------------------------------------------------
    def test_vlan_same_id_ping(self):
        """
        Scenario 2: Create net1.<vlan_id> on both host and peer using dedicated
        VLAN IPs. Ping between the sub-interfaces should PASS because both
        endpoints are in the same VLAN broadcast domain.
        """
        self.log.info("=" * 60)
        self.log.info("Test 2: Same VLAN id (%s) ping", self.vlan_id)
        self.log.info("=" * 60)

        self._create_vlan_intf_host(self.vlan_id, self.host_vlan_ip,
                                    self.netmask)
        self._create_vlan_intf_peer(self.vlan_id, self.peer_vlan_ip,
                                    self.netmask)
        time.sleep(2)

        host_vintf = "%s.%s" % (self.host_intf, self.vlan_id)
        peer_vintf = "%s.%s" % (self.peer_intf, self.vlan_id)

        vlan_networkinterface = NetworkInterface(host_vintf,
                                                 LocalHost())
        if vlan_networkinterface.ping_check(self.peer_vlan_ip,
                                            count=5) is not None:
            self.fail("Same-VLAN ping host→peer (%s → %s) FAILED"
                      % (host_vintf, self.peer_vlan_ip))
        self.log.info("Same-VLAN ping host→peer PASSED")

        cmd = "ping -I %s %s -c 5" % (peer_vintf, self.host_vlan_ip)
        result = self.remotehost.remote_session.cmd(cmd)
        if result.exit_status != 0:
            self.fail("Same-VLAN ping peer→host (%s → %s) FAILED"
                      % (peer_vintf, self.host_vlan_ip))
        self.log.info("Same-VLAN ping peer→host PASSED")

    # -------------------------------------------------------------------------
    # Test 3 — Different VLAN IDs: ping must FAIL (isolation test)
    # -------------------------------------------------------------------------
    def test_vlan_isolation(self):
        """
        Scenario 3: Create net1.<vlan_id> on host and net1.2230 on peer
        (different VLAN IDs). Ping should FAIL confirming that packets tagged
        with different VLAN IDs remain isolated broadcast domains.
        """
        self.log.info("=" * 60)
        self.log.info("Test 3: VLAN isolation (host vlan=%s, peer vlan=2230)",
                      self.vlan_id)
        self.log.info("=" * 60)

        alt_vlan = "2230"

        self._create_vlan_intf_host(self.vlan_id, self.host_vlan_ip,
                                    self.netmask)
        self._create_vlan_intf_peer(alt_vlan, self.peer_vlan_ip, self.netmask)
        time.sleep(2)

        host_vintf = "%s.%s" % (self.host_intf, self.vlan_id)
        peer_vintf = "%s.%s" % (self.peer_intf, alt_vlan)

        vlan_networkinterface = NetworkInterface(host_vintf, LocalHost())
        try:
            vlan_networkinterface.ping_check(self.peer_vlan_ip, count=5)
            self.fail("Cross-VLAN ping host(%s)→peer(%s) should FAIL \
                      but PASSED" % (host_vintf, self.peer_vlan_ip))
        except NWException:
            self.log.info("Cross-VLAN ping host→peer correctly FAILED "
                          "(isolation OK)")

        cmd = "ping -I %s %s -c 5" % (peer_vintf, self.host_vlan_ip)
        result = self.remotehost.remote_session.cmd(cmd)
        if result.exit_status == 0:
            self.fail("Cross-VLAN ping peer(%s)→host(%s) should FAIL \
                      but PASSED"
                      % (peer_vintf, self.host_vlan_ip))
        self.log.info("Cross-VLAN ping peer→host correctly FAILED "
                      "(isolation OK)")

    # -------------------------------------------------------------------------
    # tearDown — remove all VLAN sub-interfaces created during this test
    # -------------------------------------------------------------------------
    def tearDown(self):
        """
        Remove VLAN sub-interfaces created on host and peer.
        Forcibly clean up all known VLAN IDs even if tracking missed any.
        Ensure the physical interface remains up after cleanup.
        """
        self.log.info("tearDown: cleaning up VLAN sub-interfaces")

        for vid in list(self._host_vlans_created):
            self._delete_vlan_host_safe(vid)
        for vid in [self.vlan_id, "2230"]:
            self._delete_vlan_host_safe(vid)

        if hasattr(self, 'remotehost') and self.remotehost:
            for vid in list(self._peer_vlans_created):
                self._delete_vlan_peer_safe(vid)
            for vid in [self.vlan_id, "2230"]:
                self._delete_vlan_peer_safe(vid)
            try:
                self.remotehost.remote_session.quit()
            except Exception:
                pass

        process.system("ip link set %s up" % self.host_intf,
                       shell=True, sudo=True, ignore_status=True)
        self.log.info("tearDown complete")
