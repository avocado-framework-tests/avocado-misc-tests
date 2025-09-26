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
from avocado.utils import process, distro
from avocado.utils.software_manager.manager import SoftwareManager


class PerfReportOptions(Test):
    """
    Test perf report options: extract help and source options,
    run general perf record, and test all final options.
    Uses -o and -i to ensure perf.data is correctly located.
    """

    PERF_DATA_FILE = "./perf.data"

    def setUp(self):
        self.log.info("Setting up PerfReportOptions test...")

        detected_distro = distro.detect()
        smm = SoftwareManager()
        packages = []
        if "rhel" in detected_distro.name.lower():
            packages = ["perf", "kernel-devel"]
        elif "suse" in detected_distro.name.lower():
            packages = ["perf", "kernel-source"]
        else:
            self.cancel("Unsupported Linux distribution")

        for pkg in packages:
            if not smm.check_installed(pkg):
                if not smm.install(pkg):
                    self.cancel(f"{pkg} is required for this test")

        self.unknown_options = set()
        self.failed_options = {}

        # Step 1: Get help options
        self.perf_help_options = self.get_help_options()
        self.log.info(f"Perf report --help options: {self.perf_help_options}")

        # Step 2: Get source options
        self.perf_src_options = self.get_src_options()
        self.log.info(f"Perf report source options: {self.perf_src_options}")

        # Step 3: Final options to test
        self.final_to_test = self.perf_help_options - self.perf_src_options
        self.log.info(f"Final options to test: {self.final_to_test}")

    def get_help_options(self):
        result = process.run("perf report --help", ignore_status=True)
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
        src_dir = None
        for path in ["/usr/src/linux", "/usr/src/linux-*"]:
            if os.path.exists(path):
                src_dir = path
                break
        if not src_dir:
            self.log.warning(
                "Linux source tree not found, src options set empty")
            return set()

        cmd = f"grep -r 'perf report' {src_dir}/tools/perf/tests {src_dir}/tools/perf/tests/shell || true"
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

    def sanitize_option(self, opt):
        if not opt.startswith("-"):
            return None
        opt = re.sub(r"[)\'\",.:;/\[\]]+$", "", opt)
        opt = re.split(r"[=/]", opt, 1)[0]
        opt = re.sub(r"^(-[a-zA-Z])\d+$", r"\1", opt)
        return opt.strip()

    def run_record(self):
        record_cmd = f"perf record -g -a -e cycles,instructions -o {self.PERF_DATA_FILE} -- sleep 1"
        self.log.info(f"Running general perf record: {record_cmd}")
        result = process.run(record_cmd, shell=True, ignore_status=True)
        if result.exit_status != 0:
            self.fail(f"General perf record failed: {result.stderr_text}")
        self.log.info(
            f"General perf record completed successfully: {self.PERF_DATA_FILE}")

    def run_report(self, opt=None):
        """
        Run a perf report command for the given option, using YAML for minimal
        values and skipping unsupported infra or options.
        """
        # --- Step 1: Sanitize option ---
        opt = self.sanitize_option(opt)
        if not opt:
            return

        # --- Step 2: Skip unsupported infra or options ---
        unsupported_opts = [
            "gtk",
            "cgroup",
            "bpf",
            "smi-cost",
            "interval-clear",
            "vmlinux",
            "smyfs"]
        if any(x in opt for x in unsupported_opts):
            self.log.info(f"Skipping unsupported option: {opt}")
            self.unknown_options.add(opt)
            return

        # --- Step 3: Determine minimal value from YAML ---
        minimal = self.params.get(opt, default="")
        if minimal:
            self.log.info(
                f"For option {opt}, using minimal value from YAML: {minimal}")
        else:
            self.log.info(
                f"No YAML value found for option {opt}, using default if needed")

        # --- Step 5: Construct command ---
        cmd_parts = [f"perf report -i {self.PERF_DATA_FILE} "]

        # If minimal value exists, append it to the option
        if "=" in opt:
            base_opt = opt.split("=", 1)[0]
            cmd_parts.append(f"{base_opt}={minimal}")
        elif minimal:
            cmd_parts.extend([opt, minimal])
        elif opt:
            cmd_parts.append(opt)

        cmd_parts.append("> /tmp/perf_report_options.txt 2>&1")
        cmd = " ".join(cmd_parts)

        # --- Step 6: Run command ---
        self.log.info(f"Running perf report: {cmd}")
        process.run("rm -rf  /tmp/perf_report_options.txt")
        result = process.run(cmd, shell=True, ignore_status=True)
        ret = result.exit_status
        out = result.stdout_text
        err = result.stderr_text

        # --- Step 7: Handle results ---
        if ret != 0:
            if ret == 129 or "unknown option" in err.lower():
                self.log.info(f"Skipping report option {opt}: unknown option")
                self.unknown_options.add(opt)
            else:
                self.failed_options[opt or "general"] = {
                    "exit_code": ret, "stderr": err.strip()}
                self.log.warning(f"Perf report failed with exit code {ret}")
        else:
            self.log.info(
                f"Perf report ran successfully with option: {opt or 'none'}")

        return ret, out, err

    def test_perf_report_options(self):
        # Step 1: Record
        self.run_record()

        # Step 2: Loop through final options
        for opt in sorted(self.final_to_test):
            self.run_report(opt)

        if self.unknown_options:
            self.log.warning(
                f"Unknown options skipped: {', '.join(self.unknown_options)}")
        if self.failed_options:
            self.log.error("Failed report options and their exit codes:")
            for opt, code in self.failed_options.items():
                self.log.error(f"  {opt} -> {code}")
            self.fail(
                f"{len(self.failed_options)} options failed, see logs above")

    def tearDown(self):
        if os.path.exists(self.PERF_DATA_FILE):
            try:
                os.remove(self.PERF_DATA_FILE)
                self.log.info(f"Removed {self.PERF_DATA_FILE}")
            except Exception as e:
                self.log.warning(
                    f"Failed to remove {self.PERF_DATA_FILE}: {e}")
