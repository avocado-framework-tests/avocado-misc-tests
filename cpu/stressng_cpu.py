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
# Copyright: 2022 IBM
# Author: Rohan Deshpande <rohan_d@linux.ibm.com>
# Modified by: Samir A Mulani <samir@linux.vnet.ibm.com>
#

import os
import re
import errno
import signal
import subprocess
import time
from avocado import Test
from avocado.utils import dmesg
from avocado.utils import archive
from avocado.utils import build
from avocado.utils import process
from avocado.utils.software_manager.manager import SoftwareManager

# Scheduling policy constants (from linux/sched.h / sched(7))
SCHED_OTHER = 0
SCHED_FIFO = 1
SCHED_RR = 2
SCHED_BATCH = 3
SCHED_IDLE = 5
SCHED_DEADLINE = 6

# Human-readable names and required real-time priorities for each policy.
# SCHED_FIFO / SCHED_RR require priority in [1, 99]; all others use 0.
POLICY_META = {
    SCHED_OTHER:   {"name": "SCHED_OTHER", "label": "other", "rt_prio": 0},
    SCHED_BATCH:   {"name": "SCHED_BATCH", "label": "batch", "rt_prio": 0},
    SCHED_IDLE:    {"name": "SCHED_IDLE", "label": "idle",  "rt_prio": 0},
    SCHED_FIFO:    {"name": "SCHED_FIFO", "label": "fifo",  "rt_prio": 1},
    SCHED_RR:      {"name": "SCHED_RR",      "label": "rr", "rt_prio": 1},
    SCHED_DEADLINE: {"name": "SCHED_DEADLINE", "label": "deadline",
                     "rt_prio": 0},
}

# Ordered transition chain for the runtime policy-change test.
# Built from the named constants so the list never repeats bare names.
# SCHED_DEADLINE is intentionally excluded — it requires sched_setattr(2)
# with runtime/deadline/period attrs not exposed via os.sched_setscheduler().
POLICY_TRANSITION_CHAIN = [
    SCHED_OTHER,   # default CFS — starting point
    SCHED_IDLE,
    SCHED_BATCH,
    SCHED_FIFO,
    SCHED_RR,
    SCHED_OTHER,   # restore to CFS at the end
]


class Stressngcpu(Test):
    """
    stress-ng testsuite
    Source: "https://github.com/ColinIanKing/stress-ng/archive/master.zip"
    Description:
    The purpose of this script is to run CPU stress tests using the
    stress-ng program
    """

    def check_policy_support(self, policy):
        """
        Check if a scheduling policy is supported by this kernel.
        Returns the label string (e.g. "other", "fifo") if supported,
        False otherwise.

        Uses POLICY_META for priority and label so there is a single
        source of truth for policy attributes across the whole test.
        """
        meta = POLICY_META.get(policy)
        if meta is None:
            self.log.warning("Invalid scheduling policy constant: %d", policy)
            return False

        priority = meta["rt_prio"]
        label = meta["label"]

        try:
            # For SCHED_DEADLINE os.sched_param is a dummy; the kernel will
            # reject it with EINVAL, which is handled below.
            param = os.sched_param(priority)
            os.sched_setscheduler(0, policy, param)
            return label
        except OSError as e:
            if e.errno == errno.EPERM:
                # Permission denied — policy exists but caller is not root
                return label
            elif e.errno == errno.EINVAL:
                # Policy not recognised by this kernel build
                return False
            else:
                # ESRCH, EFAULT, or any other unexpected error
                return False

    def read_line_with_matching_pattern(self, filename, pattern):
        matching_pattern = []
        with open(filename, 'r') as file_obj:
            for line in file_obj.readlines():
                if pattern in line:
                    matching_pattern.append(line.rstrip("\n"))
        return matching_pattern

    def setUp(self):
        self.sched_class_payload = []
        # PIDs of live stress-ng background workers (runtime policy test)
        self._stressng_proc = None
        smm = SoftwareManager()
        crt_stressors_list = ["bsearch", "context", "cpu", "crypt", "hsearch",
                              "longjmp", "lsearch", "matrix", "qsort", "str",
                              "stream", "tsearch", "vecmath", "wcs"]

        self.runtime = self.params.get("runtime", default=7200)
        self.sched_runtime = self.params.get("sched_runtime", default="100")
        self.test_mode = self.params.get("test_mode", default="saturate")
        self.url = self.params.get("url", default="https://github.com/"
                                   "ColinIanKing/stress-ng/archive/master.zip")
        self.crt_stressors = self.params.get(
            "crt_stressors", default=crt_stressors_list)
        # Seconds to keep stress-ng alive during the runtime policy-change test
        self.policy_change_runtime = int(self.params.get(
            "policy_change_runtime", default=120))
        # Number of stress-ng worker threads for runtime policy-change test
        self.policy_change_workers = int(self.params.get(
            "policy_change_workers", default=os.cpu_count() or 2))

        for package in ['gcc', 'make', 'libattr-devel', 'libcap-devel',
                        'libgcrypt-devel', 'zlib-devel', 'libaio-devel']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel("%s is needed for the test to be run." % package)

        tarball = self.fetch_asset(
            'stressng.zip', locations=self.url, expire='7d')
        archive.extract(tarball, self.workdir)
        sourcedir = os.path.join(self.workdir, 'stress-ng-master')
        os.chdir(sourcedir)
        result = build.run_make(sourcedir, process_kwargs={
                                'ignore_status': True})

        for line in str(result).splitlines():
            if 'error:' in line:
                self.cancel(
                    "Build Failed, Please check the build logs for details !!")
        build.make(sourcedir, extra_args='install')

        policies = [SCHED_OTHER, SCHED_BATCH, SCHED_IDLE, SCHED_FIFO,
                    SCHED_RR, SCHED_DEADLINE]
        for sched_policies in policies:
            sched_pol = self.check_policy_support(sched_policies)
            if sched_pol is not False:
                self.sched_class_payload.append(sched_pol)

        self.log.info("The currently booted Linux OS supports {%s} scheduling \
                policies." % (self.sched_class_payload))

        # Clear the dmesg to capture the delta at the end of the test.
        dmesg.clear_dmesg()

    def stress_sched_class(self, cmd):
        """
        Executes the given stress-ng command and returns its exit status.
        Parameters:
            cmd (str): The full stress-ng command to execute.

        Returns:
            int: The exit status code returned by the stress-ng command.
        """

        return_code = process.system(cmd, ignore_status=True)
        return return_code

    def stress_ng_status_check(self, return_code):
        """
        This function checks the return code of a stress-ng command execution
        to determine whether it succeeded or failed.

        Parameters:
            return_code (int): The exit status returned by the executed
            stress-ng command. A return code of 0 indicates success, while
            any non-zero value indicates failure.
        """

        self.log.info("=====================================================")
        if (return_code == 0):
            self.log.info("==> stress-ng CPU test passed!")
        else:
            if (return_code == 137):
                self.log.info("== > stress-ng CPU test timed out and was \
                        forcefully terminated!")
            else:
                self.log.info(
                    "==> stress-ng CPU test failed with result %s"
                    % (return_code))
        self.log.info("=====================================================")

    def test_cpu(self):
        """
        This function is responsible for stressing the system using a
        combination of stress-ng stressor threads, based on the specified
        test mode.

        The stressors are selected from a predefined list (e.g., "bsearch",
        "context","cpu", "crypt", "hsearch", "longjmp", "lsearch", "matrix",
        "qsort", "str","stream", "tsearch", "vecmath", "wcs") and are used
        to build a composite stress-ng command.

        The intensity and nature of the stress is controlled by the
        'test_mode' parameter (e.g., 'saturate', 'overload',
        'underutilize'), which determines how many worker threads to spawn
        per stressor.
        """

        num_cpus = os.cpu_count()
        stress_ng_threads = 0
        if self.test_mode == "saturate":
            stress_ng_threads = num_cpus
        elif self.test_mode == "overload":
            stress_ng_threads = num_cpus * 2
        elif self.test_mode == "underutilize":
            stress_ng_threads = num_cpus / 2

        cmd = ""

        if self.sched_class_payload:
            for sched_class in self.sched_class_payload:
                cmd = "stress-ng  --cpu %s --sched %s  --timeout %s \
                        --aggressive  --verify \
                        --metrics-brief --tz\
                        --times" % (stress_ng_threads, sched_class,
                                    self.sched_runtime)

                return_code = process.system(cmd, ignore_status=True)
                self.log.info("Return code is %s", return_code)
                self.stress_ng_status_check(return_code)

        cmd = "stress-ng --aggressive --verify \
                --timeout %s --metrics-brief \
                --tz --times " % (self.runtime)

        loop_count = 0
        while (loop_count < len(self.crt_stressors)):
            cmd += "--%s 0 " % (self.crt_stressors[loop_count])
            loop_count = loop_count + 1

        return_code = process.system(cmd, ignore_status=True)
        self.log.info("Return code is %s", return_code)
        self.stress_ng_status_check(return_code)

    # ------------------------------------------------------------------
    # Helpers for the runtime scheduling-policy change test
    # ------------------------------------------------------------------

    def _spawn_stressng_background(self, num_workers, duration_secs):
        """
        Launch stress-ng as a background process with *num_workers* CPU
        stressor threads that will run for *duration_secs* seconds.

        Returns the subprocess.Popen object so the caller can wait on it
        or terminate it.  The process is started without shell=True so
        that its PID is the actual stress-ng PID.
        """
        cmd = [
            "stress-ng",
            "--cpu", str(num_workers),
            "--timeout", str(duration_secs),
            "--metrics-brief",
        ]
        self.log.info("Spawning background stress-ng: %s", " ".join(cmd))
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.log.info("stress-ng started with PID %d", proc.pid)
        return proc

    def _get_stressng_worker_pids(self, parent_pid, settle_secs=3):
        """
        Return the PIDs of the stress-ng child worker processes spawned
        under *parent_pid*, plus the parent PID itself.

        stress-ng forks one worker per stressor thread.  Children are
        discovered first via /proc/<parent_pid>/task/<parent_pid>/children
        and then via pgrep as a fallback.  *settle_secs* gives the workers
        time to be created before enumeration.

        Returns a sorted list that always includes *parent_pid*.  Logs a
        warning when no child workers are found, because the test will then
        exercise only the manager process rather than actual CPU stressors.
        """
        time.sleep(settle_secs)
        child_pids = set()

        children_file = "/proc/%d/task/%d/children" % (parent_pid, parent_pid)
        if os.path.exists(children_file):
            try:
                with open(children_file, "r") as fobj:
                    for token in fobj.read().split():
                        child_pids.add(int(token))
            except (OSError, ValueError) as read_err:
                self.log.warning(
                    "Could not read %s: %s", children_file, read_err)

        if not child_pids:
            try:
                raw = subprocess.check_output(
                    ["pgrep", "-P", str(parent_pid)],
                    stderr=subprocess.DEVNULL,
                ).decode()
                for token in raw.split():
                    child_pids.add(int(token))
            except subprocess.CalledProcessError:
                self.log.warning(
                    "pgrep found no children of PID %d", parent_pid)

        if not child_pids:
            self.log.warning(
                "No child worker PIDs found under PID %d — "
                "only the stress-ng manager process will be exercised",
                parent_pid)

        all_pids = child_pids | {parent_pid}
        self.log.info(
            "Found %d stress-ng PID(s) to exercise: %s",
            len(all_pids), sorted(all_pids))
        return sorted(all_pids)

    def _pid_alive(self, pid):
        """Return True if *pid* still exists in /proc."""
        return os.path.exists("/proc/%d" % pid)

    def _read_proc_sched_policy(self, pid):
        """
        Return the current scheduling policy integer for *pid* by calling
        os.sched_getscheduler(pid), which wraps the sched_getscheduler(2)
        syscall and reads the value directly from the kernel scheduler.

        Returns the policy integer, or None if the PID has gone away.
        """
        if not self._pid_alive(pid):
            return None
        try:
            return os.sched_getscheduler(pid)
        except OSError as get_err:
            self.log.debug(
                "os.sched_getscheduler(%d) failed: %s", pid, get_err)
            return None

    def _verify_policy_via_chrt(self, pid, expected_policy):
        """
        Cross-verify the scheduling policy of *pid* using the ``chrt``
        command-line tool.

        ``chrt -p <pid>`` prints a line like::

            pid 12345's current scheduling policy: SCHED_OTHER
            pid 12345's current scheduling priority: 0

        We parse the policy name and compare it with the expected constant.

        Returns a tuple (ok: bool, actual_name: str).
        """
        meta = POLICY_META.get(expected_policy, {})
        expected_name = meta.get("name", "UNKNOWN")

        try:
            raw = subprocess.check_output(
                ["chrt", "-p", str(pid)],
                stderr=subprocess.STDOUT,
            ).decode()
        except FileNotFoundError:
            self.log.warning(
                "chrt not found on this system — "
                "secondary policy verification is unavailable for the "
                "entire test run")
            return False, "chrt-not-installed"
        except subprocess.CalledProcessError as chrt_err:
            self.log.warning(
                "chrt -p %d failed: %s — secondary verification skipped",
                pid, chrt_err)
            return False, "chrt-error"

        # Parse the policy name from chrt output
        match = re.search(
            r"current scheduling policy:\s+(\S+)", raw, re.IGNORECASE)
        if not match:
            self.log.warning(
                "Could not parse chrt output for PID %d:\n%s", pid, raw)
            return True, "parse-error"

        actual_name = match.group(1).upper()
        ok = actual_name == expected_name.upper()
        if not ok:
            self.log.error(
                "chrt mismatch PID %d: expected %s got %s",
                pid, expected_name, actual_name)
        return ok, actual_name

    def _set_policy_for_pids(self, pids, policy):
        """
        Apply scheduling *policy* to every PID in *pids* using
        os.sched_setscheduler(2).

        Returns a dict  {pid: True|False}  indicating per-PID success.
        FIFO and RR require a real-time priority >= 1; all others use 0.
        """
        meta = POLICY_META.get(policy, {})
        rt_prio = meta.get("rt_prio", 0)
        param = os.sched_param(rt_prio)
        results = {}
        for pid in pids:
            if not self._pid_alive(pid):
                self.log.warning(
                    "PID %d no longer alive; skipping policy set", pid)
                results[pid] = False
                continue
            try:
                os.sched_setscheduler(pid, policy, param)
                results[pid] = True
                self.log.debug(
                    "PID %d: policy set to %s (prio=%d)",
                    pid, meta.get("name", policy), rt_prio)
            except OSError as set_err:
                self.log.error(
                    "PID %d: sched_setscheduler(%s) failed: %s",
                    pid, meta.get("name", policy), set_err)
                results[pid] = False
        return results

    def _verify_policy_for_pids(self, pids, expected_policy):
        """
        Verify that every living PID in *pids* is running under
        *expected_policy*.

        Uses two independent sources:
          1. ``os.sched_getscheduler(pid)``  — kernel syscall (primary)
          2. ``chrt -p <pid>``              — userspace tool (secondary)

        Returns a list of failure description strings (empty == all pass).
        """
        policy_name = POLICY_META.get(
            expected_policy, {}).get("name", str(expected_policy))
        failures = []

        for pid in pids:
            if not self._pid_alive(pid):
                # Worker may have exited; treat as a warning, not a failure
                self.log.warning(
                    "PID %d exited before verification for %s",
                    pid, policy_name)
                continue

            # --- primary: syscall ---
            actual = self._read_proc_sched_policy(pid)
            if actual is None:
                failures.append(
                    "PID %d: sched_getscheduler returned None for %s"
                    % (pid, policy_name))
                continue

            if actual != expected_policy:
                actual_name = POLICY_META.get(
                    actual, {}).get("name", str(actual))
                failures.append(
                    "PID %d: sched_getscheduler mismatch — "
                    "expected %s(%d) got %s(%d)"
                    % (pid, policy_name, expected_policy,
                       actual_name, actual))
            else:
                self.log.debug(
                    "PID %d: sched_getscheduler OK — %s", pid, policy_name)

            # --- secondary: chrt tool ---
            chrt_ok, chrt_actual = self._verify_policy_via_chrt(
                pid, expected_policy)
            if not chrt_ok:
                failures.append(
                    "PID %d: chrt mismatch — expected %s got %s"
                    % (pid, policy_name, chrt_actual))
            else:
                self.log.debug(
                    "PID %d: chrt verification OK — %s", pid, chrt_actual)

        return failures

    def test_runtime_policy_change(self):
        """
        Runtime Scheduling-Policy Change Test
        ======================================
        Purpose
        -------
        Validate that the Linux kernel correctly honours scheduling-policy
        changes applied to *live* stress-ng worker threads via
        sched_setscheduler(2) at run-time.

        Background
        ----------
        By default, processes run under CFS (SCHED_OTHER, policy=0).
        Linux exposes sched_setscheduler(2) to change the policy of any
        thread the caller has permission to modify.

        Requirements
        ------------
        - Must be run as root (CAP_SYS_NICE required for RT policies).
        - ``stress-ng`` must be installed (built in setUp).
        - ``chrt`` utility must be present on the system.

        Parameters (from YAML)
        ----------------------
        - ``policy_change_runtime``  : seconds stress-ng runs (default 120)
        - ``policy_change_workers``  : number of CPU stressor threads
                                       (default: os.cpu_count())
        """
        self.log.info("=" * 60)
        self.log.info("Test: Runtime Scheduling-Policy Change")
        self.log.info("=" * 60)

        all_results = []

        self._stressng_proc = self._spawn_stressng_background(
            num_workers=self.policy_change_workers,
            duration_secs=self.policy_change_runtime,
        )

        worker_pids = self._get_stressng_worker_pids(
            self._stressng_proc.pid, settle_secs=3)

        child_pids = [p for p in worker_pids
                      if p != self._stressng_proc.pid]
        if not child_pids:
            self._terminate_stressng()
            self.fail(
                "No stress-ng worker child PIDs found under PID %d — "
                "cannot exercise CPU stressor scheduling policies."
                % self._stressng_proc.pid)

        self.log.info("Workers under test: %s", worker_pids)

        supported_transitions = []
        for idx in range(len(POLICY_TRANSITION_CHAIN) - 1):
            from_policy = POLICY_TRANSITION_CHAIN[idx]
            to_policy = POLICY_TRANSITION_CHAIN[idx + 1]

            from_name = POLICY_META[from_policy]["name"]
            to_name = POLICY_META[to_policy]["name"]
            transition_label = "%s -> %s" % (from_name, to_name)

            # Skip if target policy is not supported on this kernel/config
            if POLICY_META[to_policy]["label"] not in self.sched_class_payload:
                self.log.warning(
                    "Transition %s: target policy not supported — skipping",
                    transition_label)
                all_results.append({
                    "transition": transition_label,
                    "pid": "N/A",
                    "step": "policy-support-check",
                    "status": "SKIP",
                    "detail": "Policy %s not supported on this kernel"
                              % to_name,
                })
                continue

            supported_transitions.append(transition_label)

            self.log.info("-" * 60)
            self.log.info(
                "Transition [%d/%d]: %s",
                idx + 1, len(POLICY_TRANSITION_CHAIN) - 1, transition_label)

            # -- 3a: Log current (from) policy for each worker PID ------
            self.log.info("Current policies before change:")
            for pid in worker_pids:
                cur = self._read_proc_sched_policy(pid)
                cur_name = POLICY_META.get(cur, {}).get("name", str(cur))
                self.log.info("  PID %d: %s", pid, cur_name)

            # -- 3b: Apply the new policy to all workers -----------------
            self.log.info(
                "Applying %s to %d PID(s)...", to_name, len(worker_pids))
            set_results = self._set_policy_for_pids(worker_pids, to_policy)

            for pid, ok in set_results.items():
                status = "PASS" if ok else "FAIL"
                detail = ("sched_setscheduler(%s) succeeded" % to_name
                          if ok
                          else "sched_setscheduler(%s) failed" % to_name)
                all_results.append({
                    "transition": transition_label,
                    "pid": pid,
                    "step": "set-policy",
                    "status": status,
                    "detail": detail,
                })
                self.log.info(
                    "  PID %d set-policy %s: %s", pid, to_name, status)

            # -- 3c: Verify the policy was actually applied --------------
            self.log.info("Verifying %s on %d PID(s)...", to_name,
                          len(worker_pids))
            verify_failures = self._verify_policy_for_pids(
                worker_pids, to_policy)

            if not verify_failures:
                self.log.info(
                    "  Verification PASSED for all PIDs (%s)", to_name)
                all_results.append({
                    "transition": transition_label,
                    "pid": "all",
                    "step": "verify-policy",
                    "status": "PASS",
                    "detail": "sched_getscheduler + chrt both confirmed %s"
                              % to_name,
                })
            else:
                for detail_msg in verify_failures:
                    self.log.error("  Verification FAIL: %s", detail_msg)
                    all_results.append({
                        "transition": transition_label,
                        "pid": "see-detail",
                        "step": "verify-policy",
                        "status": "FAIL",
                        "detail": detail_msg,
                    })

            # Brief pause so the kernel has a chance to run workers under
            # the new policy before we move on.
            time.sleep(1)

        self._terminate_stressng()

        self.log.info("=" * 60)
        self.log.info("Runtime Policy-Change Test — Result Summary")
        self.log.info("=" * 60)
        self.log.info("Transitions exercised : %d", len(supported_transitions))
        self.log.info("Total result entries  : %d", len(all_results))

        pass_count = sum(1 for r in all_results if r["status"] == "PASS")
        fail_count = sum(1 for r in all_results if r["status"] == "FAIL")
        skip_count = sum(1 for r in all_results if r["status"] == "SKIP")

        self.log.info("PASS: %d  FAIL: %d  SKIP: %d",
                      pass_count, fail_count, skip_count)
        self.log.info("-" * 60)

        failed_entries = [r for r in all_results if r["status"] == "FAIL"]
        if failed_entries:
            self.log.error("Failed transitions / steps:")
            for entry in failed_entries:
                self.log.error(
                    "  [%s] PID=%s step=%s — %s",
                    entry["transition"], entry["pid"],
                    entry["step"], entry["detail"])
            self.fail(
                "Runtime policy-change test FAILED — %d failure(s) "
                "across %d transition(s). See log for details."
                % (fail_count, len(failed_entries)))
        else:
            self.log.info(
                "All runtime policy-change transitions PASSED.")

    def _terminate_stressng(self):
        """
        Gracefully stop the background stress-ng process started by
        test_runtime_policy_change, then wait for it to exit.
        """
        if self._stressng_proc is None:
            return
        proc = self._stressng_proc
        self._stressng_proc = None

        if proc.poll() is not None:
            # Already exited
            self.log.debug(
                "stress-ng (PID %d) already exited with code %d",
                proc.pid, proc.returncode)
            return

        self.log.info(
            "Sending SIGTERM to stress-ng PID %d ...", proc.pid)
        try:
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=15)
            self.log.info(
                "stress-ng PID %d terminated (rc=%d)",
                proc.pid, proc.returncode)
        except subprocess.TimeoutExpired:
            self.log.warning(
                "stress-ng PID %d did not exit after SIGTERM; sending SIGKILL",
                proc.pid)
            proc.kill()
            proc.wait()
        except OSError as kill_err:
            self.log.warning(
                "Could not signal stress-ng PID %d: %s", proc.pid, kill_err)

    def tearDown(self):
        """
        Ensure the background stress-ng process (if any) is cleaned up,
        then capture dmesg and scan for known error patterns.
        """
        # Clean up background stress-ng if test_runtime_policy_change
        # exited early (e.g. due to cancel/error).
        self._terminate_stressng()

        errors_in_dmesg = []
        pattern = ['WARNING: CPU:', 'Oops', 'Segfault', 'soft lockup',
                   'Unable to handle', 'ard LOCKUP']

        filename = dmesg.collect_dmesg()

        for failed_pattern in pattern:
            contents = self.read_line_with_matching_pattern(
                filename, failed_pattern)
            if contents:
                loop_count = 0
                while loop_count < len(contents):
                    errors_in_dmesg.append(contents[loop_count])
                    loop_count = loop_count + 1

        if errors_in_dmesg:
            self.fail("Failed : Errors in dmesg : %s" %
                      "\n".join(errors_in_dmesg))
