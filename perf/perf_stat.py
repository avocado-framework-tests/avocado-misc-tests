#!/usr/bin/env python
#
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
# Copyright: 2025 IBM
# Author: Tejas Manhas <Tejas.Manhas1@ibm.com>
import re
import os
from avocado import Test
from avocado.utils import process, distro, build
from avocado.utils.software_manager.manager import SoftwareManager


class PerfStatOptions(Test):
    """
    Test perf stat options: compare --help options vs kernel source.
    Run only options present in help but missing from source.
    """

    def setUp(self):
        """
        Checks for dependencies and packages and Compiles
        final stat options options that are not used to be run
        """
        self.log.info("Setting up PerfStatOptions test...")

        # Check dependencies for RHEL/SLES/upstream
        self.detected_distro = distro.detect()
        smg = SoftwareManager()
        packages = ["perf"]
        for pkg in packages:
            if not smg.check_installed(pkg):
                if not smg.install(pkg):
                    self.cancel(f"{pkg} is required for this test")

        if self.detected_distro.name in [
                'rhel', 'centos', 'fedora', 'rocky', 'almalinux']:
            src_name = 'kernel'
            if self.detected_distro.name == 'rhel' and int(
                    self.detected_distro.version) >= 9:
                pass
            self.buldir = smg.get_source(
                src_name, self.workdir, build_option='-bp')
            self.buldir = os.path.join(self.buldir, os.listdir(self.buldir)[0])

        elif 'SuSE' in self.detected_distro.name:
            if not smg.check_installed(
                    "kernel-source") and not smg.install("kernel-source"):
                self.cancel("Failed to install kernel-source for this test.")
            if not os.path.exists("/usr/src/linux"):
                self.cancel("kernel source missing after install")
            self.buldir = "/usr/src/linux"

        elif self.detected_distro.name in ['ubuntu', 'debian']:
            self.buldir = smg.get_source('linux', self.workdir)

        else:
            self.cancel(
                "Distro %s not supported for kernel source install" %
                self.detected_distro.name)

        self.sourcedir = os.path.join(self.buldir, 'tools/perf')

        self.unknown_options = set()
        self.failed_options = {}

        # Get help options
        self.perf_options = self.get_help_options()
        self.log.info(f"Perf --help options: {self.perf_options}")

        # Get source options
        self.src_options = self.get_src_options()
        self.log.info(
            f"Source options from kernel perf tests: {self.src_options}")

        # Final options to test
        self.final_to_test = self.perf_options - self.src_options
        self.log.info(f"Final options to test: {self.final_to_test}")

    def get_help_options(self):
        """
        Extract valid -/-- options from `perf stat --help`.
        Ignores separators and non-option lines.
        """
        result = process.run("perf stat --help", ignore_status=True)
        out = result.stdout.decode()
        opts = set()
        for line in out.splitlines():
            stripped = line.lstrip()
            # Only parse actual option lines
            if not stripped.startswith('-'):
                continue

            # Tokenize line
            tokens = stripped.split()
            for token in tokens:
                # Capture only real options (skip commas and arguments)
                if re.match(r"^-{1,2}[A-Za-z0-9][A-Za-z0-9\-]*$", token):
                    clean_opt = self.sanitize_option(token)
                    if clean_opt:
                        opts.add(clean_opt)

        return opts

    def get_src_options(self):
        """
        Grep perf kernel tests for 'perf stat' and extract options.
        """
        if not os.path.exists(self.sourcedir):
            self.cancel(f"{self.sourcedir} not found, cannot build tools/perf")

        self.log.info(f"Building tools/perf in {self.sourcedir}")
        if build.make(self.sourcedir):
            self.fail("tools/perf build failed, check logs")
        self.log.info(f"Using Linux source directory: {self.sourcedir}")

        # Grep recursively for 'perf stat' in tools/perf/tests and tests/shell
        cmd = f"grep -r 'perf stat' {self.sourcedir}/tests || true"
        result = process.run(cmd, ignore_status=True, shell=True)
        out = result.stdout.decode()
        opts = set()
        for line in out.splitlines():
            matches = re.findall(r"-{1,2}[a-zA-Z0-9][\w-]*", line)
            for opt in matches:
                clean_opt = self.sanitize_option(opt)
                if clean_opt:
                    opts.add(clean_opt)
        return opts

    def run_and_check(self, opt):
        """
        Run a perf stat command for the given option, automatically generating
        required resources and minimal valid workloads to avoid errors.
        """

        # --- Step 1: Sanitize option ---
        opt = self.sanitize_option(opt)
        if not opt:
            return

        # --- Step 2: Skip unsupported infra (cgroup / bpf) ---
        if opt in [
            "--for-each-cgroup", "-b", "--bpf",
            "--bpf-attr-map", "--bpf-counters",
            "--bpf-prog", "--cgroup",
            "--smi-cost", "--interval-clear"
        ]:
            self.log.info(f"Skipping unsupported option: {opt}")
            self.unknown_options.add(opt)
            return

        # --- Step 3: Determine the resource / value for this option ---
        minimal = self.params.get(opt, default="")
        if minimal:
            self.log.info(
                f"For option {opt}, using minimal value from YAML: {minimal}")
        else:
            self.log.info(
                f"No YAML value found for option {opt}, skipping or using default")

        if opt in ["--metric-groups"]:
            cmd1 = "perf list metricgroup 2>/dev/null | grep -v '^$' | grep -v 'Metric Groups' | head -1"
            result1 = process.run(cmd1, ignore_status=True, shell=True)
            metric_group = result1.stdout.strip().decode()
            minimal = metric_group
            if not metric_group:
                self.cancel("No metric groups available on this system")
            self.log.info(f"Using metric group: {metric_group}")

        if opt in ["--topdown", "-T", "--transaction", "-t"]:
            grep_pat = "^TopdownL1" if opt in [
                "--topdown", "-T"] else "^transaction"
            group = process.run(
                f"perf list metricgroups 2>/dev/null | grep '{grep_pat}' | head -1",
                shell=True, ignore_status=True
            ).stdout.strip().decode()
            if not group:
                self.log.info(
                    f"{opt} metric groups not present on this system")
                self.unknown_options.add(opt)
                return
            else:
                minimal = group

        # Special handling for TID
        if opt in ["-t", "--tid"] or "--tid=" in opt:
            task_dir = "/proc/self/task"
            try:
                tids = os.listdir(task_dir)
                minimal = tids[0] if tids else str(os.getpid())
            except Exception:
                minimal = str(os.getpid())
        if opt in ["-p", "--pid"] or "--pid=" in opt:
            minimal = str(os.getpid())

        # --- Step 4: Generate required files / workloads ---
        # Input data for perf
        if opt in ["--input"]:
            process.run(
                f"mkdir -p events_dir && echo -e 'cycles,instructions' > {minimal}",
                shell=True)

        # Minimal post/pre scripts
        if opt in ["--post", "--pre"] and not os.path.exists(minimal):
            with open(minimal, "w") as f:
                f.write("#!/bin/bash\nsleep 0.1\n")
            os.chmod(minimal, 0o755)

        # --- Step 5: Construct command ---
        cmd_parts = ["perf", "stat"]

        # Flags that require a dependent event
        flags_with_deps = [
            "-b", "-u",
            "-s", "--metric-only",
            "--topdown", "--transaction", "-T"]
        if opt in flags_with_deps:
            cmd_parts.extend(["-e", self.params.get("-e")])

        # Options with "="
        if "=" in opt:
            base_opt = opt.split("=", 1)[0]
            cmd_parts.append(f"{base_opt}={minimal}")
        elif minimal:
            cmd_parts.extend([opt, minimal])
        else:
            cmd_parts.append(opt)

        # Default minimal workload
        workload = "sleep 5"
        cmd_parts.append(workload)

        cmd = " ".join(cmd_parts)

        # --- Step 6: Run command ---
        result = process.run(cmd, shell=True, ignore_status=True)
        ret = result.exit_status
        out = result.stdout_text
        err = result.stderr_text

        # --- Step 7: Handle results ---
        if ret != 0:
            if ret == 129 or "unknown option" in err.lower():
                self.log.info(f"Skipping option {opt}: unknown option")
                self.unknown_options.add(opt)
            else:
                self.failed_options[opt] = {
                    "exit_code": ret,
                    "stderr": err.strip(),
                }
                self.log.warning(f"Option {opt} failed with exit code {ret}")
        else:
            self.log.info(f"Option {opt} ran successfully")

        return ret, out, err

    def sanitize_option(self, opt):
        """
        Remove trailing non-alphanumeric chars commonly found in perf help/source.
        Keep leading '-' or '--'.
        """
        # opt = opt.strip()
        if not opt.startswith("-"):
            return None
        # remove trailing junk characters
        opt = re.sub(r"[),.:;/\[\]]+$", "", opt)
        # handle attached arguments:  -G/cgroup  -> -G,  --foo=bar  -> --foo,
        # -j64       -> -j
        opt = re.split(r"[=/]", opt, 1)[0]
        opt = re.sub(r"^(-[a-zA-Z])\d+$", r"\1", opt)
        # remove leading/trailing whitespace
        opt = opt.strip()
        if not opt:
            return None
        return opt

    def test_perf_stat_options(self):
        """
        Run all final options with minimal values where required.
        """

        prefix = self.params.get("--prefix", default="")

        if not prefix:
            self.log.info(
                "No YAML file provided, running plain perf report and exiting"
            )
            result = process.run(
                "perf stat sleep 2 > /tmp/perf_report_options.txt 2>&1",
                shell=True,
                ignore_status=False
            )
            if result.exit_status != 0:
                self.fail(f"Plain perf report failed: {result.stderr_text}")
            return

        for opt in sorted(self.final_to_test):
            self.log.info(f"Testing option: {opt}")
            self.run_and_check(opt)
        if self.unknown_options:
            self.log.warning(
                f"Unknown options skipped: {', '.join(self.unknown_options)}")
        if self.failed_options:
            self.log.error("Failed options and their exit codes:")
            for opt, code in self.failed_options.items():
                self.log.error(f"  {opt} -> {code}")
            self.fail(
                f"{len(self.failed_options)} options failed, see logs above")

    def tearDown(self):
        """
        Removes temporary files and post pre files
        """
        self.log.info("Tearing down PerfStatOptions test...")
        # Remove events directory if exists
        events_dir = "events_dir"
        if os.path.exists(events_dir):
            try:
                import shutil
                shutil.rmtree(events_dir)
                self.log.info(f"Removed temporary directory: {events_dir}")
            except Exception as e:
                self.log.warning(f"Failed to remove {events_dir}: {e}")

        # Remove any post/pre scripts created dynamically
        for opt in ["--post", "--pre"]:
            minimal = self.params.get(opt, default="")
            if minimal and os.path.exists(minimal):
                try:
                    os.remove(minimal)
                    self.log.info(f"Removed temporary script: {minimal}")
                except Exception as e:
                    self.log.warning(f"Failed to remove {minimal}: {e}")
