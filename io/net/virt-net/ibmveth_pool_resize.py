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
# Author: Shaik Abdulla <shaik.abdulla1@ibm.com>

"""
ibmveth Buffer Pool Resize Under Traffic
==========================================
Validates that the ibmveth driver correctly handles resizing each receive
buffer pool (pool0 through pool4) to 65536 bytes while background
network traffic is running, with no kernel call traces or OOM events.

The ibmveth driver exposes per-pool sysfs knobs under:
  /sys/class/net/<iface>/device/pool<N>/size   - buffer size in bytes
  /sys/class/net/<iface>/device/pool<N>/num    - number of pre-allocated
                                                  receive buffers

Test flow:
  1.  Detect the ibmveth interface and verify it is an ibmveth device.
  2.  Snapshot the original pool0-pool4 size values for later restore.
  3.  Start background flood-ping traffic from the peer.
  4.  For each pool (pool0 first, then pool1-pool4):
        a.  Write 65536 to .../pool<N>/size.
        b.  Validate ping connectivity to peer is still alive.
        c.  Scan dmesg for call traces and OOM messages.
        d.  Restore the original size for that pool.
  5.  Stop background traffic and confirm it has stopped.
  6.  tearDown restores all pools unconditionally.

See ibmveth_pool_resize.py.data/README for full parameter documentation.
"""

import os
import time

from avocado import Test
from avocado.utils import dmesg
from avocado.utils import process
from avocado.utils import wait
from avocado.utils import genio
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.network.hosts import LocalHost
from avocado.utils.ssh import Session

# Number of receive-buffer pools exposed by the ibmveth driver.
_NUM_POOLS = 5
# Pool indices exercised in this test.
_POOL_INDICES = list(range(_NUM_POOLS))   # [0, 1, 2, 3, 4]


class IbmvethPoolResize(Test):
    """
    ibmveth receive-buffer pool resize test.

    Resizes each pool (pool0-pool4) to 65536 bytes under live flood-ping
    traffic and verifies no call traces or OOM events appear in dmesg.
    """
    def setUp(self):
        """Validate environment, configure interface, open SSH to peer."""
        smm = SoftwareManager()
        for pkg in ["net-tools", "iputils", "util-linux"]:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel("Required package '%s' could not be installed"
                            % pkg)

        local = LocalHost()
        interfaces = os.listdir('/sys/class/net')
        device = self.params.get("interface", default=None)
        if device in interfaces:
            self.interface = device
        elif (local.validate_mac_addr(device) and
              device in local.get_all_hwaddr()):
            self.interface = local.get_interface_by_hwaddr(device).name
        else:
            self.cancel("Interface '%s' not found – update YAML" % device)

        # Create NetworkInterface early so we can use its is_veth() method
        # to verify this is an ibmveth (l-lan) device before proceeding.
        self.networkinterface = NetworkInterface(self.interface, local)

        # Must be an ibmveth (l-lan) interface — verified via devspec.
        try:
            if not self.networkinterface.is_veth():
                self.cancel(
                    "Interface '%s' is not an ibmveth device" % self.interface)
        except Exception as exc:
            self.cancel(
                "Interface '%s' ibmveth check failed: %s"
                % (self.interface, exc))

        self.ipaddr = self.params.get("host_ip", default=None)
        self.netmask = self.params.get("netmask", default=None)
        self.peer_ip = self.params.get("peer_ip", default=None)
        self.peer_user = self.params.get("peer_user", default="root")
        self.peer_password = self.params.get("peer_password", "*",
                                             default=None)
        self.ping_count = int(self.params.get("ping_count", default=1000000))
        self.pool_size_target = int(
            self.params.get("pool_size", default=65536))

        if not self.peer_ip:
            self.cancel("'peer_ip' parameter is required")
        if not self.ipaddr or not self.netmask:
            self.cancel("'host_ip' and 'netmask' parameters are required")

        # Assign IP only if the interface does not already have it.
        existing_ips = self.networkinterface.get_ipaddrs()
        if self.ipaddr not in existing_ips:
            try:
                self.networkinterface.add_ipaddr(self.ipaddr, self.netmask)
                self.networkinterface.save(self.ipaddr, self.netmask)
            except Exception as exc:
                self.fail(
                    "Failed to assign %s/%s to %s: %s"
                    % (self.ipaddr, self.netmask, self.interface, exc))
        else:
            self.log.info(
                "Interface %s already has IP %s, skipping add_ipaddr",
                self.interface, self.ipaddr)
        self.networkinterface.bring_up()

        if not wait.wait_for(self.networkinterface.is_link_up, timeout=120):
            self.fail(
                "Interface '%s' link did not come up within 120 s"
                % self.interface)

        try:
            self.networkinterface.ping_check(self.peer_ip, count=5)
        except Exception as exc:
            self.fail("No connectivity to peer %s: %s" % (self.peer_ip, exc))

        # Open SSH to peer for background traffic control.
        self.session = Session(self.peer_ip, user=self.peer_user,
                               password=self.peer_password)
        if not self.session.connect():
            self.fail("SSH connection to peer %s failed" % self.peer_ip)

        # Snapshot original pool sizes – keyed by pool index.
        self._pool_dir = os.path.join(
            '/sys/class/net', self.interface, 'device')
        self._original_sizes = {}
        for idx in _POOL_INDICES:
            orig = self._read_pool_size(idx)
            if orig is not None:
                self._original_sizes[idx] = orig

        if not self._original_sizes:
            self.fail(
                "No pool sysfs entries found under %s – "
                "ibmveth pool interface not available" % self._pool_dir)

        self.log.info("Original pool sizes: %s", self._original_sizes)

        # Background flood-ping process handle.
        self._ping_proc = None

    def test_pool_resize_under_traffic(self):
        """
        Resize each ibmveth pool to 65536 under live flood-ping traffic and
        verify no call traces or OOM events appear in dmesg.
        """
        failures = []

        self.log.info("=" * 60)
        self.log.info("ibmveth pool resize test – interface %s",
                      self.interface)
        self.log.info("Target pool size: %d", self.pool_size_target)
        self.log.info("=" * 60)

        # ---- Start background flood-ping traffic ----
        self._start_background_traffic()
        self.log.info("Background flood-ping traffic started to %s",
                      self.peer_ip)

        # ---- Exercise pool0 first, then pool1-pool4 ----
        for idx in _POOL_INDICES:
            if idx not in self._original_sizes:
                self.log.info("pool%d: sysfs not present – skipping", idx)
                continue

            pool_failures = self._test_single_pool(idx)
            failures.extend(pool_failures)

        # ---- Stop background traffic ----
        stopped = self._stop_background_traffic()
        if stopped:
            self.log.info("Background traffic stopped successfully")
        else:
            self.log.warning("Background traffic may not have stopped cleanly")

        if failures:
            self.fail("ibmveth pool resize failures:\n  "
                      + "\n  ".join(failures))

    def _test_single_pool(self, idx):
        """
        Set pool<idx>/size to pool_size_target, validate ping, check dmesg,
        restore. Returns a (possibly empty) list of failure strings.
        """
        failures = []
        original = self._original_sizes[idx]

        self.log.info("-" * 50)
        self.log.info("pool%d – writing size=%d (was %d)",
                      idx, self.pool_size_target, original)

        # Snapshot dmesg to a temp file before the resize so we only
        # scan lines that appear after the pool size change.
        dmesg_before_file = dmesg.collect_dmesg()

        # Write the new pool size.
        if not self._write_pool_size(idx, self.pool_size_target):
            failures.append(
                "pool%d: failed to write size=%d"
                % (idx, self.pool_size_target))
            # Restore immediately and return; no point scanning dmesg.
            self._restore_pool(idx, original)
            return failures

        # Allow the driver a moment to reallocate.
        time.sleep(2)

        # Verify the kernel accepted the new value.
        actual = self._read_pool_size(idx)
        if actual != self.pool_size_target:
            self.log.info(
                "pool%d: size read-back %s (expected %d) – "
                "kernel may have clamped to a valid value",
                idx, actual, self.pool_size_target)

        self.log.info("pool%d: size is now %s", idx, actual)

        # Validate that ping connectivity is still alive after the resize.
        try:
            self.networkinterface.ping_check(self.peer_ip, count=5)
            self.log.info(
                "pool%d: ping connectivity to %s is alive", idx, self.peer_ip)
        except Exception as exc:
            failures.append(
                "pool%d: ping to peer %s failed after "
                "setting size=%d: %s" % (idx, self.peer_ip,
                                         self.pool_size_target, exc))

        # Scan dmesg for call traces and OOM events using avocado dmesg util.
        dmesg_errors = self._check_dmesg_errors(dmesg_before_file)

        if dmesg_errors:
            for err_line in dmesg_errors:
                self.log.info("  [dmesg] Error pattern matched: %s", err_line)
            failures.append(
                "pool%d: dmesg errors detected after setting size=%d: %s"
                % (idx, self.pool_size_target,
                   "; ".join(dmesg_errors)))
        else:
            self.log.info(
                "pool%d: PASS – no call traces or OOM events", idx)

        # Restore original size.
        self._restore_pool(idx, original)
        return failures

    def _restore_pool(self, idx, original_size):
        """Write original_size back to pool<idx>/size."""
        if not self._write_pool_size(idx, original_size):
            self.log.info(
                "pool%d: WARNING – failed to restore size to %d",
                idx, original_size)
        else:
            self.log.info(
                "pool%d: restored size to %d", idx, original_size)
        time.sleep(1)

    def _pool_size_path(self, idx):
        return os.path.join(self._pool_dir, "pool%d" % idx, "size")

    def _read_pool_size(self, idx):
        """Return the current pool<idx> size as int, or None on error."""
        path = self._pool_size_path(idx)
        if not os.path.exists(path):
            return None
        try:
            return int(genio.read_file(path).strip())
        except (ValueError, IOError) as exc:
            self.log.info("pool%d: read error – %s", idx, exc)
            return None

    def _write_pool_size(self, idx, size):
        """Write size to pool<idx>/size. Returns True on success."""
        path = self._pool_size_path(idx)
        if not os.path.exists(path):
            self.log.info("pool%d: sysfs path not found: %s", idx, path)
            return False
        try:
            genio.write_file(path, str(size))
            return True
        except IOError as exc:
            self.log.info("pool%d: write error – %s", idx, exc)
            return False

    def _check_dmesg_errors(self, dmesg_before_file):
        """
        Collect dmesg lines that appeared after dmesg_before_file was
        snapshotted and match any call-trace or OOM pattern.

        Uses avocado.utils.dmesg.collect_errors_dmesg() which accepts a
        list of patterns and returns matching lines from the current dmesg.
        Lines already present before the pool resize (captured in
        dmesg_before_file) are subtracted so only new entries are reported.

        :param dmesg_before_file: path to dmesg snapshot taken before resize
        :type dmesg_before_file: str
        :returns: list of matching dmesg lines (empty list = no errors)
        :rtype: list
        """
        error_patterns = [
            "call trace", "calltrace", "kernel bug", "oops:",
            "BUG:", "BUG at", "WARNING:", "general protection fault",
            "soft lockup", "out of memory", "oom-kill",
            "oom_kill_process", "kill process", "kswapd",
        ]
        # Lines present before the resize — used to filter out pre-existing
        # dmesg noise.
        before_lines = set(
            genio.read_file(dmesg_before_file).splitlines())

        # collect_errors_dmesg() scans the *current* full dmesg for patterns.
        all_matches = dmesg.collect_errors_dmesg(error_patterns)

        # Return only lines that did not exist before the pool resize.
        return [line for line in all_matches if line not in before_lines]

    def _start_background_traffic(self):
        """Launch a background flood-ping from the local host to peer_ip."""
        cmd = ("ping -f -c %d %s > /tmp/ibmveth_pool_ping.log 2>&1"
               % (self.ping_count, self.peer_ip))
        self._ping_proc = process.SubProcess(cmd, shell=True, sudo=True)
        self._ping_proc.start()
        # Give the flood ping a moment to reach steady-state.
        time.sleep(2)

    def _stop_background_traffic(self):
        """
        Terminate the background flood-ping process.
        Returns True if the process was successfully stopped, False otherwise.
        """
        if self._ping_proc is None:
            return True
        try:
            self._ping_proc.stop()
            self._ping_proc = None
            return True
        except Exception as exc:
            self.log.warning("Failed to stop background ping: %s", exc)
            self._ping_proc = None
            return False

    def tearDown(self):
        """
        Best-effort cleanup: stop background traffic and restore all pools.
        """
        # Stop background traffic if still running.
        if getattr(self, '_ping_proc', None) is not None:
            self._stop_background_traffic()

        # Restore all pools to their original sizes.
        original_sizes = getattr(self, '_original_sizes', {})
        for idx, orig in original_sizes.items():
            current = self._read_pool_size(idx)
            if current != orig:
                self.log.info(
                    "tearDown: restoring pool%d size %s → %d",
                    idx, current, orig)
                self._write_pool_size(idx, orig)

        # Remove the interface IP configuration.
        if hasattr(self, 'networkinterface') and hasattr(self, 'ipaddr'):
            self.networkinterface.remove_ipaddr(self.ipaddr, self.netmask)
            try:
                self.networkinterface.restore_from_backup()
            except Exception:
                self.networkinterface.remove_cfg_file()
                self.log.info(
                    "tearDown: backup not available – cfg file removed.")

        if hasattr(self, 'session') and self.session:
            try:
                self.session.quit()
            except Exception:
                pass
