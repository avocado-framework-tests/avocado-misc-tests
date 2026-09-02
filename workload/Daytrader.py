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
# Copyright: 2024 IBM
# Author: Samir A Mulani <samir@linux.vnet.ibm.com>

import os
import re
import shutil
import socket
import time

from avocado import Test
from avocado.utils import archive, distro, process
from avocado.utils.software_manager.manager import SoftwareManager


_INSTALL_ROOT = "/root"


class Daytrader(Test):

    def _run(self, cmd, fail_msg, ignore_status=False):
        """Run a shell command and fail the test on non-zero exit status.

        Args:
            cmd (str): Shell command to execute.
            fail_msg (str): Message passed to self.fail() on error.
            ignore_status (bool): When True, a non-zero exit status is
                tolerated and the result is returned without failing.

        Returns:
            avocado.utils.process.CmdResult: The command result object.
        """
        result = process.run(cmd, shell=True, ignore_status=True,
                             sudo=False, verbose=True)
        if result.exit_status != 0 and not ignore_status:
            self.log.error(f"stderr: {result.stderr_text.strip()}")
            self.fail(fail_msg)
        return result

    def _list_remote_files(self, base_url):
        """Retrieve file names listed at *base_url* via an HTTP
        directory index.

        Parses ``href`` attributes from the HTML returned by *base_url* and
        returns only plain-file entries (directories, parent links, and query
        strings are excluded).  The list is used to discover the tarball and
        install script names dynamically so that hardcoded file names are not
        required.

        Args:
            base_url (str): HTTP(S) URL of the directory to list.

        Returns:
            list[str]: File names found at *base_url*.

        Cancels the test if the URL is unreachable.
        """
        result = process.run(
            f"curl -fsSL {base_url.rstrip('/')}/",
            shell=True, ignore_status=True, verbose=False)
        if result.exit_status != 0:
            self.cancel(
                f"Cannot reach install URL '{base_url}'. "
                f"Check network connectivity and URL. rc={result.exit_status}")

        raw = result.stdout_text
        hrefs = re.findall(r'href="([^"]+)"', raw)
        files = [h for h in hrefs
                 if not h.startswith(("?", "/", ".."))
                 and h != "./"
                 and not h.endswith("/")]
        self.log.info(f"Remote files found at {base_url}: {files}")
        return files

    def _validate_hostname(self):
        """Validate that the system hostname is a resolvable FQDN.

        Logs a warning when the hostname is not a FQDN.  Fails the test when
        the FQDN cannot be resolved, because DB2 instance creation requires a
        resolvable hostname.
        """
        hostname = socket.gethostname()
        self.log.info(f"Current hostname: {hostname}")

        if "." not in hostname:
            self.log.warning(
                f"Hostname '{hostname}' is not a FQDN. "
                "DB2 instance creation may fail. "
                "Set a FQDN with:  hostname <fqdn>  "
                "and update /etc/hostname accordingly.")
        else:
            try:
                resolved_ip = socket.gethostbyname(hostname)
                self.log.info(
                    f"Hostname '{hostname}' resolves to "
                    f"{resolved_ip}")
            except socket.gaierror as exc:
                self.fail(
                    f"Hostname '{hostname}' does not resolve: {exc}.  "
                    "DB2 installation requires a resolvable hostname.")

    def _detect_java_pkgs(self):
        """Detect which Java packages (>= 17) are available in enabled repos.

        Queries the package manager for all available ``java-*`` packages and
        selects a JRE and JDK package at major version 17 or higher.  If no
        qualifying JRE is found the test is cancelled, because DayTrader7
        cannot run without Java >= 17.

        Returns:
            list[str]: Package names to install (JRE and optionally JDK).
        """
        self.log.info("Probing available Java packages (>= 17) via dnf ...")
        result = process.run(
            "dnf list available 2>/dev/null | grep -iE 'java-[0-9]'",
            shell=True, ignore_status=True, verbose=False)

        available = result.stdout_text.lower()
        java_pkgs = []

        # Collect all java-<N>-openjdk[-headless] entries where N >= 17.
        jre_candidates = re.findall(r'(java-(\d+)-openjdk(?:-headless)?)',
                                    available)
        qualifying_jre = [(pkg, int(ver))
                          for pkg, ver in jre_candidates if int(ver) >= 17]
        if qualifying_jre:
            # Prefer the highest available version; prefer headless variant.
            qualifying_jre.sort(key=lambda x: (x[1], "headless" in x[0]),
                                reverse=True)
            best_jre = qualifying_jre[0][0]
            java_pkgs.append(best_jre)
            self.log.info(f"Selected JRE package: {best_jre}")
        else:
            self.cancel(
                "No Java >= 17 JRE found in enabled repos.  "
                "Enable the AppStream repository and retry.")

        # Add a matching JDK if available.
        jdk_candidates = re.findall(r'(java-(\d+)-openjdk-devel)',
                                    available)
        qualifying_jdk = [(pkg, int(ver))
                          for pkg, ver in jdk_candidates if int(ver) >= 17]
        if qualifying_jdk:
            qualifying_jdk.sort(key=lambda x: x[1], reverse=True)
            best_jdk = qualifying_jdk[0][0]
            java_pkgs.append(best_jdk)
            self.log.info(f"Selected JDK package: {best_jdk}")

        return java_pkgs

    def _set_java_alternative(self):
        """Configure the system Java alternative to use a version >= 17.

        Checks the currently active ``java`` binary version.  If it is
        already >= 17, records ``JAVA_HOME`` and returns.  Otherwise searches
        ``/usr/lib/jvm`` for a suitable binary and registers it via
        ``update-alternatives``.  Sets ``self._java_home`` so that callers
        can export ``JAVA_HOME`` when spawning subprocesses.
        """
        _MIN_JAVA = 17
        self._java_home = ""

        def _parse_java_version(out):
            m = re.search(r'"(\d+)(?:\.(\d+))?', out)
            if not m:
                return 0
            major = int(m.group(1))
            if major == 1 and m.group(2):
                return int(m.group(2))
            return major

        def _java_home_from_bin(java_bin):
            real = process.run(f"readlink -f {java_bin}", shell=True,
                               ignore_status=True, verbose=False)
            resolved = real.stdout_text.strip() or java_bin
            if resolved.endswith("/bin/java"):
                return resolved[:-len("/bin/java")]
            return os.path.dirname(os.path.dirname(resolved))

        ver_result = process.run("java -version", shell=True,
                                 ignore_status=True, verbose=False)
        ver_output = (ver_result.stdout_text + ver_result.stderr_text).strip()
        active_ver = _parse_java_version(ver_output)
        self.log.info(f"Detected active Java major version: {active_ver}")

        if active_ver >= _MIN_JAVA:
            which = process.run("which java", shell=True,
                                ignore_status=True, verbose=False)
            java_bin = which.stdout_text.strip() or "/usr/bin/java"
            self._java_home = _java_home_from_bin(java_bin)
            self.log.info(
                f"Java {active_ver} >= {_MIN_JAVA} OK. "
                f"JAVA_HOME={self._java_home}")
            return

        self.log.warning(
            f"Active Java {active_ver} < {_MIN_JAVA}. "
            "Searching /usr/lib/jvm ...")

        find_result = process.run(
            "find /usr/lib/jvm -name 'java' -path '*/bin/java' "
            "2>/dev/null | sort",
            shell=True, ignore_status=True, verbose=False)
        candidates = [p.strip() for p in
                      find_result.stdout_text.splitlines() if p.strip()]
        self.log.info(f"Java binaries found: {candidates}")

        chosen, chosen_ver = None, 0
        for candidate in candidates:
            cv_result = process.run(f"{candidate} -version", shell=True,
                                    ignore_status=True, verbose=False)
            cv_out = (cv_result.stdout_text + cv_result.stderr_text)
            cv = _parse_java_version(cv_out)
            if cv >= _MIN_JAVA and cv > chosen_ver:
                chosen, chosen_ver = candidate, cv

        if not chosen:
            self.log.warning(
                f"No Java >= {_MIN_JAVA} found under /usr/lib/jvm. "
                "JAVA_HOME not set. JMeter/Liberty will likely fail.")
            return

        self._java_home = _java_home_from_bin(chosen)
        self.log.info(
            f"Selected Java {chosen_ver}: {chosen}  "
            f"JAVA_HOME={self._java_home}")

        priority = chosen_ver * 1000
        process.run(
            "update-alternatives --install "
            f"/usr/bin/java java {chosen} {priority}",
            shell=True, ignore_status=True, verbose=False)
        process.run(
            f"update-alternatives --set java {chosen}",
            shell=True, ignore_status=True, verbose=False)

        final_out = process.run("java -version", shell=True,
                                ignore_status=True, verbose=False)
        final_ver = _parse_java_version(
            final_out.stdout_text + final_out.stderr_text)
        self.log.info(f"JAVA_HOME will be exported as: {self._java_home}")
        if final_ver < _MIN_JAVA:
            self.log.warning(
                f"java -version still {final_ver} after alternatives switch. "
                "JAVA_HOME export in subshells is the primary fix.")

    def _install_packages(self, packages):
        """Install a list of packages using the system software manager.

        Each package is checked first; if already present it is skipped.
        If a package cannot be installed the test is cancelled.

        Args:
            packages (list[str]): Package names to install.
        """
        smm = SoftwareManager()
        for pkg in packages:
            if not smm.check_installed(pkg):
                self.log.info(f"Installing prerequisite package: {pkg}")
                if not smm.install(pkg):
                    self.cancel(
                        f"Cannot install prerequisite package '{pkg}'. "
                        "Ensure the package repositories are configured "
                        "and the system has internet/intranet access.")
            else:
                self.log.info(f"Package already installed: {pkg}")

    def setUp(self):
        """Prepare the test environment.

        Validates the architecture and privileges, detects the distro,
        defines required package lists, installs prerequisites, fetches
        and extracts the DayTrader7 asset, and runs the installer.
        """
        if "ppc64" not in distro.detect().arch:
            self.cancel("DayTrader7 test is supported only on "
                        "IBM Power (ppc64le) architecture")

        if os.geteuid() != 0:
            self.cancel("DayTrader7 installation and workload must be run "
                        "as root (DB2 requires root during install)")

        self.detected_distro = distro.detect()
        distro_name = self.detected_distro.name
        distro_ver = self.detected_distro.version
        self.log.info(
            f"Detected distro: name={distro_name}  "
            f"version={distro_ver}")

        # Package lists are defined here as member variables (not at module
        # level) so they are scoped to each test instance.
        _common_pkgs = [
            "tar",
            "gzip",
            "hostname",
            "net-tools",
            "gcc",
            "gcc-c++",
            "make",
            "kernel-devel",
            "libaio-devel",
            "libstdc++-devel",
            "pam-devel",
            "numactl",
        ]
        _sles_pkgs = _common_pkgs + [
            "kernel-default-devel",
            "java-17-openjdk",
            "java-17-openjdk-devel",
        ]
        _rhel_pkgs = _common_pkgs + [
            "kernel-headers",
        ]

        self._java_pkgs = []
        default_url = ""
        if distro_name in ("SuSE", "suse", "sles"):
            self.distro_tag = f"{distro_name.lower()}{distro_ver}"
            self.req_pkgs = _sles_pkgs
            default_url = self.params.get("install_url", default="")
        elif distro_name in ("rhel", "centos", "fedora"):
            self.distro_tag = f"{distro_name.lower()}{distro_ver}"
            self.req_pkgs = _rhel_pkgs
            self._java_pkgs = self._detect_java_pkgs()
            default_url = self.params.get("install_url", default="")
        else:
            self.cancel(
                f"DayTrader7 test supports SLES and RHEL only. "
                f"Detected: {distro_name} {distro_ver}")

        self.install_url = self.params.get("install_url", default=default_url)
        self.users = self.params.get("users", default=20)
        self.duration = self.params.get("duration", default=1800)
        self.instances = self.params.get("instances", default=2)

        self.log.info(
            f"DayTrader7 setup: distro={self.distro_tag}, "
            f"install_url={self.install_url}")

        self._validate_hostname()

        self.log.info(
            "Installing prerequisite packages ...")
        self._install_packages(self.req_pkgs)

        if self._java_pkgs:
            self._install_packages(self._java_pkgs)
            self._set_java_alternative()

        remote_files = self._list_remote_files(self.install_url)
        if not remote_files:
            self.cancel(f"No files found at install URL: {self.install_url}")

        tarballs = [f for f in remote_files if f.endswith(".tar.gz")]
        if not tarballs:
            tarballs = [f for f in remote_files
                        if f.endswith(".tar") and not f.endswith(".tar.gz")]
        install_scripts = [f for f in remote_files
                           if f.startswith("INSTALL_") and f.endswith(".sh")]

        if not tarballs:
            self.cancel(
                f"No .tar.gz or .tar found at {self.install_url}")
        if not install_scripts:
            self.cancel(f"No INSTALL_*.sh found at {self.install_url}")

        self.tarball_name = tarballs[0]
        self.install_script = install_scripts[0]
        self.log.info(f"Discovered tarball      : {self.tarball_name}")
        self.log.info(f"Discovered install script: {self.install_script}")

        # Download every file from the remote location into _INSTALL_ROOT.
        self.files_in_root = []
        for fname in remote_files:
            file_url = self.install_url.rstrip("/") + "/" + fname
            self.log.info(f"Fetching: {file_url}")
            cached_path = self.fetch_asset(file_url)
            dest = os.path.join(_INSTALL_ROOT, fname)
            if not os.path.exists(dest):
                shutil.copy2(cached_path, dest)
            self.files_in_root.append(dest)

        # On RHEL the INSTALL_*.sh script handles tarball extraction
        # internally, so we must NOT pre-extract here.  On SLES the
        # install script expects the tarball to already be extracted.
        if distro_name not in ("rhel", "centos", "fedora"):
            tarball_path = os.path.join(_INSTALL_ROOT, self.tarball_name)
            before = set(os.listdir(_INSTALL_ROOT))
            self.log.info(f"Extracting {tarball_path} -> {_INSTALL_ROOT}")
            archive.extract(tarball_path, _INSTALL_ROOT)
            after = set(os.listdir(_INSTALL_ROOT))
            for item in after - before:
                path = os.path.join(_INSTALL_ROOT, item)
                self.files_in_root.append(path)
        else:
            self.log.info(
                f"Skipping tarball extraction for {distro_name}: "
                f"{self.install_script} will handle it internally.")

        self._install()

    def _install(self):
        """Run the DayTrader7 installation script.

        Locates ``INSTALL_*.sh``, makes it executable, and executes it with
        the DB2 license agreement pre-accepted.  Fails the test if the script
        exits with a non-zero status.

        The "already installed" sentinel is ``/root/bin/`` — a directory
        created exclusively by the installer.  On RHEL ``DayTrader7_Run.sh``
        is downloaded as a plain file before the installer runs, so it cannot
        be used as the sentinel (it would always be present and skip the
        install step).
        """
        script_path = os.path.join(_INSTALL_ROOT, self.install_script)

        if not os.path.isfile(script_path):
            self.cancel(f"Install script not found at '{script_path}'. "
                        "Check download step completed.")

        self._run(f"chmod +x {script_path}",
                  f"Cannot chmod install script: {script_path}")

        # Use /root/bin/ as the sentinel: it is created by the installer and
        # is never present from a plain file download.
        install_sentinel = os.path.join(_INSTALL_ROOT, "bin")
        if os.path.isdir(install_sentinel):
            self.log.info(
                f"Install sentinel '{install_sentinel}' already exists – "
                "installation already completed. Skipping.")
            return

        self.log.info(
            "Starting DayTrader7 installation. This may take 10-20 minutes.")

        java_env = ""
        if getattr(self, '_java_home', ""):
            java_env = (f"export JAVA_HOME={self._java_home} && "
                        "export PATH=$JAVA_HOME/bin:$PATH && ")

        install_cmd = (
            f"cd {_INSTALL_ROOT} && {java_env}"
            f"echo '1' | bash {script_path}")

        result = process.run(install_cmd, shell=True, ignore_status=True,
                             verbose=True)

        if result.exit_status != 0:
            self.log.error(
                "Installation stderr:\n"
                f"{result.stderr_text.strip()[-2000:]}")
            self.fail(
                f"DayTrader7 installation script '{script_path}' "
                f"exited with rc={result.exit_status}. "
                "Check stderr above for details.")

        if not os.path.isdir(install_sentinel):
            self.fail(
                "Installation succeeded (rc=0) but sentinel "
                f"directory '{install_sentinel}' was NOT found. "
                "Review the installer output above.")

        self.log.info(
            f"DayTrader7 installation complete. "
            f"Sentinel: {install_sentinel}")

    def test_run_workload(self):
        """Execute the DayTrader7 workload and validate its exit status.

        Runs ``DayTrader7_Run.sh`` with the configured user count, duration,
        and instance count.  Fails the test if the script returns a non-zero
        exit status.
        """
        run_script = os.path.join(_INSTALL_ROOT, "DayTrader7_Run.sh")

        if not os.path.isfile(run_script):
            self.fail(
                f"DayTrader7_Run.sh not found at '{run_script}'. "
                "Check that setUp/_install completed successfully.")

        self._run(f"chmod +x {run_script}",
                  f"Cannot chmod run script: {run_script}")

        java_env = ""
        if getattr(self, '_java_home', ""):
            java_env = (f"export JAVA_HOME={self._java_home} && "
                        "export PATH=$JAVA_HOME/bin:$PATH && ")

        workload_cmd = (
            f"cd {_INSTALL_ROOT} && {java_env}"
            f"./DayTrader7_Run.sh -u {self.users}"
            f" -l {self.duration} -i {self.instances}"
        )

        self.log.info(
            f"Launching DayTrader7 workload: "
            f"users={self.users}, duration={self.duration}s, "
            f"instances={self.instances}")

        start_time = time.time()
        result = process.run(workload_cmd, shell=True, ignore_status=True,
                             verbose=True)
        elapsed = time.time() - start_time

        self.log.info(
            f"Workload finished in {elapsed:.1f} seconds "
            f"(rc={result.exit_status}).")

        if result.exit_status != 0:
            # Only dump stderr on failure to avoid Avocado WARN status
            # caused by bash set -x trace output written to stderr on
            # success.
            if result.stderr_text.strip():
                self.log.error(
                    "Workload stderr:\n"
                    f"{result.stderr_text.strip()[-2000:]}")
            self.fail(
                f"DayTrader7_Run.sh exited with "
                f"rc={result.exit_status}. "
                "Review the workload output above for errors.")

        self.log.info(
            "DayTrader7 workload completed successfully.  "
            f"users={self.users}, duration={self.duration}s, "
            f"instances={self.instances}")

    def tearDown(self):
        """Clean up all files and directories created under ``/root``.

        Removes every entry recorded in ``self.files_in_root`` regardless
        of test outcome so that subsequent runs start from a clean state.
        """
        self.log.info(
            f"tearDown: cleaning up /root "
            f"(status={self.status}) ...")

        if hasattr(self, 'files_in_root'):
            for path in self.files_in_root:
                if os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=True)
                elif os.path.isfile(path):
                    try:
                        os.remove(path)
                    except OSError as err:
                        self.log.warning(f"Could not remove {path}: {err}")

        self.log.info("tearDown: cleanup of /root complete.")
