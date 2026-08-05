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
  /sys/class/net/<iface>/device/pool<N>/size   – buffer size in bytes
  /sys/class/net/<iface>/device/pool<N>/num    – number of pre-allocated
                                                  receive buffers

Test flow:
  1.  Detect the ibmveth interface and verify it is an ibmveth device.
  2.  Snapshot the original pool0-pool4 size values for later restore.
  3.  Start background flood-ping traffic from the peer.
  4.  For each pool (pool0 first, then pool1-pool4):
        a.  Write 65536 to .../pool<N>/size.
        b.  Scan dmesg for call traces and OOM messages.
        c.  Restore the original size for that pool.
  5.  Stop background traffic.
  6.  tearDown restores all pools unconditionally.

Parameters (YAML)
-----------------
  interface      - ibmveth interface name or MAC address
  host_ip        - local IP to configure on the interface
  netmask        - netmask for the host IP
  peer_ip        - peer machine IP (used for ping traffic)
  peer_user      - SSH user on the peer (default: root)
  peer_password  - SSH password on the peer
  ping_count     - flood-ping packet count (default: 1000000)
  pool_size      - buffer size in bytes to write to each pool (default: 65536)
"""

import os
import time

from avocado import Test
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

    # ------------------------------------------------------------------ #
    #  Life-cycle                                                          #
    # ------------------------------------------------------------------ #

    def setUp(self):
        """Validate environment, configure interface, open SSH to peer."""
        smm = SoftwareManager()
        for pkg in ["net-tools", "iputils"]:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel("Required package '%s' could not be installed"
                            % pkg)

        local = LocalHost()
        interfaces = os.listdir('/sys/class/net')
        device = self.params.get("interface")
        if device in interfaces:
            self.interface = device
        elif (local.validate_mac_addr(device) and
              device in local.get_all_hwaddr()):
            self.interface = local.get_interface_by_hwaddr(device).name
        else:
            self.cancel("Interface '%s' not found – update YAML" % device)

        # Must be an ibmveth interface.
        if not self._is_ibmveth(self.interface):
            self.cancel(
                "Interface '%s' is not an ibmveth device" % self.interface)

        self.ipaddr = self.params.get("host_ip", default="")
        self.netmask = self.params.get("netmask", default="")
        self.peer_ip = self.params.get("peer_ip", default="")
        self.peer_user = self.params.get("peer_user", default="root")
        self.peer_password = self.params.get("peer_password", "*",
                                             default=None)
        self.ping_count = int(self.params.get("ping_count", default=1000000))
        self.pool_size_target = int(
            self.params.get("pool_size", default=65536))

        if not self.peer_ip:
            self.cancel("'peer_ip' parameter is required")

        # Configure the interface.
        self.networkinterface = NetworkInterface(self.interface, local)
        try:
            self.networkinterface.add_ipaddr(self.ipaddr, self.netmask)
            self.networkinterface.save(self.ipaddr, self.netmask)
        except Exception:
            self.networkinterface.save(self.ipaddr, self.netmask)
        self.networkinterface.bring_up()

        if not wait.wait_for(self.networkinterface.is_link_up, timeout=120):
            self.cancel(
                "Interface '%s' link did not come up within 120 s"
                % self.interface)

        if self.networkinterface.ping_check(self.peer_ip, count=5) is not None:
            self.cancel("No connectivity to peer %s" % self.peer_ip)

        # Open SSH to peer for background traffic control.
        self.session = Session(self.peer_ip, user=self.peer_user,
                               password=self.peer_password)
        if not self.session.connect():
            self.cancel("SSH connection to peer %s failed" % self.peer_ip)

        # Snapshot original pool sizes – keyed by pool index.
        self._pool_dir = os.path.join(
            '/sys/class/net', self.interface, 'device')
        self._original_sizes = {}
        for idx in _POOL_INDICES:
            orig = self._read_pool_size(idx)
            if orig is not None:
                self._original_sizes[idx] = orig
                self.log.info("pool%d: original size = %d", idx, orig)

        if not self._original_sizes:
            self.cancel(
                "No pool sysfs entries found under %s – "
                "ibmveth pool interface not available" % self._pool_dir)

        # Background flood-ping process handle.
        self._ping_proc = None

    # ------------------------------------------------------------------ #
    #  Main test                                                           #
    # ------------------------------------------------------------------ #

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
        self._stop_background_traffic()
        self.log.info("Background traffic stopped")

        if failures:
            self.fail("ibmveth pool resize failures:\n  "
                      + "\n  ".join(failures))

    # ------------------------------------------------------------------ #
    #  Per-pool helpers                                                    #
    # ------------------------------------------------------------------ #

    def _test_single_pool(self, idx):
        """
        Set pool<idx>/size to pool_size_target, check dmesg, restore.
        Returns a (possibly empty) list of failure strings.
        """
        failures = []
        original = self._original_sizes[idx]

        self.log.info("-" * 50)
        self.log.info("pool%d – writing size=%d (was %d)",
                      idx, self.pool_size_target, original)

        # Snapshot dmesg length before the change so we only scan new lines.
        dmesg_before = self._dmesg_line_count()

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

        # Scan dmesg for call traces and OOM events.
        new_dmesg = self._dmesg_new_lines(dmesg_before)
        calltrace_found, oom_found = self._analyse_dmesg(new_dmesg)

        if calltrace_found:
            failures.append(
                "pool%d: call trace detected in dmesg after "
                "setting size=%d" % (idx, self.pool_size_target))
        if oom_found:
            failures.append(
                "pool%d: OOM event detected in dmesg after "
                "setting size=%d" % (idx, self.pool_size_target))

        if not calltrace_found and not oom_found:
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

    # ------------------------------------------------------------------ #
    #  ibmveth pool sysfs I/O                                              #
    # ------------------------------------------------------------------ #

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

    # ------------------------------------------------------------------ #
    #  ibmveth device detection                                            #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _is_ibmveth(interface):
        """Return True if <interface> is driven by the ibmveth driver."""
        driver_link = os.path.join(
            '/sys/class/net', interface, 'device', 'driver')
        if not os.path.exists(driver_link):
            return False
        try:
            driver_path = os.readlink(driver_link)
            return 'ibmveth' in os.path.basename(driver_path)
        except OSError:
            return False

    # ------------------------------------------------------------------ #
    #  dmesg analysis                                                      #
    # ------------------------------------------------------------------ #

    def _dmesg_line_count(self):
        """Return the current number of lines in dmesg."""
        try:
            out = process.run("dmesg", sudo=True, ignore_status=True,
                              shell=True).stdout_text
            return len(out.splitlines())
        except Exception:
            return 0

    def _dmesg_new_lines(self, line_count_before):
        """Return dmesg lines added since line_count_before."""
        try:
            out = process.run("dmesg", sudo=True, ignore_status=True,
                              shell=True).stdout_text
            lines = out.splitlines()
            return lines[line_count_before:]
        except Exception:
            return []

    def _analyse_dmesg(self, lines):
        """
        Scan lines for call-trace and OOM patterns.
        Returns (calltrace_found, oom_found) as booleans.
        """
        calltrace_found = False
        oom_found = False
        call_trace_patterns = [
            "call trace", "calltrace", "kernel bug", "oops:", "BUG:", "BUG at",
            "WARNING:", "general protection fault",
        ]
        oom_patterns = [
            "out of memory", "oom-kill", "oom_kill_process",
            "kill process", "kswapd",
        ]
        for line in lines:
            lower = line.lower()
            if not calltrace_found:
                for pat in call_trace_patterns:
                    if pat.lower() in lower:
                        calltrace_found = True
                        self.log.info(
                            "  [dmesg] Call-trace pattern matched: %s", line)
                        break
            if not oom_found:
                for pat in oom_patterns:
                    if pat.lower() in lower:
                        oom_found = True
                        self.log.info(
                            "  [dmesg] OOM pattern matched: %s", line)
                        break
        return calltrace_found, oom_found

    # ------------------------------------------------------------------ #
    #  Background traffic helpers                                          #
    # ------------------------------------------------------------------ #

    def _start_background_traffic(self):
        """Launch a background flood-ping from the local host to peer_ip."""
        cmd = ("ping -f -c %d %s > /tmp/ibmveth_pool_ping.log 2>&1"
               % (self.ping_count, self.peer_ip))
        self._ping_proc = process.SubProcess(cmd, shell=True, sudo=True)
        self._ping_proc.start()
        # Give the flood ping a moment to reach steady-state.
        time.sleep(2)

    def _stop_background_traffic(self):
        """Terminate the background flood-ping process."""
        if self._ping_proc is not None:
            self._ping_proc.stop()
            self._ping_proc = None

    # ------------------------------------------------------------------ #
    #  Tear-down                                                           #
    # ------------------------------------------------------------------ #

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
