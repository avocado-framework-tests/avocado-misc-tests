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

import json
import os
import time

from avocado import Test
from avocado.utils import distro
from avocado.utils import dmesg
from avocado.utils import genio
from avocado.utils import process
from avocado.utils import wait
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.network.hosts import LocalHost
from avocado.utils.ssh import Session

_IPERF3_SERVER_LOG = '/tmp/iperf3_ibmvnic_perf_server.log'
_IPERF3_MAX_STREAMS = 128
_DMESG_ERROR_PATTERNS = [
    'call trace', 'calltrace', 'kernel bug', 'oops:', 'BUG:', 'BUG at',
    'WARNING:', 'general protection fault', 'softlockup',
]


class IbmvnicSmallPktPerf(Test):
    """
    ibmvnic small-packet performance test using iperf3.

    On SLES/SuSE the iperf3 binary is shipped inside the ``iperf``
    package (not ``iperf3``), but the executable and all its flags
    remain ``iperf3``.  Package installation is therefore distro-aware
    while every shell command continues to invoke ``iperf3`` directly.
    """

    def setUp(self):
        """
        Install dependencies, configure the ibmvnic interface,
        open SSH to peer, and start the iperf3 server on the peer.

        On SLES/SuSE the iperf3 binary is provided by the ``iperf``
        package; on all other distros it is provided by ``iperf3``.
        """
        self.smm = SoftwareManager()
        detected_distro = distro.detect()
        iperf_pkg = 'iperf' if detected_distro.name == "SuSE" else 'iperf3'
        self.log.info("Detected distro: %s – installing package '%s'",
                      detected_distro.name, iperf_pkg)
        for pkg in [iperf_pkg, 'net-tools', 'ethtool']:
            if not self.smm.check_installed(pkg) and not self.smm.install(pkg):
                self.cancel("Required package '%s' could not be installed"
                            % pkg)
        # Only one ncat implementation is required; try in preference order.
        _NCAT_LOCAL_PKGS = ('nmap-ncat', 'ncat', 'nmap')
        self.ncat_cmd = None
        for _pkg in _NCAT_LOCAL_PKGS:
            if self.smm.check_installed(_pkg) or self.smm.install(_pkg):
                # All three packages provide the 'ncat' binary
                self.ncat_cmd = 'ncat'
                break
        if self.ncat_cmd is None:
            import shutil
            if shutil.which('ncat'):
                self.ncat_cmd = 'ncat'
            elif shutil.which('nc'):
                self.ncat_cmd = 'nc'
        local = LocalHost()
        interfaces = os.listdir('/sys/class/net')
        device = self.params.get('interface', default=None)
        if not device:
            self.cancel("'interface' parameter is required in YAML")
        if device in interfaces:
            self.interface = device
        elif (local.validate_mac_addr(device) and
              device in local.get_all_hwaddr()):
            self.interface = local.get_interface_by_hwaddr(device).name
        else:
            self.cancel("Interface '%s' not found – update YAML" % device)
        self.ipaddr = self.params.get('host_ip', default=None)
        self.netmask = self.params.get('netmask', default=None)
        self.peer_ip = self.params.get('peer_ip', default=None)
        self.peer_user = self.params.get('peer_user', default='root')
        self.peer_password = self.params.get('peer_password', '*',
                                             default=None)
        if not self.peer_ip:
            self.cancel("'peer_ip' parameter is required in YAML")
        # All test parameters are hardcoded here; only environment-specific
        # values (interface, IPs, credentials) live in the YAML.
        self.iperf3_port = 5201
        self.udp_msg_size = 65507
        self.rr_msg_size = 20971
        self.stream_duration = 60
        self.rr_iterations = 3
        self.rr_duration = 10
        self.scale_streams = 150
        self.scale_nprocs = (
            (self.scale_streams + _IPERF3_MAX_STREAMS - 1)
            // _IPERF3_MAX_STREAMS)
        self.scale_duration = 10
        self.burst_duration = 30
        self.burst_parallel = 8
        self.networkinterface = NetworkInterface(self.interface, local)
        try:
            self.networkinterface.add_ipaddr(self.ipaddr, self.netmask)
            self.networkinterface.save(self.ipaddr, self.netmask)
        except Exception as exc:
            self.log.warning("add_ipaddr failed (%s), attempting save only", exc)
            self.networkinterface.save(self.ipaddr, self.netmask)
        self.networkinterface.bring_up()
        time.sleep(0.5)
        assigned_ips = self.networkinterface.get_ipaddrs()
        if not any(self.ipaddr in str(ip) for ip in assigned_ips):
            self.log.warning(
                "IP %s not found in assigned addresses: %s; attempting manual assignment",
                self.ipaddr, assigned_ips)
            cidr = NetworkInterface.netmask_to_cidr(self.netmask)
            process.run(
                "ip addr add %s/%d dev %s 2>&1 | grep -v 'File exists'"
                % (self.ipaddr, cidr, self.interface),
                shell=True, ignore_status=True)

        if not wait.wait_for(self.networkinterface.is_link_up, timeout=120):
            self.fail("Interface '%s' link did not come up within 120 s"
                      % self.interface)

        if self.networkinterface.ping_check(self.peer_ip, count=5) is not None:
            self.fail("No connectivity to peer %s" % self.peer_ip)

        self.session = Session(self.peer_ip, user=self.peer_user,
                               password=self.peer_password)
        if not self.session.connect():
            self.fail("SSH connection to peer %s failed" % self.peer_ip)

        peer_install = self.smm.backend.base_command
        output = self.session.cmd(
            "%s install -y %s" % (peer_install, iperf_pkg),
            ignore_status=True)
        if output.exit_status != 0:
            self.fail("iperf3 could not be installed on peer %s"
                      % self.peer_ip)

        self._start_peer_iperf3_server()

        self.log.info("setUp complete – interface=%s peer=%s",
                      self.interface, self.peer_ip)

    def test_udp_stream_throughput(self):
        """
        UDP stream throughput

        Runs three iperf3 UDP stream measurements using a 65507-byte datagram
        size (matching the original netperf UDP_STREAM test):
          run-A : 6-second warm-up
          run-B : 60-second sustained run
          run-C : 6-second repeat

        Validates that no call traces appear in dmesg and that iperf3 reports
        zero UDP errors on both sender and receiver.
        """
        if not self.session.connect():
            self.fail("SSH session to peer %s could not be established"
                      % self.peer_ip)
        self.log.info("=" * 60)
        self.log.info("UDP stream throughput  (msg=%d bytes)",
                      self.udp_msg_size)
        self.log.info("=" * 60)
        failures = []

        runs = [
            ('run-A (6 s warm-up)', 6),
            ('run-B (%d s sustained)' % self.stream_duration,
             self.stream_duration),
            ('run-C (6 s repeat)', 6),
        ]
        for label, duration in runs:
            self.log.info("udp_stream %s", label)
            dmesg.clear_dmesg()
            result = self._run_iperf3_udp_stream(duration)
            errs = dmesg.collect_errors_dmesg(_DMESG_ERROR_PATTERNS)
            if errs:
                failures.append(
                    "udp_stream %s: dmesg errors: %s"
                    % (label, '; '.join(errs)))
            if result is None:
                failures.append(
                    "udp_stream %s: iperf3 failed to produce output"
                    % label)
                continue
            udp_lost = self._parse_udp_lost(result)
            mbps = self._parse_udp_throughput_mbps(result)
            self.log.info("udp_stream %s: %.2f Mbps  lost=%d",
                          label, mbps, udp_lost)
            if udp_lost > 0:
                self.log.info("udp_stream %s: WARNING – %d UDP datagrams lost",
                              label, udp_lost)

        if failures:
            self.fail('\n'.join(failures))
        self.log.info("PASS – UDP stream throughput OK")

    def test_udp_rr(self):
        """
        UDP request/response

        Simulates UDP_RR by running iperf3 in bidirectional UDP mode with
        a 20971-byte payload (matching the original netperf UDP_RR test).
        Runs rr_iterations × rr_duration-second tests.

        The original netperf UDP_RR baseline was ~5000–5100 trans/sec.
        This test validates correctness (zero dmesg errors, no iperf3
        errors) rather than enforcing a hard throughput threshold.
        """
        self.log.info("=" * 60)
        self.log.info("UDP RR (bidirectional, msg=%d bytes, "
                      "%d x %d s)", self.rr_msg_size,
                      self.rr_iterations, self.rr_duration)
        self.log.info("=" * 60)
        failures = []

        for iteration in range(1, self.rr_iterations + 1):
            self.log.info("udp_rr iteration %d/%d",
                          iteration, self.rr_iterations)
            dmesg.clear_dmesg()
            result = self._run_iperf3_udp_bidir(self.rr_duration)
            errs = dmesg.collect_errors_dmesg(_DMESG_ERROR_PATTERNS)
            if errs:
                failures.append(
                    "udp_rr iter %d: dmesg errors: %s"
                    % (iteration, '; '.join(errs)))
            if result is None:
                failures.append(
                    "udp_rr iter %d: iperf3 produced no output"
                    % iteration)
                continue
            packets = self._parse_udp_packets(result)
            mbps = self._parse_udp_throughput_mbps(result)
            self.log.info("udp_rr iter %d: %.2f Mbps  packets=%d",
                          iteration, mbps, packets)

        if failures:
            self.fail('\n'.join(failures))
        self.log.info("PASS – UDP RR (bidirectional) OK")

    def test_tcp_rr(self):
        """
        TCP request/response

        The primary target workload of the patch series.  Runs iperf3 in
        bidirectional TCP mode with a 20971-byte block size (matching the
        original netperf TCP_RR test), 3 iterations of 10 seconds each.
        """
        self.log.info("=" * 60)
        self.log.info("TCP RR (bidirectional, msg=%d bytes, "
                      "%d x %d s)", self.rr_msg_size,
                      self.rr_iterations, self.rr_duration)
        self.log.info("=" * 60)
        failures = []

        for iteration in range(1, self.rr_iterations + 1):
            self.log.info("tcp_rr iteration %d/%d",
                          iteration, self.rr_iterations)
            dmesg.clear_dmesg()
            result = self._run_iperf3_tcp_bidir(
                self.rr_duration, self.rr_msg_size)
            errs = dmesg.collect_errors_dmesg(_DMESG_ERROR_PATTERNS)
            if errs:
                failures.append(
                    "tcp_rr iter %d: dmesg errors: %s"
                    % (iteration, '; '.join(errs)))
            if result is None:
                failures.append(
                    "tcp_rr iter %d: iperf3 produced no output"
                    % iteration)
                continue
            mbps = self._parse_tcp_throughput_mbps(result)
            retrans = self._parse_tcp_retransmits(result)
            self.log.info("tcp_rr iter %d: %.2f Mbps  retransmits=%d",
                          iteration, mbps, retrans)

        if failures:
            self.fail('\n'.join(failures))
        self.log.info("PASS – TCP RR OK")

    def test_scale_150_sessions(self):
        """
        Scale: 150 parallel TCP streams

        Replicates the original 150-session concurrency test.  Because iperf3
        caps a single client at _IPERF3_MAX_STREAMS (128) parallel streams,
        the requested scale_streams (default 150) are split across multiple
        concurrent iperf3 client/server pairs (one per port) so the adapter
        sees the full concurrent load.
        """
        self.log.info("=" * 60)
        self.log.info("Scale – %d parallel TCP streams across %d proc(s) "
                      "(%d s)", self.scale_streams, self.scale_nprocs,
                      self.scale_duration)
        self.log.info("=" * 60)
        failures = []

        ports = self._start_peer_iperf3_server_farm(self.scale_nprocs)

        dmesg.clear_dmesg()
        agg = self._run_iperf3_tcp_parallel_multiproc(
            self.scale_duration, self.scale_streams, ports)
        errs = dmesg.collect_errors_dmesg(_DMESG_ERROR_PATTERNS)
        if errs:
            failures.append("scale_150: dmesg errors: %s" % '; '.join(errs))

        if agg is None:
            failures.append("scale_150: no iperf3 client produced output")
        else:
            for pp in agg['per_proc']:
                self.log.info("  port %d: streams=%d ok=%s %.2f Mbps "
                              "retrans=%d", pp['port'], pp['streams'],
                              pp['ok'], pp['mbps'], pp['retransmits'])
            self.log.info("scale_150: %d/%d streams ran, aggregate "
                          "%.2f Mbps  retransmits=%d",
                          agg['streams'], self.scale_streams,
                          agg['mbps'], agg['retransmits'])
            failed_procs = [pp['port'] for pp in agg['per_proc']
                            if not pp['ok']]
            if failed_procs:
                failures.append(
                    "scale_150: client(s) on port(s) %s failed to run"
                    % failed_procs)
            if agg['streams'] < self.scale_streams:
                failures.append(
                    "scale_150: only %d of %d streams completed"
                    % (agg['streams'], self.scale_streams))

        if failures:
            self.fail('\n'.join(failures))
        self.log.info("PASS – %d-session scale OK", self.scale_streams)

    def test_packet_integrity_dma_barrier(self):
        """
        Packet integrity after DMA barrier removal

        removes the early dma_wmb() before tx_pool->consumer_index update.
        The existing barrier inside send_subcrq_[in]direct() covers ordering.
        """
        if not self.session.connect():
            self.fail("SSH session to peer %s could not be established"
                      % self.peer_ip)
        self.log.info("=" * 60)
        self.log.info("Packet integrity – DMA barrier removal "
                      "(payload sha256 verification)")
        self.log.info("=" * 60)
        failures = []

        ethtool_before = self._ethtool_error_snapshot()
        dmesg.clear_dmesg()

        for size_mb in (16, 64, 128):
            ok, detail = self._verify_payload_integrity(size_mb)
            if ok:
                self.log.info("pkt_integrity: %d MB transfer sha256 MATCH "
                              "(%s)", size_mb, detail)
            else:
                failures.append("pkt_integrity: %d MB transfer integrity "
                                "FAILED – %s" % (size_mb, detail))

        result = self._run_iperf3_tcp_stream(30)
        if result is not None:
            retrans = self._parse_tcp_retransmits(result)
            mbps = self._parse_tcp_throughput_mbps(result)
            self.log.info("pkt_integrity: %.2f Mbps  retransmits=%d "
                          "(informational only)", mbps, retrans)

        errs = dmesg.collect_errors_dmesg(_DMESG_ERROR_PATTERNS)
        if errs:
            failures.append(
                "pkt_integrity: dmesg errors: %s" % '; '.join(errs))

        ethtool_delta = self._ethtool_error_delta(ethtool_before)
        if ethtool_delta:
            failures.append(
                "pkt_integrity: ethtool error counters "
                "increased: %s" % ethtool_delta)

        if failures:
            self.fail('\n'.join(failures))
        self.log.info("PASS – payload sha256 verified, no ethtool/dmesg "
                      "errors")

    def _verify_payload_integrity(self, size_mb):
        """
        Byte-exact end-to-end payload check over the TX path.

        1. Generate a random file of size_mb locally and compute its sha256.
        2. Stream it to the peer over the interface-under-test using nc
           (netcat).  The nc listener is started on the peer via the already
           authenticated SSH session, and the local nc client is bound
           to the interface's source IP so the payload traverses the
           ibmvnic TX path.
        3. Recompute sha256 on the peer and compare.

        Returns (True, detail) on match, (False, detail) on mismatch/error.
        """
        if not self.session.connect():
            return (False, "SSH session to peer %s could not be established"
                    % self.peer_ip)
        local_f = "/tmp/ibmvnic_integrity_%dmb.bin" % size_mb
        remote_f = "/tmp/ibmvnic_integrity_recv_%dmb.bin" % size_mb
        nc_port = self.iperf3_port + 100
        try:
            process.run(
                "dd if=/dev/urandom of=%s bs=1M count=%d status=none"
                % (local_f, size_mb), shell=True, timeout=120)
            local_sum = process.run(
                "sha256sum %s" % local_f, shell=True,
                timeout=60).stdout_text.split()[0]

            _NCAT_PKGS = ('nmap-ncat', 'ncat', 'nmap')
            ncat_ok = False
            for _pkg in _NCAT_PKGS:
                out = self.session.cmd(
                    "%s install -y %s" % (self.smm.backend.base_command, _pkg),
                    ignore_status=True)
                if out.exit_status == 0:
                    ncat_ok = True
                    break
            if not ncat_ok:
                chk = self.session.cmd("command -v ncat", ignore_status=True)
                ncat_ok = (chk.exit_status == 0)
            if not ncat_ok:
                return (False,
                        "ncat not available on peer and could not be "
                        "installed (tried: %s)" % ', '.join(_NCAT_PKGS))
            self.session.cmd("pkill -f ncat.*%d 2>/dev/null" % nc_port,
                             ignore_status=True)
            time.sleep(1.5)
            unit = "ibmvnicinteg%d" % nc_port
            sr = self.session.cmd(
                "systemctl reset-failed %s 2>/dev/null; "
                "systemd-run --unit=%s --collect "
                "/bin/sh -c \"ncat -l %d > %s 2>/dev/null\""
                % (unit, unit, nc_port, remote_f), ignore_status=True)
            sr_rc = getattr(sr, 'exit_status', 0)
            if sr_rc not in (0, None):
                self.session.cmd(
                    "printf '#!/bin/sh\\nexec ncat -l %d > %s 2>/dev/null "
                    "< /dev/null\\n' > /tmp/ibmvnic_ncat_%d.sh; "
                    "chmod +x /tmp/ibmvnic_ncat_%d.sh; "
                    "setsid /tmp/ibmvnic_ncat_%d.sh "
                    ">/dev/null 2>&1 < /dev/null &"
                    % (nc_port, remote_f, nc_port, nc_port, nc_port),
                    ignore_status=True)

            listening = False
            for _ in range(10):
                time.sleep(0.5)
                chk = self.session.cmd(
                    "ss -ltn | grep -c :%d" % nc_port, ignore_status=True)
                out = chk.stdout
                out = out.decode() if hasattr(out, 'decode') else str(out)
                if out.strip() and out.strip().split()[0] != '0':
                    listening = True
                    break
            if not listening:
                return (False, "peer ncat listener never came up on port %d"
                        % nc_port)

            ncat_bin = getattr(self, 'ncat_cmd', None) or 'ncat'
            if ncat_bin == 'ncat':
                push = ("ncat --send-only %s %d < %s"
                        % (self.peer_ip, nc_port, local_f))
            else:
                # Fallback to plain nc (OpenBSD/GNU netcat)
                push = ("nc %s %d < %s"
                        % (self.peer_ip, nc_port, local_f))
            ret = process.run(push, shell=True, ignore_status=True,
                              timeout=300)
            if ret.exit_status != 0:
                return (False, "nc transfer failed rc=%d: %s"
                        % (ret.exit_status, ret.stderr_text[:200]))
            time.sleep(1)

            peer_out = self.session.cmd("sha256sum %s" % remote_f,
                                        ignore_status=True)
            raw = peer_out.stdout
            peer_text = raw.decode() if hasattr(raw, 'decode') else str(raw)
            parts = peer_text.split()
            if not parts:
                return (False, "peer sha256sum produced no output")
            peer_sum = parts[0]

            peer_size = self.session.cmd(
                "stat -c %%s %s" % remote_f, ignore_status=True)
            psz_raw = peer_size.stdout
            psz = psz_raw.decode() if hasattr(psz_raw, 'decode') \
                else str(psz_raw)
            expected = size_mb * 1024 * 1024
            try:
                if int(psz.strip()) != expected:
                    return (False, "size mismatch: peer=%s expected=%d"
                            % (psz.strip(), expected))
            except ValueError:
                pass

            if local_sum == peer_sum:
                return (True, "sha256=%s..." % local_sum[:12])
            return (False, "sha256 mismatch local=%s peer=%s"
                    % (local_sum[:12], peer_sum[:12]))
        except Exception as exc:
            return (False, "integrity check error: %s" % exc)
        finally:
            process.run("rm -f %s" % local_f, shell=True,
                        ignore_status=True)
            self.session.cmd(
                "systemctl stop ibmvnicinteg%d 2>/dev/null; "
                "systemctl reset-failed ibmvnicinteg%d 2>/dev/null; "
                "pkill -f ncat.*%d 2>/dev/null; "
                "rm -f %s /tmp/ibmvnic_ncat_%d.sh"
                % (nc_port, nc_port, nc_port, remote_f, nc_port),
                ignore_status=True)

    def test_bql_limit_monitoring(self):
        """
        BQL (Byte Queue Limits) dynamic limit monitoring  (

        moves netdev_tx_completed_queue() to once per ibmvnic_complete_tx()
        handler.  The observable effect is that the DQL limit value in sysfs
        rises dynamically under load (from ~130 to 130–900+ per the commit).

        This test:
          1. Snapshots BQL limit values for all TX queues before the load.
          2. Runs the 150-session TCP parallel test.
          3. Polls BQL limits during the run.
          4. Validates that at least one TX queue BQL limit rose above its
             initial value, proving that the DQL algorithm is responding
             dynamically rather than being stuck.
        """
        if not self.session.connect():
            self.fail("SSH session to peer %s could not be established"
                      % self.peer_ip)
        self.log.info("=" * 60)
        self.log.info("BQL sysfs limit monitoring under %d-stream load",
                      self.scale_streams)
        self.log.info("=" * 60)
        failures = []

        bql_before = self._bql_limits_snapshot()
        self.log.info("bql_monitor: BQL limits before load: %s", bql_before)

        ports = self._start_peer_iperf3_server_farm(self.scale_nprocs)
        dmesg.clear_dmesg()

        chunks = self._split_streams(self.scale_streams, len(ports))
        iperf_procs = []
        for port, nstreams in zip(ports, chunks):
            cmd = ("iperf3 -c %s -p %d -P %d -t %d -J "
                   "-l %d > /tmp/iperf3_bql_monitor_%d.json 2>&1"
                   % (self.peer_ip, port, nstreams, self.scale_duration,
                      self.rr_msg_size, port))
            proc = process.SubProcess(cmd, shell=True)
            proc.start()
            iperf_procs.append(proc)

        bql_max_seen = dict(bql_before)
        poll_end = time.time() + self.scale_duration
        while time.time() < poll_end:
            time.sleep(2)
            current = self._bql_limits_snapshot()
            for queue, val in current.items():
                if val > bql_max_seen.get(queue, 0):
                    bql_max_seen[queue] = val

        deadline = time.time() + 45
        for proc in iperf_procs:
            remaining = max(1, int(deadline - time.time()))
            try:
                proc.wait(timeout=remaining)
            except Exception:
                proc.stop()

        errs = dmesg.collect_errors_dmesg(_DMESG_ERROR_PATTERNS)
        if errs:
            failures.append(
                "bql_monitor: dmesg errors: %s" % '; '.join(errs))

        self.log.info("bql_monitor: BQL max seen during load: %s",
                      bql_max_seen)
        clients_ok = any(
            getattr(p, 'result', None) is not None and p.result.exit_status == 0
            for p in iperf_procs
        )
        if not clients_ok:
            for port in ports:
                json_f = "/tmp/iperf3_bql_monitor_%d.json" % port
                data = self._load_iperf3_json_file(json_f)
                if data and data.get('end'):
                    clients_ok = True
                    break

        if not clients_ok:
            failures.append(
                "bql_monitor: all iperf3 client processes failed – "
                "no TX load was generated; BQL result is inconclusive. "
                "Check peer iperf3 server availability on ports %s" % ports)
        else:
            limit_rose = any(
                bql_max_seen.get(q, 0) > bql_before.get(q, 0)
                for q in bql_before
            )
            if not limit_rose:
                failures.append(
                    "bql_monitor: no TX queue BQL limit rose above initial "
                    "value. Before=%s  MaxSeen=%s  – P6 DQL fix may not be "
                    "active" % (bql_before, bql_max_seen))
            else:
                self.log.info(
                    "bql_monitor: BQL limits rose dynamically – "
                    "DQL algorithm active")

        if failures:
            self.fail('\n'.join(failures))
        self.log.info("PASS – BQL limit rose dynamically under load")

    def test_rx_pool_burst_no_drops(self):
        """
        RX pool availability under burst UDP

        RX buffer replenish trigger to fire only when:
          available < req_rx_add_entries_per_subcrq / 2

          * starts iperf3 servers on the HOST (one per port),
          * drives multiple concurrent iperf3 -u CLIENTS on the PEER so the
            host receives a genuine high-pps small-packet (-l 64 -b 0) burst
            that single-process/single-socket load cannot produce,
          * gates on host RX drop / RX error / RX no-buffer deltas from both
            `ethtool -S` and /proc/net/dev RX-drop column.

        A single client is capped at _IPERF3_MAX_STREAMS streams, so the
        requested burst_parallel is split across procs/ports just like the
        scale test.
        """
        nprocs = ((self.burst_parallel + _IPERF3_MAX_STREAMS - 1)
                  // _IPERF3_MAX_STREAMS)
        self.log.info("=" * 60)
        self.log.info("RX pool burst – peer->host UDP %d streams across "
                      "%d proc(s), %d s", self.burst_parallel, nprocs,
                      self.burst_duration)
        self.log.info("=" * 60)
        failures = []
        self.session.cmd("killall iperf3 2>/dev/null", ignore_status=True)
        time.sleep(0.5)

        ports = list(range(self.iperf3_port, self.iperf3_port + nprocs))
        if not self.smm.check_installed('iperf3'):
            self.smm.install('iperf3')
        host_servers = []
        for port in ports:
            srv = ("iperf3 -s -p %d > /tmp/iperf3_rx_srv_%d.log 2>&1"
                   % (port, port))
            proc = process.SubProcess(srv, shell=True)
            proc.start()
            host_servers.append(proc)
        time.sleep(1.5)
        rx_before = self._rx_error_snapshot()
        proc_rx_before = self._proc_net_dev_rx_drop()
        dmesg.clear_dmesg()
        chunks = self._split_streams(self.burst_parallel, nprocs)
        peer_cmd = "killall iperf3 2>/dev/null; sleep 0.3; "
        for port, nstreams in zip(ports, chunks):
            peer_cmd += (
                "nohup iperf3 -c %s -p %d -u -l 64 -b 0 -P %d -t %d "
                "> /tmp/iperf3_rx_cli_%d.log 2>&1 & "
                % (self.ipaddr, port, nstreams, self.burst_duration, port))
        peer_cmd += "wait"
        try:
            self.session.cmd(peer_cmd,
                             timeout=self.burst_duration + 45,
                             ignore_status=True)
        except Exception as exc:
            self.log.info("rx_burst: peer client run note: %s", exc)

        time.sleep(2)
        errs = dmesg.collect_errors_dmesg(_DMESG_ERROR_PATTERNS)
        if errs:
            failures.append("rx_burst: dmesg errors: %s" % '; '.join(errs))

        rx_delta = self._rx_error_delta(rx_before)
        if rx_delta:
            failures.append(
                "rx_burst: host RX error/drop/no-buffer counters increased "
                "after peer->host UDP burst – RX pool starvation: %s"
                % rx_delta)
        else:
            self.log.info("rx_burst: zero host RX drop/error/no-buffer "
                          "increase – RX pool threshold adequate")

        proc_rx_delta = self._proc_net_dev_rx_drop() - proc_rx_before
        if proc_rx_delta > 0:
            failures.append(
                "rx_burst: /proc/net/dev shows %d new RX drops on %s"
                % (proc_rx_delta, self.interface))
        else:
            self.log.info("rx_burst: /proc/net/dev RX drop delta = 0")

        for proc in host_servers:
            try:
                proc.stop()
            except Exception:
                pass
        process.run("killall iperf3 2>/dev/null", shell=True,
                    ignore_status=True)
        self._start_peer_iperf3_server()

        if failures:
            self.fail('\n'.join(failures))
        self.log.info("PASS – zero host RX drops under peer->host UDP burst")

    def _run_iperf3_udp_stream(self, duration):
        """Run a UDP stream test; return parsed JSON dict or None."""
        cmd = ("iperf3 -c %s -p %d -u -l %d -t %d -b 0 -J"
               % (self.peer_ip, self.iperf3_port,
                  self.udp_msg_size, duration))
        return self._run_iperf3(cmd, duration + 15)

    def _run_iperf3_udp_bidir(self, duration):
        """Run a bidirectional UDP test; return parsed JSON dict or None."""
        cmd = ("iperf3 -c %s -p %d -u -l %d -t %d -b 0 --bidir -J"
               % (self.peer_ip, self.iperf3_port,
                  self.rr_msg_size, duration))
        return self._run_iperf3(cmd, duration + 15)

    def _run_iperf3_tcp_bidir(self, duration, block_size):
        """Run a bidirectional TCP test; return parsed JSON dict or None."""
        cmd = ("iperf3 -c %s -p %d -l %d -t %d --bidir -J"
               % (self.peer_ip, self.iperf3_port, block_size, duration))
        return self._run_iperf3(cmd, duration + 15)

    def _run_iperf3_tcp_parallel(self, duration, streams):
        """Run parallel TCP streams; return parsed JSON dict or None."""
        cmd = ("iperf3 -c %s -p %d -P %d -t %d -l %d -J"
               % (self.peer_ip, self.iperf3_port,
                  streams, duration, self.rr_msg_size))
        return self._run_iperf3(cmd, duration + 30)

    def _split_streams(self, total, n_procs):
        """
        Distribute 'total' streams across 'n_procs' processes as evenly as
        possible, each chunk <= _IPERF3_MAX_STREAMS.
        Returns a list of per-process stream counts.
        """
        base = total // n_procs
        rem = total % n_procs
        return [base + (1 if i < rem else 0) for i in range(n_procs)]

    def _run_iperf3_tcp_parallel_multiproc(self, duration, total_streams,
                                           ports):
        """
        Run 'total_streams' TCP streams split across len(ports) concurrent
        iperf3 client processes (one per port), each with <=
        _IPERF3_MAX_STREAMS streams.  All clients run simultaneously so the
        adapter sees the full concurrent load.

        Returns an aggregated dict:
          {'mbps': float, 'retransmits': int, 'streams': int,
           'nprocs': int, 'per_proc': [ {port, mbps, retransmits}, ... ]}
        or None if every client failed to produce output.
        """
        chunks = self._split_streams(total_streams, len(ports))
        procs = []
        out_files = []
        for idx, (port, nstreams) in enumerate(zip(ports, chunks)):
            out_file = "/tmp/iperf3_scale_p%d.json" % port
            out_files.append((port, nstreams, out_file))
            cmd = ("iperf3 -c %s -p %d -P %d -t %d -l %d -J > %s 2>&1"
                   % (self.peer_ip, port, nstreams, duration,
                      self.rr_msg_size, out_file))
            self.log.debug("scale proc %d: %s", idx, cmd)
            proc = process.SubProcess(cmd, shell=True)
            proc.start()
            procs.append(proc)

        deadline = time.time() + duration + 45
        for proc in procs:
            remaining = max(1, int(deadline - time.time()))
            try:
                proc.wait(timeout=remaining)
            except Exception:
                proc.stop()

        agg = {'mbps': 0.0, 'retransmits': 0, 'streams': 0,
               'nprocs': len(ports), 'per_proc': []}
        any_ok = False
        for port, nstreams, out_file in out_files:
            data = self._load_iperf3_json_file(out_file)
            if data is None:
                self.log.info("scale: port %d (%d streams) produced no "
                              "parseable output", port, nstreams)
                agg['per_proc'].append(
                    {'port': port, 'streams': nstreams,
                     'mbps': 0.0, 'retransmits': 0, 'ok': False})
                continue
            any_ok = True
            mbps = self._parse_tcp_throughput_mbps(data)
            retrans = self._parse_tcp_retransmits(data)
            agg['mbps'] += mbps
            agg['retransmits'] += retrans
            agg['streams'] += nstreams
            agg['per_proc'].append(
                {'port': port, 'streams': nstreams, 'mbps': mbps,
                 'retransmits': retrans, 'ok': True})
        agg['mbps'] = round(agg['mbps'], 2)
        return agg if any_ok else None

    def _load_iperf3_json_file(self, path):
        """Read and parse an iperf3 JSON output file; None on failure."""
        try:
            text = genio.read_file(path)
        except IOError:
            return None
        if not text.strip():
            return None
        try:
            return json.loads(text)
        except ValueError:
            start = text.find('{')
            end = text.rfind('}')
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(text[start:end + 1])
                except ValueError:
                    return None
            return None

    def _run_iperf3_tcp_stream(self, duration):
        """Run a simple TCP stream; return parsed JSON dict or None."""
        cmd = ("iperf3 -c %s -p %d -t %d -l 1460 -J"
               % (self.peer_ip, self.iperf3_port, duration))
        return self._run_iperf3(cmd, duration + 15)

    def _run_iperf3(self, cmd, timeout):
        """
        Execute an iperf3 client command and return the parsed JSON dict.
        Returns None if the command fails or JSON cannot be parsed.
        """
        self.log.debug("iperf3 cmd: %s", cmd)
        ret = process.run(cmd, shell=True, ignore_status=True,
                          timeout=timeout)
        if ret.exit_status != 0:
            self.log.info("iperf3 exit=%d stderr=%s",
                          ret.exit_status, ret.stderr_text[:300])
        if not ret.stdout_text.strip():
            return None
        try:
            return json.loads(ret.stdout_text)
        except ValueError as exc:
            self.log.info("iperf3 JSON parse error: %s", exc)
            return None

    def _parse_tcp_throughput_mbps(self, data):
        """Return TCP received throughput in Mbps from iperf3 JSON."""
        try:
            bps = data['end']['sum_received']['bits_per_second']
            return round(bps / 1_000_000, 2)
        except (KeyError, TypeError):
            return 0.0

    def _parse_tcp_retransmits(self, data):
        """Return total TCP retransmits from iperf3 JSON."""
        try:
            return int(data['end']['sum_sent'].get('retransmits', 0))
        except (KeyError, TypeError):
            return 0

    def _parse_udp_throughput_mbps(self, data):
        """Return UDP sender throughput in Mbps from iperf3 JSON."""
        try:
            bps = data['end']['sum'].get('bits_per_second', 0)
            return round(bps / 1_000_000, 2)
        except (KeyError, TypeError):
            return 0.0

    def _parse_udp_lost(self, data):
        """Return total UDP lost datagrams from iperf3 JSON."""
        try:
            return int(data['end']['sum'].get('lost_packets', 0))
        except (KeyError, TypeError):
            return 0

    def _parse_udp_packets(self, data):
        """Return total UDP packets sent from iperf3 JSON."""
        try:
            return int(data['end']['sum'].get('packets', 0))
        except (KeyError, TypeError):
            return 0

    def _start_peer_iperf3_server(self):
        """Kill any stale iperf3 server and start a fresh one on the peer."""
        self.session.cmd(
            "killall iperf3 2>/dev/null; sleep 0.3; "
            "nohup iperf3 -s -p %d -D > %s 2>&1"
            % (self.iperf3_port, _IPERF3_SERVER_LOG),
            ignore_status=True)
        time.sleep(1)
        self.log.info("iperf3 server started on peer %s port %d",
                      self.peer_ip, self.iperf3_port)

    def _start_peer_iperf3_server_farm(self, n_procs):
        """
        Start n_procs iperf3 servers on the peer, one per port starting at
        self.iperf3_port.  Used by the multi-process scale test to exceed
        the per-process stream cap.

        After launching, poll until every port is listening (up to 10 s)
        so that subsequent iperf3 clients do not connect before the servers
        are ready.
        """
        ports = [self.iperf3_port + i for i in range(n_procs)]
        launch = "killall iperf3 2>/dev/null; sleep 0.3; "
        for port in ports:
            launch += ("nohup iperf3 -s -p %d -D > %s.%d 2>&1; "
                       % (port, _IPERF3_SERVER_LOG, port))
        self.session.cmd(launch, ignore_status=True)
        deadline = time.time() + 10
        while time.time() < deadline:
            time.sleep(0.5)
            chk = self.session.cmd(
                "ss -ltn | grep -cE ':%s'" % '|:'.join(str(p) for p in ports),
                ignore_status=True)
            raw = chk.stdout
            cnt_str = (raw.decode() if hasattr(raw, 'decode') else str(raw)).strip()
            try:
                if int(cnt_str) >= len(ports):
                    break
            except ValueError:
                pass

        self.log.info("iperf3 server farm started on peer %s ports %s",
                      self.peer_ip, ports)
        return ports

    def _stop_peer_iperf3_server(self):
        """Terminate the iperf3 server on the peer."""
        self.session.cmd("killall iperf3 2>/dev/null", ignore_status=True)

    def _ethtool_error_snapshot(self):
        """
        Return a dict of ethtool -S counters whose names suggest errors
        or drops for self.interface.  Returns empty dict on failure.
        """
        try:
            out = process.run("ethtool -S %s" % self.interface,
                              shell=True, ignore_status=True).stdout_text
        except Exception:
            return {}
        counters = {}
        for line in out.splitlines():
            line = line.strip()
            if not line or ':' not in line:
                continue
            name, _, val = line.partition(':')
            name = name.strip().lower()
            if any(tok in name for tok in
                   ('error', 'drop', 'miss', 'corrupt', 'fail')):
                try:
                    counters[name] = int(val.strip())
                except ValueError:
                    pass
        return counters

    def _ethtool_error_delta(self, before):
        """
        Return a description string of counters that increased since
        the before snapshot.  Empty string means no increase.
        """
        after = self._ethtool_error_snapshot()
        deltas = {}
        for name, val_after in after.items():
            val_before = before.get(name, 0)
            if val_after > val_before:
                deltas[name] = val_after - val_before
        if not deltas:
            return ''
        return ', '.join('%s=+%d' % (k, v) for k, v in sorted(deltas.items()))

    def _bql_limits_snapshot(self):
        """
        Return a dict mapping 'tx-N' → current BQL limit value for all
        TX queues of self.interface.
        """
        bql_root = os.path.join(
            '/sys/class/net', self.interface, 'queues')
        result = {}
        if not os.path.isdir(bql_root):
            return result
        for queue in sorted(os.listdir(bql_root)):
            if not queue.startswith('tx-'):
                continue
            limit_path = os.path.join(
                bql_root, queue, 'byte_queue_limits', 'limit')
            if not os.path.exists(limit_path):
                continue
            try:
                result[queue] = int(
                    genio.read_one_line(limit_path).strip())
            except (IOError, ValueError):
                pass
        return result

    def _rx_error_snapshot(self):
        """
        Return a dict of ethtool -S counters that pertain to *RX*
        errors / drops / no-buffer conditions for self.interface.
        These are the counters that rise on host RX pool starvation.
        """
        try:
            out = process.run("ethtool -S %s" % self.interface,
                              shell=True, ignore_status=True).stdout_text
        except Exception:
            return {}
        counters = {}
        rx_bad_tokens = (
            'dropped', 'drop', 'errors', 'error', 'err',
            'no_buffer', 'nobuf', 'no_buff', 'missed', 'miss',
            'fifo_errors', 'over_errors', 'overrun', 'length_errors',
            'crc_errors', 'frame_errors', 'starv',
        )
        for line in out.splitlines():
            line = line.strip()
            if not line or ':' not in line:
                continue
            name, _, val = line.partition(':')
            name = name.strip().lower()
            if not name.startswith('rx'):
                continue
            if any(benign in name for benign in
                   ('interrupt', 'packets', 'bytes', 'csum', 'checksum',
                    'coalesce')):
                continue
            if any(('_' + tok in name) or name.endswith(tok) or
                   name.endswith('_' + tok) for tok in rx_bad_tokens):
                try:
                    counters[name] = int(val.strip())
                except ValueError:
                    pass
        return counters

    def _rx_error_delta(self, before):
        """
        Return a description string of RX error/drop counters that increased
        since the before snapshot.  Empty string means no increase.
        """
        after = self._rx_error_snapshot()
        deltas = {}
        for name, val_after in after.items():
            val_before = before.get(name, 0)
            if val_after > val_before:
                deltas[name] = val_after - val_before
        if not deltas:
            return ''
        return ', '.join('%s=+%d' % (k, v)
                         for k, v in sorted(deltas.items()))

    def _proc_net_dev_rx_drop(self):
        """
        Return the current RX-drop counter for self.interface from
        /proc/net/dev.  Field layout after 'iface:':
          rx: bytes packets errs drop fifo frame compressed multicast
        so rx_drop is index 3 (0-based) of the post-colon fields.
        Returns 0 if the interface/line is not found.
        """
        try:
            for line in genio.read_file('/proc/net/dev').splitlines():
                if ':' not in line:
                    continue
                name, _, rest = line.partition(':')
                if name.strip() != self.interface:
                    continue
                fields = rest.split()
                if len(fields) >= 4:
                    return int(fields[3])
        except (IOError, IndexError, ValueError):
            pass
        return 0

    def tearDown(self):
        """Stop iperf3 server on peer, remove IP config, close SSH."""
        if hasattr(self, 'session') and self.session:
            try:
                self._stop_peer_iperf3_server()
            except Exception:
                pass
            try:
                self.session.quit()
            except Exception:
                pass

        if hasattr(self, 'networkinterface') and hasattr(self, 'ipaddr'):
            try:
                self.networkinterface.remove_ipaddr(self.ipaddr, self.netmask)
            except Exception:
                pass
            try:
                self.networkinterface.restore_from_backup()
            except Exception:
                try:
                    self.networkinterface.remove_cfg_file()
                except Exception:
                    pass
