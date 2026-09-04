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
# Author: Samir Mulani <samir@linux.ibm.com>

import glob
import os
import shutil

from avocado import Test
from avocado.utils import cpu, process
from avocado.utils.software_manager.manager import SoftwareManager


class CpuidleWakeupTest(Test):
    """
    Compile cpuidle_wakeup.c and run it across a sweep of sleep intervals
    using pipe-based wakeup mode.  One plain-text log file per interval is
    written under cpuidle_wakeup_logs/.

    :avocado: tags=cpu,cpuidle,power,wakeup_latency
    """

    def setUp(self):
        """
        Install gcc/make, compile the bundled C source, validate cpuidle
        sysfs, and read test parameters from YAML.
        """
        smm = SoftwareManager()
        for pkg in ["gcc", "make"]:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel(
                    "'%s' is required but could not be installed" % pkg)

        src_name = "cpuidle_wakeup.c"
        src_path = self.get_data(src_name)
        if src_path is None:
            self.cancel(
                "Source file '%s' not found in the .data directory" % src_name
            )

        dst_src = os.path.join(self.workdir, src_name)
        shutil.copy(src_path, dst_src)

        self.binary = os.path.join(self.workdir, "cpuidle-state-test")
        ret = process.run(
            "gcc -O2 -pthread -o %s %s" % (self.binary, dst_src),
            ignore_status=True,
        )
        if ret.exit_status != 0:
            self.cancel(
                "Compilation failed:\n%s\n%s"
                % (ret.stdout_text, ret.stderr_text)
            )
        self.log.info("Binary compiled: %s", self.binary)

        cpuidle_root = "/sys/devices/system/cpu/cpu0/cpuidle"
        if not os.path.isdir(cpuidle_root):
            self.cancel(
                "cpuidle sysfs not found at '%s'; "
                "cpuidle may be disabled on this kernel" % cpuidle_root
            )
        state_dirs = glob.glob(os.path.join(cpuidle_root, "state*"))
        self.nr_idle_states = len(state_dirs)
        self.log.info("Detected %d cpuidle state(s) on cpu0",
                      self.nr_idle_states)

        self.wakee_cpu = self.params.get("wakee_cpu", default=10)
        self.waker_cpu = self.params.get("waker_cpu", default=40)
        self.test_duration = self.params.get("test_duration_sec", default=10)
        raw = self.params.get(
            "sleep_intervals_us",
            default="3,5,10,20,30,40,50,60,70,80,90",
        )
        self.sleep_intervals = [int(x.strip()) for x in str(raw).split(",")]

        online_cpus = cpu.cpu_online_list()
        for c in [self.wakee_cpu, self.waker_cpu]:
            if c not in online_cpus:
                self.cancel(
                    "CPU %d is not online (online list: %s)" % (c, online_cpus)
                )

        self.log.info(
            "Config — wakee_cpu=%d  waker_cpu=%d  duration=%ds  intervals=%s",
            self.wakee_cpu, self.waker_cpu,
            self.test_duration, self.sleep_intervals,
        )

        self.result_dir = os.path.join(self.logdir, "cpuidle_wakeup_logs")
        os.makedirs(self.result_dir, exist_ok=True)
        self.log.info("Run logs dir: %s", self.result_dir)

    def test(self):
        """
        Run cpuidle-state-test for every sleep interval (pipe-based wakeup).
        Each run is checked for exit status, wakeup count, and above/below
        idle residency threshold (default 8%).  Raw output is dumped to a
        per-interval .log file.  A failed-commands summary is printed at
        the end.
        """
        ABOVE_BELOW_THRESHOLD_PCT = self.params.get(
            "above_below_threshold_pct", default=8.0
        )

        any_failure = False
        failed_cmds = []

        for interval_us in self.sleep_intervals:

            cmd = (
                "%s -w %d -e %d -d %d -s %d -p"
                % (self.binary, self.wakee_cpu, self.waker_cpu,
                   self.test_duration, interval_us)
            )
            self.log.info("=" * 60)
            self.log.info("Running [interval=%d us]: %s", interval_us, cmd)
            self.log.info("=" * 60)

            result = process.run(
                cmd, ignore_status=True,
                timeout=self.test_duration + 30
            )

            stdout = result.stdout_text.strip()
            stderr = result.stderr_text.strip()

            if result.exit_status != 0:
                reason = "exit status %d" % result.exit_status
                self.log.error("FAIL [interval=%d us]: %s",
                               interval_us, reason)
                self._dump_run_log(interval_us, cmd, stdout, stderr,
                                   result.exit_status, fail_reason=reason)
                failed_cmds.append((cmd, reason))
                any_failure = True
                continue

            wakeup_count = self._parse_wakeup_count(stdout)
            if wakeup_count == 0:
                reason = "wakeup_count is 0"
                self.log.error("FAIL [interval=%d us]: %s",
                               interval_us, reason)
                self._dump_run_log(interval_us, cmd, stdout, stderr,
                                   result.exit_status, fail_reason=reason)
                failed_cmds.append((cmd, reason))
                any_failure = True
                continue

            above_pct, below_pct = self._parse_above_below(stdout)
            ab_fail_reason = None

            if above_pct > ABOVE_BELOW_THRESHOLD_PCT:
                ab_fail_reason = (
                    "Total Above %.2f%% exceeds threshold %.2f%%"
                    % (above_pct, ABOVE_BELOW_THRESHOLD_PCT)
                )
            elif below_pct > ABOVE_BELOW_THRESHOLD_PCT:
                ab_fail_reason = (
                    "Total Below %.2f%% exceeds threshold %.2f%%"
                    % (below_pct, ABOVE_BELOW_THRESHOLD_PCT)
                )

            if ab_fail_reason:
                self.log.error(
                    "FAIL [interval=%d us]: %s", interval_us, ab_fail_reason
                )
                self._dump_run_log(interval_us, cmd, stdout, stderr,
                                   result.exit_status,
                                   fail_reason=ab_fail_reason)
                failed_cmds.append((cmd, ab_fail_reason))
                any_failure = True
                continue

            self._dump_run_log(interval_us, cmd, stdout, stderr,
                               result.exit_status)
            self.log.info(
                "PASS [interval=%d us] — wakeups=%d  "
                "above=%.2f%%  below=%.2f%%",
                interval_us, wakeup_count, above_pct, below_pct,
            )

        self.log.info("Logs written to: %s", self.result_dir)

        if failed_cmds:
            self.log.error("")
            self.log.error("=" * 60)
            self.log.error("FAILED COMMANDS SUMMARY (%d / %d runs failed):",
                           len(failed_cmds), len(self.sleep_intervals))
            self.log.error("=" * 60)
            for i, (fc, reason) in enumerate(failed_cmds, 1):
                self.log.error("  [%d] cmd   : %s", i, fc)
                self.log.error("       reason: %s", reason)
            self.log.error("=" * 60)

        if any_failure:
            self.fail(
                "%d of %d runs failed. See logs in: %s"
                % (len(failed_cmds), len(self.sleep_intervals),
                   self.result_dir)
            )

    def _dump_run_log(self, interval_us, cmd, stdout, stderr,
                      exit_status, fail_reason=None):
        """
        Write raw command output to cpuidle_wakeup_logs/run_<N>us.log.
        Failed runs are prefixed with STATUS: FAIL and the failure reason.
        """
        log_path = os.path.join(self.result_dir, "run_%dus.log" % interval_us)
        with open(log_path, "w") as fh:
            if fail_reason:
                fh.write("STATUS      : FAIL\n")
                fh.write("FAIL REASON : %s\n" % fail_reason)
            else:
                fh.write("STATUS      : PASS\n")
            fh.write("cmd         : %s\n" % cmd)
            fh.write("exit_status : %d\n" % exit_status)
            fh.write("\n")
            fh.write(stdout)
            if stderr:
                fh.write("\n")
                fh.write(stderr)
            fh.write("\n")
        self.log.info("Log written: %s", log_path)

    @staticmethod
    def _parse_wakeup_count(output):
        """
        Parse ``Wakee wakeups: <N>`` from binary stdout.
        Returns 0 when the line is absent (timer-mode omits it).
        """
        for line in output.splitlines():
            if "Wakee wakeups:" in line:
                try:
                    return int(
                        line.split("Wakee wakeups:")[1].split(",")[0].strip()
                    )
                except (IndexError, ValueError):
                    pass
        return 0

    @staticmethod
    def _parse_metric(output, keyword):
        """
        Parse a float value (µs) from lines matching *keyword*.
        Handles lines of the form ``<label> = 5.123 us``.
        Returns 0.0 when not found.
        """
        kw_lower = keyword.lower()
        for line in output.splitlines():
            if kw_lower in line.lower():
                parts = line.split("=")
                if len(parts) >= 2:
                    try:
                        return float(parts[-1].strip().split()[0])
                    except (IndexError, ValueError):
                        pass
        return 0.0

    @staticmethod
    def _parse_above_below(output):
        """
        Parse ``Total Above: N (X.XX% …)`` / ``Total Below: N (X.XX% …)``.
        Returns (above_pct, below_pct) as floats.
        """
        above_pct = below_pct = 0.0
        for line in output.splitlines():
            lo = line.lower()
            if "total above:" in lo:
                try:
                    above_pct = float(line.split("(")[1].split("%")[0].strip())
                except (IndexError, ValueError):
                    pass
            elif "total below:" in lo:
                try:
                    below_pct = float(line.split("(")[1].split("%")[0].strip())
                except (IndexError, ValueError):
                    pass
        return above_pct, below_pct
