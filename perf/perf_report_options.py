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
    PERF_DATA_LATENCY_FILE = "perf_latency.data"

    def setUp(self):
        """
        Checks required packages and compiles Final unused
        options to test with perf report
        """
        self.detected_distro = distro.detect()
        smg = SoftwareManager()
        distro_name = self.detected_distro.name

        if distro_name in ['rhel', 'centos', 'fedora']:
            self.buldir = smg.get_source(
                'kernel', self.workdir, build_option='-bp')
            if not self.buldir or not os.path.exists(self.buldir):
                self.cancel("Failed to get kernel source directory")
            dir_contents = os.listdir(self.buldir)
            if not dir_contents:
                self.cancel("Kernel source directory is empty")
            self.buldir = os.path.join(self.buldir, dir_contents[0])
        elif 'SuSE' in distro_name:
            if not smg.check_installed(
                    "kernel-source") and not smg.install("kernel-source"):
                self.cancel("Failed to install kernel-source for this test")
            if not os.path.exists("/usr/src/linux"):
                self.cancel("Kernel source missing after install")
            self.buldir = "/usr/src/linux"
        elif distro_name in ['ubuntu', 'debian']:
            self.buldir = smg.get_source('linux', self.workdir)
            if not self.buldir or not os.path.exists(self.buldir):
                self.cancel("Failed to get kernel source directory")
        else:
            self.cancel(
                f"Distro {distro_name} not supported for kernel source install")

        packages = [
            "perf",
            "elfutils-devel",
            "elfutils-debuginfod-client-devel",
            "systemtap-sdt-devel",
            "openssl-devel",
            "slang-devel",
            "llvm-devel",
            "numactl-devel",
            "libbabeltrace-devel",
            "capstone-devel",
            "java-latest-openjdk-devel",
            "libpfm-devel",
            "libtraceevent-devel"
        ]

        for pkg in packages:
            if not smg.check_installed(pkg):
                if not smg.install(pkg):
                    self.log.warning(
                        f"Failed to install {pkg}, continuing anyway")

        self.sourcedir = os.path.join(self.buldir, 'tools/perf')
        self.unknown_options = set()
        self.failed_options = {}

        # Step 1: Get help options
        self.perf_help_options = self._get_help_options()
        self.log.info(f"Perf report --help options: {self.perf_help_options}")

        # Step 2: Get source options
        self.perf_src_options = self._get_src_options()
        self.log.info(f"Perf report source options: {self.perf_src_options}")

        # Step 3: Final options to test
        self.final_to_test = self.perf_help_options - self.perf_src_options
        self.log.info(f"Final options to test: {self.final_to_test}")

    def _get_help_options(self):
        """
        Get available executable options for perf report.
        Parses help output carefully to avoid false positives.
        """
        result = process.run("perf report --help", ignore_status=True)
        out = result.stdout.decode()
        opts = set()

        for line in out.splitlines():
            stripped = line.lstrip()
            # Only parse lines that start with option syntax (- or --)
            if not stripped.startswith('-'):
                continue

            # Skip lines that look like examples or command output (contain '='
            # with values)
            if '=' in stripped and not stripped.split(
                    '=')[0].strip().startswith('-'):
                continue

            # Extract first token which should be the option
            tokens = stripped.split()
            if not tokens:
                continue

            # Process first few tokens (options are usually at the start)
            for token in tokens[:3]:  # Limit to first 3 tokens to avoid descriptions
                # Remove trailing commas/punctuation
                token = token.rstrip(',')
                # Match valid option format: -x or --option-name
                if re.match(r"^-{1,2}[A-Za-z][A-Za-z0-9\-]*$", token):
                    clean_opt = self._sanitize_option(token)
                    if clean_opt and len(
                            clean_opt) > 1:  # Ensure it's not just '-'
                        opts.add(clean_opt)

        return opts

    def _get_src_options(self):
        """
        Get latest source directory and collect perf report options.
        Fixed parsing logic to filter out non-report options.
        Build is attempted but failures are ignored - we only need source files for grep.
        """
        if not os.path.exists(self.sourcedir):
            self.log.warning(
                f"{self.sourcedir} not found, skipping source options check")
            return set()

        self.log.info(f"Attempting to build tools/perf in {self.sourcedir}")
        try:
            build.make(self.sourcedir)
            self.log.info("Build completed successfully")
        except Exception as e:
            self.log.warning(
                f"Build failed but continuing to grep source files: {e}")

        # Search specifically for perf report command usage in test files
        # This works even if build failed, as long as source files exist
        cmd = f"grep -r 'perf report' {self.sourcedir}/tests || true"
        result = process.run(cmd, ignore_status=True, shell=True)
        out = result.stdout.decode()

        opts = set()
        for line in out.splitlines():
            # Only process lines that actually contain 'perf report' command
            if 'perf report' not in line:
                continue

            # Extract the portion after 'perf report'
            parts = line.split('perf report', 1)
            if len(parts) < 2:
                continue

            report_args = parts[1]

            # Find options in the report arguments
            matches = re.findall(r"-{1,2}[a-zA-Z][\w-]*", report_args)
            for opt in matches:
                clean_opt = self._sanitize_option(opt)
                if clean_opt:
                    opts.add(clean_opt)

        return opts

    def _sanitize_option(self, opt):
        """
        Sanitize options that are derived from source or available options
        """
        if not opt.startswith("-"):
            return None

        opt = re.sub(r"[)\'\",.:;/\[\]]+$", "", opt)
        opt = re.split(r"[=/]", opt, 1)[0]
        opt = re.sub(r"^(-[a-zA-Z])\d+$", r"\1", opt)

        return opt.strip()

    def _run_record(self):
        """
        Runs perf record with options that may be required for report options.
        Creates two data files: one with -a for most options, one with --latency for latency options.
        """
        # Record 1: System-wide collection for most options
        record_cmd = (
            f"perf record -g -a -e cycles,instructions "
            f"-o {self.PERF_DATA_FILE} -- sleep 1"
        )
        process.system(record_cmd, shell=True)

        latency_cmd = (
            f"perf record -g --latency -e cycles,instructions "
            f"-o {self.PERF_DATA_LATENCY_FILE} -- sleep 1"
        )
        process.system(latency_cmd, shell=True)

    def _run_report(self, opt=None):
        """
        Run a perf report command for the given option, using YAML for minimal
        values and skipping unsupported infra or options.
        Uses appropriate data file based on option type.
        """
        # --- Step 1: Sanitize option ---
        opt = self._sanitize_option(opt)
        if not opt:
            return

        # --- Step 2: Skip unsupported infrastructure options ---
        # Options that require special setup/infrastructure that we can't test
        unsupported_opts = [
            "gtk", "cgroup", "bpf", "smi-cost", "smyfs"
        ]
        if any(x in opt for x in unsupported_opts):
            self.log.info(f"Skipping unsupported infrastructure option: {opt}")
            self.unknown_options.add(opt)
            return

        # --- Step 3: Determine minimal value from YAML ---
        minimal = self.params.get(opt, default="")

        # --- Step 4: Choose appropriate data file ---
        # Use latency data file for latency-related options
        if "latency" in opt.lower() or "parallelism" in opt.lower():
            data_file = self.PERF_DATA_LATENCY_FILE
        else:
            data_file = self.PERF_DATA_FILE

        # --- Step 5: Construct command ---
        cmd_parts = [f"perf report -i {data_file}"]

        # If minimal value exists, append it to the option
        if "=" in opt:
            base_opt = opt.split("=", 1)[0]
            cmd_parts.append(f"{base_opt}={minimal}")
        elif minimal:
            cmd_parts.extend([opt, minimal])
        elif opt:
            cmd_parts.append(opt)

        # Add output redirection to prevent interactive options from hanging
        cmd_parts.append("> /dev/null 2>&1")
        cmd = " ".join(cmd_parts)

        # --- Step 5: Run command with timeout ---
        self.log.info(f"Running perf report: {cmd}")
        try:
            result = process.run(
                cmd, shell=True, ignore_status=True, timeout=30)
            ret = result.exit_status
            out = result.stdout_text
            err = result.stderr_text
        except process.CmdError as e:
            if "timeout" in str(e).lower():
                self.log.warning(f"Perf report timed out for option: {opt}")
                self.unknown_options.add(opt)
                return 124, "", "Command timed out"
            raise

        # --- Step 6: Handle results ---
        if ret != 0:
            if ret == 129 or "unknown option" in err.lower() or "invalid option" in err.lower():
                self.log.info(
                    f"Skipping report option {opt}: unknown/unsupported option")
                self.unknown_options.add(opt)
            else:
                # Store failure but don't fail immediately - continue testing
                # other options
                self.failed_options[opt or "general"] = {
                    "exit_code": ret, "stderr": err.strip(), "stdout": out.strip()}
                self.log.warning(
                    f"Perf report failed with exit code {ret} for option: {opt}")

        return ret, out, err

    def test_perf_report_options(self):
        """
        Test perf report with various options from help and YAML configuration.
        Checks for yaml file and runs final options for perf report.
        """
        # Step 1: Record
        self._run_record()

        prefix = self.params.get("--prefix", default="")
        if not prefix:
            self.log.info(
                "No YAML file provided, running plain perf report and exiting"
            )
            result = process.run(
                f"perf report -i {self.PERF_DATA_FILE}",
                shell=True,
                ignore_status=False
            )
            if result.exit_status != 0:
                self.fail(f"Plain perf report failed: {result.stderr_text}")
            return

        # Step 2: Loop through final options - continue testing all options
        # even if some fail
        for opt in sorted(self.final_to_test):
            self._run_report(opt)

        # Step 3: Report results after testing all options
        if self.unknown_options:
            self.log.warning(
                f"Unknown options skipped: {', '.join(sorted(self.unknown_options))}")

        if self.failed_options:
            self.log.error("Failed report options and their details:")
            for opt, details in sorted(self.failed_options.items()):
                self.log.error(
                    f"  {opt} -> exit_code: {details['exit_code']}, stderr: {details['stderr'][:100]}")
            self.fail(
                f"{len(self.failed_options)} options failed, see logs above")

    def tearDown(self):
        """
        Removes temporary files and perf.data files
        """
        # Remove both data files
        for data_file in [self.PERF_DATA_FILE, self.PERF_DATA_LATENCY_FILE]:
            if os.path.exists(data_file):
                try:
                    os.remove(data_file)
                    self.log.info(f"Removed {data_file}")
                except Exception as e:
                    self.log.warning(f"Failed to remove {data_file}: {e}")

        process.run("rm -rf /tmp/perf_report_options.txt", ignore_status=True)
