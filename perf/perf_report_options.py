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


class PerfReportOptions(Test):
    """
    Test perf report options: extract help and source options,
    run general perf record, and test all final options.
    Uses -o and -i to ensure perf.data is correctly located.
    """

    PERF_DATA_FILE = "perf.data"

    def setUp(self):
        """
        Checks required packages and compiles Final unused
        options to test with perf report
        """

        self.detected_distro = distro.detect()
        smg = SoftwareManager()
        if self.detected_distro.name in [
                'rhel', 'centos', 'fedora']:
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
        packages = ["perf"]
        for pkg in packages:
            if not smg.check_installed(pkg):
                if not smg.install(pkg):
                    self.cancel(f"{pkg} is required for this test")

        self.sourcedir = os.path.join(self.buldir, 'tools/perf')
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
        """
        Get available executable options for perf report
        """

        result = process.run("perf report --help", ignore_status=True)
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
        Get latest source directory and collect perf report options
        """

        if not os.path.exists(self.sourcedir):
            self.cancel(f"{self.sourcedir} not found, cannot build tools/perf")

        self.log.info(f"Building tools/perf in {self.sourcedir}")
        if build.make(self.sourcedir):
            self.fail("tools/perf build failed, check logs")

        cmd = f"grep -r 'perf report' {self.sourcedir}/tests  || true"
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
        """
        Sanitize options that are derived from source or available options
        """

        if not opt.startswith("-"):
            return None
        opt = re.sub(r"[)\'\",.:;/\[\]]+$", "", opt)
        opt = re.split(r"[=/]", opt, 1)[0]
        opt = re.sub(r"^(-[a-zA-Z])\d+$", r"\1", opt)
        return opt.strip()

    def run_record(self):
        """
        runs perf record with options that may be required for report options
        """

        record_cmd = (
            f"perf record -g -a -e cycles,instructions "
            f"-o {self.PERF_DATA_FILE} -- sleep 1"
        )
        process.system(record_cmd, shell=True)

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
            "gtk", "cgroup", "bpf", "smi-cost",
            "interval-clear", "vmlinux", "smyfs"
        ]
        if any(x in opt for x in unsupported_opts):
            self.log.info(f"Skipping unsupported option: {opt}")
            self.unknown_options.add(opt)
            return

        # --- Step 3: Determine minimal value from YAML ---
        minimal = self.params.get(opt, default="")

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
        """
        Checks for yaml file and runs final options for perf report
        """

        # Step 1: Record
        self.run_record()
        prefix = self.params.get("--prefix", default="")

        if not prefix:
            self.log.info(
                "No YAML file provided, running plain perf report and exiting"
            )
            result = process.run(
                "perf report -i ./perf.data > /tmp/perf_report_options.txt 2>&1",
                shell=True,
                ignore_status=False
            )
            if result.exit_status != 0:
                self.fail(f"Plain perf report failed: {result.stderr_text}")
            return

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
        """
        removes temporary files and perf.data files
        """

        if os.path.exists(self.PERF_DATA_FILE):
            try:
                os.remove(self.PERF_DATA_FILE)
                self.log.info(f"Removed {self.PERF_DATA_FILE}")
            except Exception as e:
                self.log.warning(
                    f"Failed to remove {self.PERF_DATA_FILE}: {e}")
        process.run("rm -rf  /tmp/perf_report_options.txt")
