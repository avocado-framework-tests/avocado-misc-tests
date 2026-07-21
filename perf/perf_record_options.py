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

import glob
import re
import os
from avocado import Test
from avocado.utils import process, distro, build
from avocado.utils.software_manager.manager import SoftwareManager


class PerfRecordOptions(Test):
    """
    Test perf record options: compare --help options vs kernel source.
    Run only options present in help but missing from source.
    """

    def setUp(self):
        """
        Checks for dependencies and packages and Compiles
        final stat options options that are not used to be run
        """
        self.log.info("Setting up PerfRecordOptions test...")

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
        Extract valid -/-- options from `perf record --help`.
        Ignores separators and non-option lines.
        """
        result = process.run("perf record --help", ignore_status=True)
        out = result.stdout.decode()
        opts = set()
        for line in out.splitlines():
            line = line.strip()
            if not line or set(line) == {"-"}:
                continue
            tokens = line.split()
            for token in tokens:
                if re.match(r"^-{1,2}[a-zA-Z]", token):
                    clean_opt = self.sanitize_option(token)
                    if clean_opt:
                        opts.add(clean_opt)
        return opts

    def get_src_options(self):
        """
        Grep perf kernel tests for 'perf record' and extract options.
        """
        if not os.path.exists(self.sourcedir):
            self.cancel(f"{self.sourcedir} not found, cannot build tools/perf")

        self.log.info(f"Building tools/perf in {self.sourcedir}")
        if build.make(self.sourcedir):
            self.fail("tools/perf build failed, check logs")
        self.log.info(f"Using Linux source directory: {self.sourcedir}")

        # Grep recursively for 'perf record' in tools/perf/tests and
        # tests/shell
        cmd = f"grep -r 'perf record' {self.sourcedir}/tools/perf/tests || true"
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
        Run a perf record command for the given option.
        Uses minimal dummy workloads and ensures a general record works universally.
        """

        # --- Step 1: Sanitize option ---
        opt = self.sanitize_option(opt)
        if not opt:
            return

        # --- Step 2: Skip unsupported infra (cgroup / bpf / smi-cost / interval-clear) ---
        if opt in ["--for-each-cgroup",
                   "-b",
                   "--bpf",
                   "--bpf-attr-map",
                   "--bpf-counters",
                   "--bpf-prog",
                   "--cgroup",
                   "--smi-cost",
                   "--interval-clear",
                   "--aux-sample",
                   "-S",
                   "--kcore",
                   "--snapshot",
                   "-—exclude-perf",
                   "--vmlinux",
                   "--setup-filter"
                   ]:
            self.log.info(f"Skipping unsupported option: {opt}")
            self.unknown_options.add(opt)
            return

        # --- Step 3: Determine dummy value ---
        dummy = self.params.get(opt, default="")
        if dummy:
            self.log.info(
                f"For option {opt}, using dummy value from YAML: {dummy}")
        else:
            self.log.info(
                f"No YAML value found for option {opt}, using default general recording")

        # Special handling for TID/PID
        if opt in ["-t", "--tid"] or "--tid=" in opt:
            try:
                dummy = os.listdir("/proc/self/task")[0]
            except Exception:
                dummy = str(os.getpid())
        if opt in ["-p", "--pid"] or "--pid=" in opt:
            dummy = str(os.getpid())

        # --- Step 4: Construct perf record command ---
        cmd_parts = ["perf", "record"]

        # Options with "="
        if "=" in opt:
            base_opt = opt.split("=", 1)[0]
            cmd_parts.append(f"{base_opt}={dummy}")
        elif dummy:
            cmd_parts.extend([opt, dummy])
        else:
            # General recording
            cmd_parts.append(opt)
        cmd_parts.append("-o /tmp/perf.data -- sleep 2")

        cmd = " ".join(cmd_parts)

        # --- Step 5: Run command ---
        process.run("rm -rf /tmp/perf.data")
        result = process.run(cmd, shell=True, ignore_status=True)
        ret = result.exit_status
        out = result.stdout.decode("utf-8", errors="ignore")
        err = result.stderr.decode("utf-8", errors="ignore")

        # --- Step 6: Handle results ---
        if ret != 0:
            if ret == 129 or "unknown option" in err.lower():
                self.log.info(f"Skipping option {opt}: unknown option")
                self.unknown_options.add(opt)
            else:
                self.failed_options[opt] = {
                    "exit_code": ret, "stderr": err.strip()}
                self.log.warning(f"Option {opt} failed with exit code {ret}")
        else:
            self.log.info(f"Option {opt} ran successfully")
            # Optional: validate /tmp/perf.data exists
            if not glob.glob("/tmp/perf.data*"):
                self.failed_options[opt] = {"error": "Record file not created"}
                self.log.warning(f"Record file not created for option {opt}")
            else:
                self.log.info(
                    "General record file /tmp/perf.data created successfully")

        return ret, out, err

    def sanitize_option(self, opt):
        if not opt.startswith("-"):
            return None
        opt = re.sub(r"[),.:;/\[\]]+$", "", opt)
        opt = re.split(r"[=/]", opt, 1)[0]
        opt = re.sub(r"^(-[a-zA-Z])\d+$", r"\1", opt)
        opt = opt.strip()
        if not opt:
            return None
        return opt

    def test_perf_record_options(self):
        """
        Run all final options with dummy values where required.
        """

        yaml_provided = False
        try:
            if self.params.get("--affinity", default=None) is not None:
                yaml_provided = True
        except Exception:
            yaml_provided = False

        if not yaml_provided:
            self.log.info(
                "No YAML file provided, running plain perf report and exiting")
            result = process.run(
                "perf record -o /tmp/perf.data -- sleep 2",
                shell=True,
                ignore_status=False)
            if result.exit_status != 0:
                self.fail(f"Plain perf stat failed: {result.stderr_text}")
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
        self.log.info("Tearing down PerfRecordOptions test...")
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
            dummy = self.params.get(opt, default="")
            if dummy and os.path.exists(dummy):
                try:
                    os.remove(dummy)
                    self.log.info(f"Removed temporary script: {dummy}")
                except Exception as e:
                    self.log.warning(f"Failed to remove {dummy}: {e}")

        # Remove general perf.data
        if os.path.exists("/tmp/perf.data"):
            try:
                os.remove("/tmp/perf.data")
                self.log.info("Removed /tmp/perf.data file")
            except Exception as e:
                self.log.warning(f"Failed to remove /tmp/perf.data: {e}")
