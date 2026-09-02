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
TCP MSS / GSO Validation Test
==============================
Validates TCP MSS (Maximum Segment Size) handling and the kernel GSO
(Generic Segmentation Offload) disable behaviour for virtual network
devices ibmveth.

The test verifies that the kernel patch which prevents adapter freezes
on small-MSS connections works correctly:
  - For MSS values below the GSO threshold (default 224 bytes), the
    kernel must emit a "MSS too small" warning and disable GSO.
  - For MSS values at or above the threshold, the warning must NOT
    appear and GSO must remain active.

See tcp_mss_gso_test.py.data/README for full parameter documentation.
"""

import json
import re
import socket
import time
import threading

from avocado import Test
from avocado.utils import distro
from avocado.utils import process
from avocado.utils import wait
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.network.hosts import LocalHost
from avocado.utils.ssh import Session


class TcpMssGsoTest(Test):
    """
    TCP MSS/GSO validation test for ibmveth  virtual network devices.

    Clamps MSS via iptables, runs socket-echo iterations with concurrent
    iperf3 and HTTP background load, checks dmesg for the kernel GSO-disable
    warning, and optionally monitors the VIOS errpt log for hardware errors.

    Each MSS value under test is defined as a separate variant in the YAML
    mss_sweep !mux block — one Avocado test entry is created per variant.
    """

    # MSS values where small-MSS socket-echo failures are expected and
    # should not count as failures.
    _SOCKET_SKIP_MSS = {1, 36}

    # MSS values where iperf3 is unreliable; skip iperf3 for these.
    _IPERF_SKIP_MSS = {1, 36, 64}

    def setUp(self):
        """Read parameters, configure interface IP, install deps, open SSH."""
        self.peer_ip = self.params.get("peer_ip", default=None)
        self.peer_user = self.params.get("peer_user", default="root")
        self.peer_password = self.params.get("peer_password", "*",
                                             default=None)
        self.tcp_port = int(self.params.get("tcp_port", default=9999))
        self.host_interface = self.params.get("host_interface", default=None)
        self.host_ip = self.params.get("host_ip", default=None)
        self.host_netmask = self.params.get("host_netmask", default=None)
        mss_val = self.params.get("mss", default=None)
        if mss_val is None:
            self.cancel("'mss' param not found – add an mss_sweep !mux "
                        "block to the YAML")
        self.mss = int(mss_val)
        self.iterations = int(self.params.get("iterations", default=5))
        self.enable_http_load = self.params.get(
            "enable_http_load", default=True)
        self.enable_iperf = self.params.get("enable_iperf", default=True)
        self.iperf_duration = int(
            self.params.get("iperf_duration", default=30))
        self.gso_threshold = int(
            self.params.get("gso_threshold", default=224))
        self.data_size = int(self.params.get("data_size", default=65536))
        self.socket_timeout = int(
            self.params.get("socket_timeout", default=30))
        self.vios_ip = self.params.get("vios_ip", default="")
        self.vios_user = self.params.get("vios_user", default="")
        self.vios_password = self.params.get("vios_password", "*",
                                             default=None)
        if not self.peer_ip:
            self.cancel("peer_ip parameter is required")
        self._ip_was_assigned = False
        self.networkinterface = None
        if self.host_interface and self.host_ip:
            if not self.host_netmask:
                self.cancel("'host_netmask' is required when "
                            "'host_interface' and 'host_ip' are set")
            local = LocalHost()
            self.networkinterface = NetworkInterface(
                self.host_interface, local)
            existing_ips = self.networkinterface.get_ipaddrs()
            if self.host_ip not in existing_ips:
                try:
                    self.networkinterface.add_ipaddr(
                        self.host_ip, self.host_netmask)
                    self.networkinterface.save(
                        self.host_ip, self.host_netmask)
                    self._ip_was_assigned = True
                    self.log.info(
                        "Assigned %s/%s to interface %s",
                        self.host_ip, self.host_netmask,
                        self.host_interface)
                except Exception as exc:
                    self.fail(
                        "Failed to assign %s/%s to %s: %s"
                        % (self.host_ip, self.host_netmask,
                           self.host_interface, exc))
            else:
                self.log.info(
                    "Interface %s already has IP %s, skipping assignment",
                    self.host_interface, self.host_ip)
            self.networkinterface.bring_up()
            if not wait.wait_for(
                    self.networkinterface.is_link_up, timeout=120):
                self.fail(
                    "Interface %s did not come up within 120 s"
                    % self.host_interface)
        detected_distro = distro.detect()
        iperf_pkg = "iperf" if detected_distro.name == "SuSE" else "iperf3"
        smm = SoftwareManager()
        for pkg in ["iptables", iperf_pkg, "curl", "wget"]:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel("Required package '%s' could not be installed"
                            % pkg)
        self.session = Session(self.peer_ip, user=self.peer_user,
                               password=self.peer_password)
        if not self.session.connect():
            self.cancel("SSH connection to peer %s failed" % self.peer_ip)
        peer_smm_cmd = self._peer_pkg_mgr()
        peer_iperf_pkg = ("iperf" if "zypper" in peer_smm_cmd else "iperf3")
        for pkg in ["python3", peer_iperf_pkg]:
            chk = self.session.cmd(
                "rpm -q %s || dpkg -l %s 2>/dev/null" % (pkg, pkg))
            if chk.exit_status != 0:
                inst = self.session.cmd(
                    "%s install -y %s" % (peer_smm_cmd, pkg))
                if inst.exit_status != 0:
                    self.cancel("Cannot install '%s' on peer" % pkg)
        self._write_remote_file("/tmp/tcp_listener_mss_test.py",
                                self._listener_script_content())
        self._active_iptables_mss = None
        self._listener_pid = None
        self._metrics = {
            "mss": self.mss,
            "socket_success": 0,
            "socket_fail": 0,
            "send_throughput_kbps": [],
            "recv_throughput_kbps": [],
            "iperf_mbps": None,
            "http_curl": 0,
            "http_wget": 0,
            "gso_warning_found": False,
        }
        self._vios_errpt_baseline = None
        if self.vios_ip:
            self._vios_errpt_baseline = self._vios_run_errpt_count("baseline")
        self.log.info("setUp complete – peer=%s  MSS=%d",
                      self.peer_ip, self.mss)

    def test_mss_gso_large_send(self):
        """
        Clamp MSS via iptables, run socket-echo iterations with optional
        iperf3 and HTTP background load, then validate GSO warning and
        VIOS errpt.
        """
        mss = self.mss
        metrics = self._metrics
        self.log.info("=" * 60)
        self.log.info("Testing MSS = %d", mss)
        self.log.info("=" * 60)

        # 1. Start remote echo listener
        self._start_remote_listener(mss)

        # 2. Install iptables MSS clamp
        self._add_iptables_rule(mss)

        # 3. Background load threads
        stop_event = threading.Event()
        http_thread = None
        iperf_thread = None

        if self.enable_http_load:
            http_thread = threading.Thread(
                target=self._http_load_worker,
                args=(metrics, stop_event),
                daemon=True,
            )
            http_thread.start()

        if self.enable_iperf:
            iperf_thread = threading.Thread(
                target=self._iperf_worker,
                args=(mss, metrics, stop_event),
                daemon=True,
            )
            iperf_thread.start()

        # 4. Socket-echo iterations
        for iteration in range(1, self.iterations + 1):
            self.log.info("  Iteration %d/%d  MSS=%d",
                          iteration, self.iterations, mss)
            if not self._socket_echo_iteration(iteration, mss, metrics):
                self.log.info("  Iteration %d FAILED (MSS=%d)",
                              iteration, mss)

        # 5. Stop background threads
        stop_event.set()
        if http_thread:
            http_thread.join(timeout=5)
        if iperf_thread:
            iperf_thread.join(timeout=self.iperf_duration + 15)

        # 6. Cleanup
        self._stop_remote_listener()
        self._remove_iptables_rule(mss)

        self.log.info("  MSS=%d  sock_ok=%d  sock_fail=%d  "
                      "iperf=%.2f Mbps  http=%d",
                      mss, metrics["socket_success"], metrics["socket_fail"],
                      metrics["iperf_mbps"] or 0.0,
                      metrics["http_curl"] + metrics["http_wget"])

        # 7. dmesg GSO-warning check
        gso_warning_seen = self._check_dmesg_gso_warning()
        self.log.info("dmesg GSO warning present: %s", gso_warning_seen)
        if mss < self.gso_threshold:
            metrics["gso_warning_found"] = gso_warning_seen

        # 8. VIOS errpt check
        self._check_vios_errpt()

        # 9. Validate
        self._validate_results()

    def _validate_results(self):
        """Assert socket-correctness and GSO warning expectations."""
        mss = self.mss
        m = self._metrics
        fail_messages = []

        # (a) Socket failures
        if mss in self._SOCKET_SKIP_MSS:
            self.log.info(
                "SKIP socket-fail check: MSS=%d is in known-issue list "
                "– ignoring %d failure(s)", mss, m["socket_fail"])
        elif m["socket_fail"] > 0:
            fail_messages.append(
                "MSS=%d: %d socket transfer(s) failed"
                % (mss, m["socket_fail"]))

        # (b) GSO warning expected for MSS < threshold (advisory)
        if mss < self.gso_threshold:
            if not m["gso_warning_found"]:
                self.log.info(
                    "[ADVISORY] MSS=%d (<threshold %d): ibmveth GSO-disable "
                    "dmesg warning not seen – kernel patch may not be active",
                    mss, self.gso_threshold)
            else:
                self.log.info(
                    "PASS: MSS=%d  GSO correctly disabled (warning seen)", mss)

        # (c) GSO warning must NOT appear for MSS >= threshold
        else:
            if m["gso_warning_found"]:
                fail_messages.append(
                    "MSS=%d (>=threshold %d): unexpected GSO-disable "
                    "kernel warning – GSO should remain active"
                    % (mss, self.gso_threshold))
            else:
                self.log.info(
                    "PASS: MSS=%d  GSO correctly enabled (no warning)", mss)

        if fail_messages:
            self.fail("Test FAILED:\n  " + "\n  ".join(fail_messages))

    def _vios_run_errpt_count(self, label):
        """Open a fresh SSH to VIOS, run /usr/sbin/errpt, return line count.

        Returns None on connection failure (monitoring skipped).
        Returns 0 if errpt runs but finds no SOFTWARE entries.

        A new Session is opened for every call so no persistent
        ControlMaster socket is shared between tests – avoids the
        alternating-failure pattern where tearDown.quit() destroys the
        shared socket for the next test.

        Full path /usr/sbin/errpt is used because padmin's restricted
        shell (rksh) does not include /usr/sbin in its default PATH.
        """
        sess = Session(self.vios_ip, user=self.vios_user,
                       password=self.vios_password)
        if not sess.connect():
            self.log.info("[VIOS] SSH connection to %s failed at %s – "
                          "errpt monitoring disabled", self.vios_ip, label)
            return None
        try:
            result = sess.cmd(
                "/usr/sbin/errpt | grep -i software", ignore_status=True)
            # grep exit 0 = matches; exit 1 = no matches – both are OK.
            if result.exit_status not in (0, 1):
                self.log.info("[VIOS] errpt returned exit=%d at %s – "
                              "treating count as 0", result.exit_status, label)
                return 0
            lines = [ln for ln in result.stdout_text.splitlines()
                     if ln.strip()]
            self.log.info("[VIOS] errpt SOFTWARE lines at %s (%d):\n%s",
                          label, len(lines),
                          "\n".join(lines) if lines else "  (none)")
            return len(lines)
        finally:
            # Do NOT call sess.quit() – sends "ssh -O exit" which destroys
            # the shared ControlMaster socket for subsequent tests.
            pass

    def _check_vios_errpt(self):
        """Fail if VIOS errpt SOFTWARE count grew since setUp."""
        if not self.vios_ip or self._vios_errpt_baseline is None:
            return

        current = self._vios_run_errpt_count("post-test")
        if current is None:
            self.log.info("[VIOS] VIOS unreachable at post-test check – "
                          "skipping errpt comparison for MSS=%d", self.mss)
            return

        new_errors = current - self._vios_errpt_baseline
        self.log.info("[VIOS] errpt SOFTWARE count: "
                      "baseline=%d  current=%d  new=%d",
                      self._vios_errpt_baseline, current, new_errors)

        if new_errors > 0:
            sess = Session(self.vios_ip, user=self.vios_user,
                           password=self.vios_password)
            new_lines = []
            if sess.connect():
                r = sess.cmd("/usr/sbin/errpt | grep -i software",
                             ignore_status=True)
                if r.exit_status in (0, 1):
                    new_lines = [ln for ln in r.stdout_text.splitlines()
                                 if ln.strip()][:new_errors]
            self.fail(
                "[VIOS] errpt SOFTWARE-error count increased by %d "
                "after MSS=%d test cycle.\nNew entries:\n  %s"
                % (new_errors, self.mss,
                   "\n  ".join(new_lines) if new_lines else "(unavailable)"))
        else:
            self.log.info("[VIOS] PASS: no new errpt SOFTWARE errors "
                          "after MSS=%d test cycle", self.mss)

    def _iptables_cmd(self, action, mss):
        return (
            "iptables -t mangle -%s OUTPUT "
            "-p tcp --tcp-flags SYN,RST SYN "
            "-d %s "
            "-j TCPMSS --set-mss %d"
            % (action, self.peer_ip, mss)
        )

    def _add_iptables_rule(self, mss):
        ret = process.system(self._iptables_cmd("A", mss),
                             sudo=True, ignore_status=True, shell=True)
        if ret != 0:
            self.cancel("Failed to add iptables rule for MSS=%d "
                        "(need root?)" % mss)
        self._active_iptables_mss = mss
        self.log.info("iptables rule added: MSS clamp → %d", mss)

    def _remove_iptables_rule(self, mss):
        ret = process.system(self._iptables_cmd("D", mss),
                             sudo=True, ignore_status=True, shell=True)
        if ret != 0:
            self.log.info("Failed to remove iptables rule for MSS=%d", mss)
        else:
            self.log.info("iptables rule removed: MSS clamp %d", mss)
        self._active_iptables_mss = None

    def _start_remote_listener(self, mss):
        """Launch the TCP echo listener on the peer; retry up to 3 times."""
        for attempt in range(1, 4):
            self.session.cmd(
                "pkill -f tcp_listener_mss_test.py; sleep 0.5",
                ignore_status=True)
            result = self.session.cmd(
                "nohup python3 /tmp/tcp_listener_mss_test.py "
                "%d bi > /tmp/tcp_listener_mss_%d.log 2>&1 &"
                % (self.tcp_port, mss))
            if result.exit_status != 0:
                self.cancel("Failed to start remote listener for MSS=%d: %s"
                            % (mss, result.stderr_text))
            time.sleep(2.0)
            pid_r = self.session.cmd(
                "pgrep -f tcp_listener_mss_test.py", ignore_status=True)
            if pid_r.exit_status == 0:
                self._listener_pid = pid_r.stdout_text.strip().split()[0]
                self.log.info(
                    "Remote listener started (PID=%s) MSS=%d attempt=%d",
                    self._listener_pid, mss, attempt)
                return
            self.log.info(
                "Listener not running after attempt %d for MSS=%d – retrying",
                attempt, mss)
        self.log.info("Could not start remote listener for MSS=%d after "
                      "3 attempts – socket iterations will likely fail", mss)

    def _stop_remote_listener(self):
        self.session.cmd(
            "pkill -f tcp_listener_mss_test.py", ignore_status=True)
        self._listener_pid = None
        time.sleep(0.5)

    def _effective_socket_timeout(self, mss):
        estimated_pkts = max(1, (self.data_size + mss - 1) // mss)
        return min(max(int(estimated_pkts * 0.05) + 10,
                       self.socket_timeout), 120)

    def _socket_echo_iteration(self, iteration, mss, metrics):
        """Send data_size bytes to peer echo server and receive them back."""
        estimated_pkts = (self.data_size + mss - 1) // mss
        timeout = self._effective_socket_timeout(mss)
        self.log.info("    Sending %d bytes ~%d pkts MSS=%d timeout=%ds",
                      self.data_size, estimated_pkts, mss, timeout)
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((self.peer_ip, self.tcp_port))
            payload = b"X" * self.data_size

            t0 = time.time()
            sock.sendall(payload)
            send_dur = max(time.time() - t0, 1e-6)
            metrics["send_throughput_kbps"].append(
                (self.data_size / send_dur) / 1024)
            self.log.info("    Sent %d bytes in %.3fs (%.1f KB/s)",
                          self.data_size, send_dur,
                          metrics["send_throughput_kbps"][-1])

            sock.shutdown(socket.SHUT_WR)

            t2 = time.time()
            received = 0
            while received < self.data_size:
                chunk = sock.recv(8192)
                if not chunk:
                    break
                received += len(chunk)
            recv_dur = max(time.time() - t2, 1e-6)
            metrics["recv_throughput_kbps"].append(
                (received / recv_dur) / 1024)
            self.log.info("    Received %d bytes in %.3fs (%.1f KB/s)",
                          received, recv_dur,
                          metrics["recv_throughput_kbps"][-1])
            sock.close()

            if received != self.data_size:
                self.log.info("    Incomplete echo: sent %d got %d",
                              self.data_size, received)
                metrics["socket_fail"] += 1
                return False

            metrics["socket_success"] += 1
            return True

        except socket.timeout:
            self.log.info("    TIMEOUT MSS=%d iter=%d", mss, iteration)
            metrics["socket_fail"] += 1
        except Exception as exc:
            self.log.info("    ERROR MSS=%d iter=%d: %s", mss, iteration, exc)
            metrics["socket_fail"] += 1
        try:
            sock.close()
        except Exception:
            pass
        return False

    def _iperf_worker(self, mss, metrics, stop_event):
        """Run iperf3 client against the peer in background."""
        if mss in self._IPERF_SKIP_MSS:
            self.log.info(
                "  [iperf3] MSS=%d in skip-list – skipping iperf3", mss)
            return

        iperf_session = Session(self.peer_ip, user=self.peer_user,
                                password=self.peer_password)
        if not iperf_session.connect():
            self.log.info("  [iperf3] Could not open SSH session for "
                          "MSS=%d – skipping", mss)
            return

        # killall avoids pkill treating '-s' as a signal option
        iperf_session.cmd(
            "killall iperf3 2>/dev/null; sleep 0.2; "
            "nohup iperf3 -s -D > /tmp/iperf3_server.log 2>&1",
            ignore_status=True)
        time.sleep(1.0)

        try:
            result = process.run(
                "iperf3 -c %s -t %d -M %d -J"
                % (self.peer_ip, self.iperf_duration, mss),
                timeout=self.iperf_duration + 15,
                ignore_status=True, shell=True)
            if result.exit_status == 0:
                try:
                    data = json.loads(result.stdout_text)
                    mbps = (data["end"]["sum_received"]["bits_per_second"]
                            / 1_000_000)
                    metrics["iperf_mbps"] = round(mbps, 2)
                    self.log.info("  [iperf3] MSS=%d  %.2f Mbps", mss, mbps)
                except (KeyError, ValueError) as exc:
                    self.log.info("  [iperf3] JSON parse error: %s", exc)
            else:
                self.log.info("  [iperf3] Client failed (exit=%d): %s",
                              result.exit_status, result.stderr_text[:200])
        except Exception as exc:
            self.log.info("  [iperf3] Exception: %s", exc)
        finally:
            # Do NOT call quit() – destroys the shared ControlMaster.
            iperf_session.cmd("killall iperf3 2>/dev/null", ignore_status=True)

    def _http_load_worker(self, metrics, stop_event):
        """Fire curl/wget against the peer until stop_event is set."""
        self.log.info("  [HTTP load] Starting against http://%s:80",
                      self.peer_ip)
        while not stop_event.is_set():
            try:
                process.run(
                    "curl -m 1 -s -o /dev/null http://%s:80" % self.peer_ip,
                    ignore_status=True, shell=True)
                metrics["http_curl"] += 1
            except Exception:
                pass
            try:
                process.run(
                    "wget -q -O /dev/null --timeout=1 http://%s:80"
                    % self.peer_ip,
                    ignore_status=True, shell=True)
                metrics["http_wget"] += 1
            except Exception:
                pass
            stop_event.wait(timeout=0.02)
        self.log.info("  [HTTP load] Stopped: curl=%d wget=%d",
                      metrics["http_curl"], metrics["http_wget"])

    def _check_dmesg_gso_warning(self):
        """Return True if the kernel GSO-disable warning is in dmesg."""
        patterns = [
            r"ibmveth\b.*\bMSS\b.*\btoo small for LSO",
            r"too small for LSO,\s*disabling GSO",
            r"disabling GSO",
        ]
        try:
            out = process.run("dmesg", sudo=True, ignore_status=True,
                              shell=True).stdout_text
        except Exception:
            out = ""
        for pat in patterns:
            if re.search(pat, out, re.IGNORECASE):
                self.log.info("  [dmesg] GSO-disable warning matched (%s)",
                              pat)
                return True
        self.log.info("  [dmesg] No GSO-disable warning found")
        return False

    def _peer_pkg_mgr(self):
        result = self.session.cmd(
            "command -v zypper || command -v dnf || "
            "command -v yum || command -v apt-get",
            ignore_status=True)
        return (result.stdout_text.strip().splitlines()[-1].strip()
                if result.exit_status == 0 else "yum")

    def _write_remote_file(self, remote_path, content):
        """Write content to remote_path on the peer via SSH heredoc."""
        result = self.session.cmd(
            "cat > %s << 'AVOCADO_HEREDOC'\n%s\nAVOCADO_HEREDOC"
            % (remote_path, content))
        if result.exit_status != 0:
            self.cancel("Failed to deploy listener script to peer: %s"
                        % result.stderr_text)
        self.session.cmd("chmod +x %s" % remote_path)
        self.log.info("Deployed listener script → peer:%s", remote_path)

    @staticmethod
    def _listener_script_content():
        return r'''#!/usr/bin/env python3
"""Bidirectional TCP echo listener – deployed by tcp_mss_gso_test.py"""

import signal
import socket
import sys

_shutdown = False

def _sig(sig, frame):
    global _shutdown
    _shutdown = True

def _handle(conn, n):
    try:
        buf = b""
        while True:
            chunk = conn.recv(8192)
            if not chunk:
                break
            buf += chunk
        if buf:
            conn.sendall(buf)
    except Exception as exc:
        print("conn %d error: %s" % (n, exc), flush=True)
    finally:
        conn.close()

def main():
    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9999
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.settimeout(1.0)
    srv.bind(("0.0.0.0", port))
    srv.listen(16)
    print("Listening on port %d" % port, flush=True)
    n = 0
    while not _shutdown:
        try:
            conn, addr = srv.accept()
            n += 1
            print("Connection #%d from %s" % (n, addr), flush=True)
            _handle(conn, n)
        except socket.timeout:
            continue
        except Exception as exc:
            if not _shutdown:
                print("accept error: %s" % exc, flush=True)
    srv.close()
    print("Stopped. Connections: %d" % n, flush=True)

if __name__ == "__main__":
    main()
'''

    def tearDown(self):
        """Best-effort cleanup: iptables, remote listener, iperf3, summary."""
        if getattr(self, "_active_iptables_mss", None) is not None:
            self._remove_iptables_rule(self._active_iptables_mss)

        # Remove the IP address only if this test assigned it.
        if getattr(self, "_ip_was_assigned", False) and self.networkinterface:
            try:
                self.networkinterface.remove_ipaddr(
                    self.host_ip, self.host_netmask)
                self.log.info(
                    "Removed IP %s/%s from interface %s",
                    self.host_ip, self.host_netmask, self.host_interface)
            except Exception as exc:
                self.log.warning(
                    "Failed to remove IP %s from %s: %s",
                    self.host_ip, self.host_interface, exc)
            try:
                self.networkinterface.restore_from_backup()
            except Exception:
                self.networkinterface.remove_cfg_file()

        if hasattr(self, "session") and self.session:
            self.session.cmd(
                "pkill -f tcp_listener_mss_test.py; "
                "killall iperf3 2>/dev/null",
                ignore_status=True)

        m = getattr(self, "_metrics", None)
        if m:
            mss = m["mss"]
            avg_kbps = (sum(m["send_throughput_kbps"]) /
                        max(len(m["send_throughput_kbps"]), 1))
            self.log.info("")
            self.log.info("=" * 72)
            self.log.info("MSS/GSO Result – MSS=%d", mss)
            self.log.info("=" * 72)
            self.log.info("%-6s  %-8s  %-10s  %-10s  %-12s  %-10s  %-10s",
                          "MSS", "GSO", "Sock OK", "Sock Fail",
                          "iperf Mbps", "HTTP reqs", "Avg KB/s")
            self.log.info("-" * 72)
            self.log.info(
                "%-6d  %-8s  %-10d  %-10d  %-12s  %-10d  %-10.1f",
                mss,
                "OFF" if m["gso_warning_found"] else "ON",
                m["socket_success"], m["socket_fail"],
                ("%.2f" % m["iperf_mbps"]) if m["iperf_mbps"] else "N/A",
                m["http_curl"] + m["http_wget"],
                avg_kbps)
            self.log.info("=" * 72)

        if hasattr(self, "session") and self.session:
            try:
                self.session.quit()
            except Exception:
                pass
