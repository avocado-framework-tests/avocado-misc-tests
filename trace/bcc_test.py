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
# Co-developed-by: Sachin P Bappalige <sachinpb@linux.ibm.com>
# Signed-off-by: Sachin P Bappalige <sachinpb@linux.ibm.com>
# Signed-off-by: yeswanth <yeswanth@linux.ibm.com>
# Test to validate BCC (BPF Compiler Collection) Test Suite

import os
import re
import shutil
from avocado import Test
from avocado.utils import distro, process
from avocado.utils.software_manager.manager import SoftwareManager


class BCCTest(Test):

    """
    BCC (BPF Compiler Collection) test suite
    Tests BCC functionality by downloading source, building and running tests
    :avocado: tags=trace,bcc,bpf,privileged
    """

    def setUp(self):
        """
        Install the basic packages to support BCC build and testing
        """
        self.build_dir = None
        self.rpmbuild_dir = None
        smm = SoftwareManager()
        self.detected_distro = distro.detect()
        self.distro_name = self.detected_distro.name
        self.distro_major = int(str(self.detected_distro.version).split('.')[0])
        self.is_rhel = self.distro_name in ['rhel', 'centos', 'fedora']
        self.is_sles = (
            "sles" in self.distro_name.lower() or self.distro_name == 'SuSE'
        )
        if not (self.is_rhel or self.is_sles):
            self.cancel(
                "BCC test is currently supported only on "
                "RHEL/CentOS/Fedora and SLES"
            )
        self.log.info("Detected distribution: %s (major: %s)" %
                      (self.distro_name, self.distro_major))
        deps = [
            'rpm-build', 'rpmdevtools',
            'gcc', 'gcc-c++', 'make', 'automake', 'autoconf', 'libtool',
            'bison', 'cmake', 'flex',
            'ncurses-devel', 'libxml2-devel', 'python3-pip'
        ]
        if self.is_rhel:
            clang_pkg = 'clang-devel'
            llvm_pkg = 'llvm-devel'
            deps.extend([
                'dnf-plugins-core', 'pkgconfig',
                'elfutils-debuginfod-client-devel', 'elfutils-libelf-devel',
                'libbpf-devel', 'libbpf-static', 'libbpf', 'iperf3', 'netperf',
                clang_pkg, llvm_pkg,
            ])
            if self.distro_major >= 9:
                deps.append('bpftool')
        else:  # SLES
            # Find and install the highest available clang[N]-devel package and related dependent packages.
            if self.distro_major >= 16:
                clang_pkg = 'clang-devel'
                llvm_pkg = 'llvm-devel'
                iperf_pkg = 'iperf'
                self.sles_llvm_ver = None
            else:
                iperf_pkg = 'iperf3'
                clang_pkg, llvm_pkg = self._resolve_and_install_sles_llvm_pkgs()
                self.log.info(
                    "SLES 15.x: installed LLVM packages -> %s, %s"
                    % (clang_pkg, llvm_pkg)
                )
            deps.extend(['pkg-config', 'libelf-devel', iperf_pkg, 'wget',
                         'libbpf-devel', 'zip', 'sudo'])
            # For SLES 16+ add clang/llvm to deps (no conflict risk there)
            if self.distro_major >= 16:
                deps.extend([clang_pkg, llvm_pkg])

        self.log.info(
            "Installing BCC dependencies for %s..." % self.distro_name)
        failed_packages = []
        for package in deps:
            if not smm.check_installed(package):
                self.log.info("Installing package: %s" % package)
                if not smm.install(package):
                    self.log.warning("Failed to install %s" % package)
                    failed_packages.append(package)
        critical_packages = ['gcc', 'gcc-c++', 'make', 'cmake',
                             clang_pkg, llvm_pkg,
                             'flex', 'bison', 'rpm-build']
        critical_failed = [
            pkg for pkg in failed_packages if pkg in critical_packages]

        if critical_failed:
            self.cancel("Failed to install critical packages: %s"
                        % ', '.join(critical_failed))
        self.build_dir = os.path.join(self.workdir, 'bcc_build')
        os.makedirs(self.build_dir, exist_ok=True)

        # Set rpmbuild directory based on distribution
        if self.is_rhel:
            self.rpmbuild_dir = os.path.join(
                os.path.expanduser("~"), "rpmbuild")
        else:  # SLES
            self.rpmbuild_dir = "/usr/src/packages"

        self.llvm_version = getattr(self, 'sles_llvm_ver', None)
        if not self.llvm_version:
            llvm_ver_cmd = "llvm-config --version 2>/dev/null | cut -d. -f1"
            llvm_result = process.run(
                llvm_ver_cmd, shell=True, ignore_status=True)
            if llvm_result.exit_status == 0 and llvm_result.stdout:
                self.llvm_version = llvm_result.stdout.decode().strip()

    def _resolve_and_install_sles_llvm_pkgs(self):
        """
        On SLES 15.x, clang and llvm packages are versioned (clang7-devel,
        llvm7-devel, …) and bcc.spec requires them to be the SAME major version.
        Repos may not carry all versions — e.g. llvm19 may be installed but
        only clang7-devel may be available.

        Strategy:
        1. Find the highest clang[N]-devel available in repos (clang drives
           the version choice because it is more constrained than llvm).
        2. Derive the llvm major version number N from the clang package name.
        3. Remove all installed clang/llvm family packages that are NOT of
           version N to eliminate cmake(LLVM)/cmake(Clang) conflicts.
        4. Install clang[N]-devel, llvm[N]-devel, and llvm[N]-gold together.
        5. Store the version N in self.sles_llvm_ver for use in build_bcc().
        6. Return (clang_pkg, llvm_pkg) for the critical_packages check.
        """
        # Step 1 — find highest available clang[N]-devel in repos
        avail_result = process.run(
            "zypper search -t package 'clang[0-9]*-devel' 2>/dev/null | "
            "awk -F'|' '{print $2}' | "
            "grep -E '^[[:space:]]*clang[0-9]+-devel[[:space:]]*$' | "
            "tr -d ' ' | sort -V | tail -1",
            shell=True, ignore_status=True
        )
        if not (avail_result.exit_status == 0 and avail_result.stdout.strip()):
            self.log.warning(
                "No versioned clang[N]-devel found in repos; "
                "will attempt plain clang-devel / llvm-devel"
            )
            self.sles_llvm_ver = None
            return 'clang-devel', 'llvm-devel'

        clang_pkg = avail_result.stdout.decode().strip()  # e.g. clang7-devel

        # Step 2 — extract version number from package name
        m = re.search(r'clang(\d+)-devel', clang_pkg)
        if not m:
            self.log.warning(
                "Could not parse version from '%s'; "
                "falling back to plain names" % clang_pkg
            )
            self.sles_llvm_ver = None
            return 'clang-devel', 'llvm-devel'

        ver = m.group(1)                    # e.g. "7"
        llvm_pkg = 'llvm%s-devel' % ver     # e.g. llvm7-devel
        gold_pkg = 'llvm%s-gold' % ver      # e.g. llvm7-gold
        self.sles_llvm_ver = ver
        self.log.info(
            "SLES 15.x: using clang/llvm version %s "
            "(%s, %s, %s)" % (ver, clang_pkg, llvm_pkg, gold_pkg)
        )

        # Step 3 — remove all installed clang/llvm family packages that are
        # NOT of version N to avoid cmake(LLVM)/cmake(Clang) conflicts.
        # Patterns: clang*, libclang*, llvm*, libomp* — excluding versionN.
        for prefix, ver_prefix in [('clang', 'clang%s' % ver),
                                   ('llvm', 'llvm%s' % ver)]:
            installed = process.run(
                "rpm -qa --qf '%%{NAME}\\n' | "
                "grep -E '^(%s|lib%s|libomp)[0-9]' | "
                "grep -v '^%s'" % (prefix, prefix, ver_prefix),
                shell=True, ignore_status=True
            )
            if installed.exit_status == 0 and installed.stdout.strip():
                to_remove = [p for p in installed.stdout.decode().splitlines()
                             if p.strip()]
                if to_remove:
                    self.log.info(
                        "Removing conflicting %s packages: %s"
                        % (prefix, ', '.join(sorted(to_remove)))
                    )
                    process.run(
                        "zypper --non-interactive remove "
                        "--force-resolution -y %s" % ' '.join(to_remove),
                        shell=True, ignore_status=True, sudo=True
                    )

        # Step 4 — install clang[N]-devel + llvm[N]-devel + llvm[N]-gold
        install_pkgs = [clang_pkg, llvm_pkg]

        gold_check = process.run(
            "zypper search -x '%s' 2>/dev/null | grep -q '%s'"
            % (gold_pkg, gold_pkg),
            shell=True, ignore_status=True
        )
        if gold_check.exit_status == 0:
            install_pkgs.append(gold_pkg)

        self.log.info("Installing %s ..." % ', '.join(install_pkgs))
        install_result = process.run(
            "zypper --non-interactive install --force-resolution -l %s"
            % ' '.join(install_pkgs),
            shell=True, ignore_status=True, sudo=True
        )
        if install_result.exit_status != 0:
            self.log.warning(
                "Failed to install %s (exit %d): %s"
                % (' '.join(install_pkgs), install_result.exit_status,
                   install_result.stderr.decode())
            )

        return clang_pkg, llvm_pkg

    def _discover_bcc_url_rhel(self):
        """
        Auto-discover the latest bcc-*.src.rpm URL from the CentOS Stream
        AppStream source mirror, keyed off the major OS version read from
        /etc/os-release (VERSION_ID).

        Mirror index structure:
          https://mirror.stream.centos.org/<N>-stream/AppStream/source/tree/Packages/
        """
        major = str(self.distro_major)

        base_url = (
            "https://mirror.stream.centos.org/%s-stream/"
            "AppStream/source/tree/Packages/" % major
        )
        self.log.info(
            "Auto-discovering BCC source RPM from CentOS Stream "
            "(RHEL %s): %s" % (major, base_url)
        )
        # Fetch the directory listing and grep for the latest bcc src rpm.
        listing_cmd = (
            "curl -fsSL --connect-timeout 15 '%s' 2>/dev/null | "
            "grep -oP 'bcc-[0-9][^\"]*\\.src\\.rpm' | sort -V | tail -1"
            % base_url
        )
        result = process.run(listing_cmd, shell=True, ignore_status=True)
        rpm_name = result.stdout.decode().strip() if result.exit_status == 0 else ''
        if not rpm_name:
            self.fail(
                "Auto-discovery of BCC source RPM failed for RHEL %s.\n"
                "Could not fetch a bcc-*.src.rpm filename from:\n  %s\n"
                "Check network connectivity or mirror availability."
                % (major, base_url)
            )
        if not re.match(r'^bcc-[A-Za-z0-9._+~-]+\.src\.rpm$', rpm_name):
            self.fail(
                "Scraped RPM filename contains unexpected characters: %r\n"
                "Refusing to use it in a shell command." % rpm_name
            )
        bcc_url = base_url + rpm_name
        self.log.info("Auto-discovered BCC source RPM URL: %s" % bcc_url)
        return bcc_url

    def _discover_bcc_url_sles(self):
        """
        Auto-discover the latest bcc-*.src.rpm URL from the openSUSE / SLES
        mirrors, keyed off version and release from distro.detect().

        Mirror path:
          https://mirrorcache.opensuse.org/source/distribution/leap/<version>.<release>/repo/oss/src/
        """
        version_id = "%s.%s" % (self.detected_distro.version,
                                self.detected_distro.release)
        base_url = (
            "https://mirrorcache.opensuse.org/source/distribution/leap/"
            "%s/repo/oss/src/" % version_id
        )
        listing_cmd = (
            "curl -fsSL --connect-timeout 15 '%s' 2>/dev/null | "
            "grep -oP 'bcc-[0-9][^\"]*\\.src\\.rpm' | sort -V | tail -1"
            % base_url
        )
        result = process.run(listing_cmd, shell=True, ignore_status=True)
        rpm_name = result.stdout.decode().strip() if result.exit_status == 0 else ''
        if not rpm_name:
            self.fail(
                "Auto-discovery of BCC source RPM failed for %s %s.\n"
                "Could not fetch a bcc-*.src.rpm filename from:\n  %s\n"
                "Check network connectivity or mirror availability."
                % (self.distro_name, version_id, base_url)
            )

        if not re.match(r'^bcc-[A-Za-z0-9._+~-]+\.src\.rpm$', rpm_name):
            self.fail(
                "Scraped RPM filename contains unexpected characters: %r\n"
                "Refusing to use it in a shell command." % rpm_name
            )

        bcc_url = base_url + rpm_name
        self.log.info("Auto-discovered BCC source RPM URL: %s" % bcc_url)
        return bcc_url

    def download_bcc_source(self):
        """
        Download BCC source RPM.

        Primary path  — use the distro package manager (dnf/zypper) to pull
                        the source directly (no network scraping needed).
        Fallback path — auto-discover the latest bcc-*.src.rpm URL from the
                        appropriate upstream mirror by reading /etc/os-release,
                        then download with wget.  No YAML parameters required.
        """
        if self.is_rhel:
            cmd = "dnf --source download bcc"
            result = process.run(
                cmd, shell=True, ignore_status=True, sudo=True)

            if result.exit_status != 0:
                self.log.warning(
                    "dnf --source download failed (partner/source repos may "
                    "not be enabled on RHEL %s): %s — "
                    "falling back to auto-discovery"
                    % (self.distro_major, result.stderr.decode())
                )
                bcc_url = self._discover_bcc_url_rhel()
                cmd = "wget -q -P %s %s" % (self.build_dir, bcc_url)
                result = process.run(
                    cmd, shell=True, ignore_status=True, sudo=True)
                if result.exit_status != 0:
                    self.fail(
                        "Failed to download BCC source RPM via wget: %s\n"
                        "URL used: %s"
                        % (result.stderr.decode(), bcc_url)
                    )
        else:  # SLES
            cmd = "zypper source-install -d bcc"
            result = process.run(
                cmd, shell=True, ignore_status=True, sudo=True)

            if result.exit_status != 0:
                self.log.warning(
                    "zypper source-install failed — "
                    "falling back to auto-discovery"
                )
                bcc_url = self._discover_bcc_url_sles()
                cmd = "wget -q -P %s %s" % (self.build_dir, bcc_url)
                result = process.run(
                    cmd, shell=True, ignore_status=True, sudo=True)
                if result.exit_status != 0:
                    self.fail(
                        "Failed to download BCC source RPM via wget: %s\n"
                        "URL used: %s"
                        % (result.stderr.decode(), bcc_url)
                    )

        # Find the downloaded source RPM
        src_rpm = None
        for file in os.listdir(self.build_dir):
            if file.startswith('bcc-') and file.endswith('.src.rpm'):
                src_rpm = os.path.join(self.build_dir, file)
                break
        if not src_rpm:
            self.fail("BCC source RPM not found after download")

        self.log.info("Downloaded BCC source RPM: %s" % src_rpm)
        return src_rpm

    def install_source_rpm(self, src_rpm):
        """
        Install the source RPM
        """
        cmd = "rpm -ivh %s" % src_rpm
        result = process.run(cmd, shell=True, ignore_status=True, sudo=True)

        if result.exit_status != 0:
            self.fail(
                "Failed to install source RPM: %s"
                % result.stderr.decode()
            )

    def build_bcc(self):
        """
        Build BCC from source
        """
        # Use the rpmbuild directory set in setUp
        specs_dir = os.path.join(self.rpmbuild_dir, "SPECS")
        if not os.path.exists(specs_dir):
            self.fail("SPECS directory not found at %s" % specs_dir)
        if self.is_rhel:
            cmd = "cd %s && dnf builddep -y bcc.spec" % specs_dir
        else:
            cmd = (
                "cd %s && zypper --non-interactive source-install "
                "--build-deps-only bcc" % specs_dir
            )
        result = process.run(cmd, shell=True, ignore_status=True, sudo=True)
        if result.exit_status != 0:
            self.log.warning("Some build dependencies may be missing: %s"
                             % result.stderr.decode())
        llvm_version = self.llvm_version
        if llvm_version:
            cmd = (
                "cd %s && rpmbuild -bc --noclean "
                "--define 'llvm_major_version %s' "
                "--define 'product_libs_llvm_ver %s' "
                "bcc.spec" % (specs_dir, llvm_version, llvm_version)
            )
        else:
            cmd = "cd %s && rpmbuild -bc --noclean bcc.spec" % specs_dir
        result = process.run(cmd, shell=True, ignore_status=True, sudo=True,
                             timeout=3600)
        if result.exit_status != 0:
            self.fail("Failed to build BCC: %s" % result.stderr.decode())
        build_dir = os.path.join(self.rpmbuild_dir, "BUILD")
        return build_dir

    def _find_bcc_source_path(self, build_dir):
        """
        Locate the BCC source root inside the rpmbuild BUILD directory.
        Directory layouts differ across distros and BCC versions:
          SLES standard  : BUILD/bcc-<ver>-build/bcc-<ver>/CMakeLists.txt
          SLES workaround: BUILD/bcc-workaround/CMakeLists.txt
          RHEL           : BUILD/bcc-<ver>/CMakeLists.txt

        Instead of guessing from directory names (which breaks for
        non-standard names like 'bcc-workaround'), we search for the
        directory that contains CMakeLists.txt — the definitive marker
        of the BCC source root.
        """
        if not os.path.isdir(build_dir):
            self.fail("BUILD directory not found: %s" % build_dir)
        for entry in sorted(os.listdir(build_dir), reverse=True):
            top = os.path.join(build_dir, entry)
            if not os.path.isdir(top):
                continue
            # Direct source root (RHEL / SLES workaround pattern)
            if os.path.exists(os.path.join(top, "CMakeLists.txt")):
                self.log.info("Found BCC source root: %s" % top)
                return top
            # One level deeper (SLES standard: BUILD/bcc-*-build/bcc-*/)
            for nested in sorted(os.listdir(top), reverse=True):
                nested_path = os.path.join(top, nested)
                if os.path.isdir(nested_path) and os.path.exists(
                        os.path.join(nested_path, "CMakeLists.txt")):
                    self.log.info(
                        "Found BCC source root (nested): %s" % nested_path)
                    return nested_path
        self.fail(
            "BCC source directory (CMakeLists.txt) not found in %s" % build_dir)

    def run_bcc_tests(self, build_dir):
        """
        Run BCC test suite
        """
        bcc_source_path = self._find_bcc_source_path(build_dir)
        # Use a fresh subdirectory for the test build so we never collide
        # with the rpmbuild-generated CMake cache inside 'build/'.  That
        # cache was configured for the libbpf-tools build and causes cmake
        # to fail with "unknown component LLVMBitWriter" when LLVM >= 17
        # is installed (LLVMBitWriter was merged into LLVMCore in LLVM 17+).
        bcc_test_build_path = os.path.join(bcc_source_path, "build_tests")
        os.makedirs(bcc_test_build_path, exist_ok=True)
        llvm_version = self.llvm_version
        cmake_flags = (
            "-DENABLE_TESTS=ON "
            "-DCMAKE_BUILD_TYPE=Release "
            "-DCMAKE_USE_LIBBPF_PACKAGE=TRUE "
            "-DENABLE_LLVM_SHARED=ON"
        )
        if llvm_version:
            try:
                if int(llvm_version) >= 17:
                    cmake_flags += " -DLLVM_INCLUDE_TESTS=OFF"
            except ValueError:
                pass
        cmake_cmd = "cd %s && cmake %s .." % (bcc_test_build_path, cmake_flags)
        result = process.run(cmake_cmd, shell=True, ignore_status=True, sudo=True,
                             timeout=300)
        if result.exit_status != 0:
            cmake_err = result.stderr.decode()
            self.fail(
                "cmake failed to configure BCC test build. "
                "Ensure llvm-devel, clang-devel, and libbpf-devel are "
                "installed and match the installed LLVM version.\n"
                "cmake error: %s" % cmake_err
            )
        # Build tests
        result = process.run("cd %s && make -j$(nproc)" % bcc_test_build_path,
                             shell=True, ignore_status=True, sudo=True,
                             timeout=1800)
        if result.exit_status != 0:
            self.fail("Failed to build BCC tests: %s" % result.stderr.decode())
        # Log files stored in self.logdir so they appear alongside debug.log
        # in the Avocado job results directory and are included in reports.
        first_run_log = os.path.join(self.logdir, "bcc_test_output.log")
        rerun_log = os.path.join(self.logdir, "bcc_failed_tests_rerun.log")
        cmd = (
            "cd %s && set -o pipefail; "
            "SUDO='' CTEST_PARALLEL_LEVEL=1 make test ARGS='--timeout 600 -j1'"
            " 2>&1 | tee %s" % (bcc_test_build_path, first_run_log)
        )
        result = process.run(cmd, shell=True, ignore_status=True, sudo=True,
                             timeout=3600)
        first_run_output = result.stdout.decode()
        passed_first, failed_first = self._parse_ctest_results(
            first_run_output)
        if result.exit_status == 0:
            return
        rerun_cmd = (
            "cd %s && set -o pipefail; "
            "SUDO='' ctest --rerun-failed --output-on-failure --timeout 600 -j1"
            " 2>&1 | tee %s" % (bcc_test_build_path, rerun_log)
        )
        rerun_result = process.run(rerun_cmd, shell=True, ignore_status=True,
                                   sudo=True, timeout=3600)
        rerun_output = rerun_result.stdout.decode()
        passed_rerun, _ = self._parse_ctest_results(rerun_output)
        # Classify outcomes
        still_failed = [t for t in failed_first if t not in passed_rerun]
        if still_failed:
            self.fail(
                "%d BCC test(s) still failed after rerun: %s\n%s"
                % (len(still_failed), ', '.join(still_failed), rerun_output)
            )

    def _parse_ctest_results(self, ctest_output):
        """
        Parse ctest stdout and return (passed_names, failed_names) lists.

        Handles per-test result lines:
            25/37 Test #25: py_test_utils ..................   Passed    0.11 sec
            29/37 Test #29: py_test_tools_smoke ............***Failed  180.94 sec
        and the end-of-run failure summary block:
            The following tests FAILED:
                  3 - test_libbcc (Failed)
        The summary block is used for failed names (catches timeouts reliably).
        """
        passed = []
        failed = []
        # [\.\*]+ handles both dot-filled and ***Failed lines
        for line in ctest_output.splitlines():
            m = re.match(
                r'^\s*\d+/\d+\s+Test\s+#\d+:\s+(\S+)\s+[\.\*]+\s+Passed',
                line
            )
            if m:
                passed.append(m.group(1))
        in_failed_section = False
        for line in ctest_output.splitlines():
            if "The following tests FAILED" in line:
                in_failed_section = True
                continue
            if in_failed_section:
                m = re.match(r'^\s+\d+\s+-\s+(\S+)', line)
                if m:
                    failed.append(m.group(1))
                elif not line.startswith(' '):
                    in_failed_section = False
        # Fallback: derive failed from result lines when no summary block
        if not failed:
            all_tests = re.findall(
                r'^\s*\d+/\d+\s+Test\s+#\d+:\s+(\S+)',
                ctest_output, re.MULTILINE
            )
            failed = [t for t in all_tests if t not in passed]
        return passed, failed

    def test_bcc(self):
        """
        Main test method that orchestrates the BCC test workflow
        """
        src_rpm = self.download_bcc_source()
        self.install_source_rpm(src_rpm)
        build_dir = self.build_bcc()
        self.run_bcc_tests(build_dir)

    def tearDown(self):
        """
        Cleanup after test execution
        Note: rpmbuild artifacts are intentionally left on the system for
        debugging and analysis purposes. These include:
        - BUILD/ directory: Contains compiled source code and build artifacts
        - SPECS/ directory: Contains RPM spec files
        - SOURCES/ directory: Contains source tarballs
        - SRPMS/ directory: Contains source RPM packages

        Location of artifacts:
        - RHEL/CentOS/Fedora: ~/rpmbuild/
        - SLES: /usr/src/packages/

        To manually clean these artifacts after test completion:
        RHEL: rm -rf ~/rpmbuild
        SLES: rm -rf /usr/src/packages
        """
        # Clean only the working directory, leave rpmbuild artifacts for debugging
        if hasattr(self, 'build_dir') and self.build_dir and os.path.exists(self.build_dir):
            shutil.rmtree(self.build_dir, ignore_errors=True)
