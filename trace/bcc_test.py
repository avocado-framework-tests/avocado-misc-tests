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
# Author: Sachin P Bappalige <sachinpb@linux.ibm.com>
# Co-developed-by: Yeswanth Krishna <yeswanth@ibm.com>
# Test to validate BCC (BPF Compiler Collection) Test Suite

import os
import re
import shutil
from avocado import Test
from avocado.utils import distro, process
from avocado.utils.software_manager.manager import SoftwareManager


def _read_os_release():
    """
    Parse /etc/os-release and return a dict of key→value pairs.
    Values are stripped of surrounding quotes.
    """
    info = {}
    try:
        with open('/etc/os-release') as f:
            for line in f:
                line = line.strip()
                if '=' not in line or line.startswith('#'):
                    continue
                key, _, val = line.partition('=')
                info[key.strip()] = val.strip().strip('"').strip("'")
    except IOError:
        pass
    return info


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
        # Initialize build_dir early to avoid AttributeError in tearDown
        self.build_dir = None
        self.rpmbuild_dir = None

        smm = SoftwareManager()
        self.detected_distro = distro.detect()
        self.distro_name = self.detected_distro.name
        self.distro_version = self.detected_distro.version
        # Handle case where version might be an integer
        if isinstance(self.distro_version, int):
            self.distro_major = self.distro_version
        else:
            self.distro_major = int(str(self.distro_version).split('.')[0])

        self.is_rhel = self.distro_name in ['rhel', 'centos', 'fedora']
        self.is_sles = (
            "sles" in self.distro_name.lower() or self.distro_name == 'SuSE'
        )
        if not (self.is_rhel or self.is_sles):
            self.cancel(
                "BCC test is currently supported only on "
                "RHEL/CentOS/Fedora and SLES"
            )

        self.log.info("Detected distribution: %s %s (major: %s)" %
                      (self.distro_name, self.distro_version, self.distro_major))

        # Base dependencies common to all distributions.
        # clang-devel / llvm-devel are intentionally excluded here: on SLES
        # 15.x these packages are versioned (e.g. clang19-devel, llvm19-devel)
        # and no unversioned alias exists, so the correct name is resolved
        # per-distro below.  SLES 16+ and all RHEL variants do ship the plain
        # unversioned names.
        deps = [
            'rpm-build', 'rpmdevtools',
            'gcc', 'gcc-c++', 'make', 'automake', 'autoconf', 'libtool',
            'bison', 'cmake', 'flex',
            'ncurses-devel', 'libxml2-devel'
        ]

        # Add distribution-specific dependencies
        if self.is_rhel:
            clang_pkg = 'clang-devel'
            llvm_pkg = 'llvm-devel'
            deps.extend([
                'dnf-plugins-core', 'pkgconfig',
                'elfutils-debuginfod-client-devel', 'elfutils-libelf-devel',
                'libbpf-devel', 'libbpf-static', 'libbpf', 'iperf3', 'netperf',
                clang_pkg, llvm_pkg,
            ])
            # bpftool availability depends on RHEL version
            if self.distro_major >= 9:
                deps.append('bpftool')
        else:  # SLES
            # SLES 16+ ships unversioned clang-devel / llvm-devel.
            # SLES 15.x only has versioned packages and repos may not carry
            # all versions — e.g. a machine may have llvm19 installed but only
            # clang7-devel in the repos.  We therefore:
            #   1. Find the highest AVAILABLE clang[N]-devel in repos.
            #   2. Derive the required llvm major version from that clang version.
            #   3. Install the matching clang[N]-devel + llvm[N]-devel + llvm[N]-gold.
            # This keeps clang and llvm versions in sync, which bcc.spec requires.
            if self.distro_major >= 16:
                clang_pkg = 'clang-devel'
                llvm_pkg = 'llvm-devel'
                iperf_pkg = 'iperf'
                self.sles_llvm_ver = None  # unversioned, no define needed
            else:
                # SLES 15.x ships iperf3, not iperf
                iperf_pkg = 'iperf3'
                # Resolve, clean up conflicts, and install clang/llvm now.
                # They are intentionally NOT added to deps so that the generic
                # smm.install() loop below does not attempt to reinstall them
                # (which would pull the old llvm7 family back in via deps).
                clang_pkg, llvm_pkg = self._resolve_and_install_sles_llvm_pkgs()
                self.log.info(
                    "SLES 15.x: installed LLVM packages -> %s, %s"
                    % (clang_pkg, llvm_pkg)
                )
            deps.extend(['pkg-config', 'libelf-devel', iperf_pkg, 'wget',
                         'libbpf-devel', 'zip', 'sudo',
                         # pip3 is not available by default on all distros;
                         # install python3-pip via the package manager first.
                         'python3-pip'])
            # For SLES 16+ add clang/llvm to deps (no conflict risk there)
            if self.distro_major >= 16:
                deps.extend([clang_pkg, llvm_pkg])

        # pip3 is not available by default on RHEL/CentOS either;
        # python3-pip provides it.
        if self.is_rhel:
            deps.append('python3-pip')

        self.log.info(
            "Installing BCC dependencies for %s..." % self.distro_name)
        failed_packages = []

        for package in deps:
            if not smm.check_installed(package):
                self.log.info("Installing package: %s" % package)
                if not smm.install(package):
                    self.log.warning("Failed to install %s" % package)
                    failed_packages.append(package)

        # Only fail if critical packages are missing.
        # Use the resolved clang/llvm names so the check matches what was
        # actually attempted on this distro.
        critical_packages = ['gcc', 'gcc-c++', 'make', 'cmake',
                             clang_pkg, llvm_pkg,
                             'flex', 'bison', 'rpm-build']
        critical_failed = [
            pkg for pkg in failed_packages if pkg in critical_packages]

        if critical_failed:
            self.cancel("Failed to install critical packages: %s"
                        % ', '.join(critical_failed))
        elif failed_packages:
            self.log.warning("Some optional packages failed to install: %s. Continuing..."
                             % ', '.join(failed_packages))

        self.log.info("Installing Python dependencies via pip3...")
        pip_cmd = "pip3 install pyroute2 netaddr"
        result = process.run(
            pip_cmd, shell=True, ignore_status=True, sudo=True
        )

        if result.exit_status != 0:
            self.log.warning(
                "Failed to install Python dependencies via pip3: %s (continuing anyway)"
                % result.stderr.decode()
            )
        else:
            self.log.info("Python dependencies installed successfully")

        # Set up build directory
        self.build_dir = os.path.join(self.workdir, 'bcc_build')
        os.makedirs(self.build_dir, exist_ok=True)
        os.chdir(self.build_dir)

        # Set rpmbuild directory based on distribution
        if self.is_rhel:
            self.rpmbuild_dir = os.path.join(os.path.expanduser("~"), "rpmbuild")
        else:  # SLES
            self.rpmbuild_dir = "/usr/src/packages"

        self.log.info("Setup completed successfully")

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
        import re as _re

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
        m = _re.search(r'clang(\d+)-devel', clang_pkg)
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

    # ------------------------------------------------------------------ #
    # Auto-discovery helpers                                               #
    # ------------------------------------------------------------------ #

    def _discover_bcc_url_rhel(self):
        """
        Auto-discover the latest bcc-*.src.rpm URL from the CentOS Stream
        AppStream source mirror, keyed off the major OS version read from
        /etc/os-release (VERSION_ID).

        Mirror index structure:
          https://mirror.stream.centos.org/<N>-stream/AppStream/source/tree/Packages/
        """
        os_info = _read_os_release()
        version_id = os_info.get('VERSION_ID', str(self.distro_major))
        # VERSION_ID may be "10" or "10.0" — take the major part.
        major = version_id.split('.')[0]

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

        bcc_url = base_url + rpm_name
        self.log.info("Auto-discovered BCC source RPM URL: %s" % bcc_url)
        return bcc_url

    def _discover_bcc_url_sles(self):
        """
        Auto-discover the latest bcc-*.src.rpm URL from the openSUSE / SLES
        mirrors, keyed off VERSION_ID and ID read from /etc/os-release.

        Supported distributions and their mirror paths:
          openSUSE Leap 16.x:
            https://mirrorcache.opensuse.org/source/distribution/leap/<VERSION_ID>/repo/oss/src/
          SLES 15.x (any SP):
            https://mirrorcache.opensuse.org/source/distribution/leap/15.<SP>/repo/oss/src/
            where SP is derived from the CPE_NAME or VERSION field in os-release.
          openSUSE Tumbleweed:
            https://mirrorcache.opensuse.org/source/tumbleweed/repo/oss/src/
        """
        os_info = _read_os_release()
        distro_id = os_info.get('ID', '').lower()    # e.g. "opensuse-leap", "sles"
        version_id = os_info.get('VERSION_ID', '')   # e.g. "16.1", "15.7"
        pretty_name = os_info.get('PRETTY_NAME', distro_id)

        self.log.info(
            "Auto-discovering BCC source RPM for: %s %s"
            % (pretty_name, version_id)
        )

        if 'tumbleweed' in distro_id:
            base_url = (
                "https://mirrorcache.opensuse.org/source/tumbleweed/repo/oss/src/"
            )
        elif version_id:
            # Works for both openSUSE Leap and SLES — the Leap mirror carries
            # SLES-compatible source RPMs and uses the same VERSION_ID scheme.
            base_url = (
                "https://mirrorcache.opensuse.org/source/distribution/leap/"
                "%s/repo/oss/src/" % version_id
            )
        else:
            self.fail(
                "Could not determine OS version from /etc/os-release "
                "(VERSION_ID is empty). Cannot auto-discover BCC source URL."
            )

        self.log.info("Fetching BCC source RPM listing from: %s" % base_url)

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
                % (pretty_name, version_id, base_url)
            )

        bcc_url = base_url + rpm_name
        self.log.info("Auto-discovered BCC source RPM URL: %s" % bcc_url)
        return bcc_url

    # ------------------------------------------------------------------ #

    def download_bcc_source(self):
        """
        Download BCC source RPM.

        Primary path  — use the distro package manager (dnf/zypper) to pull
                        the source directly (no network scraping needed).
        Fallback path — auto-discover the latest bcc-*.src.rpm URL from the
                        appropriate upstream mirror by reading /etc/os-release,
                        then download with wget.  No YAML parameters required.
        """
        self.log.info("==== Downloading BCC source RPM ====")

        if self.is_rhel:
            cmd = "dnf --source download bcc"
            result = process.run(cmd, shell=True, ignore_status=True, sudo=True)

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
            result = process.run(cmd, shell=True, ignore_status=True, sudo=True)

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
                src_rpm = file
                break

        if not src_rpm:
            self.fail("BCC source RPM not found after download")

        self.log.info("Downloaded BCC source RPM: %s" % src_rpm)
        return src_rpm

    def install_source_rpm(self, src_rpm):
        """
        Install the source RPM
        """
        self.log.info("===== Installing BCC source RPM =====")

        cmd = "rpm -ivh %s" % src_rpm
        result = process.run(cmd, shell=True, ignore_status=True, sudo=True)

        if result.exit_status != 0:
            self.fail(
                "Failed to install source RPM: %s"
                % result.stderr.decode()
            )

        self.log.info("Source RPM installed successfully")

    def build_bcc(self):
        """
        Build BCC from source
        """
        self.log.info("============== Building BCC =================")

        # Use the rpmbuild directory set in setUp
        specs_dir = os.path.join(self.rpmbuild_dir, "SPECS")

        if not os.path.exists(specs_dir):
            self.fail("SPECS directory not found at %s" % specs_dir)

        os.chdir(specs_dir)

        self.log.info("Installing build dependencies...")
        if self.is_rhel:
            cmd = "dnf builddep -y bcc.spec"
        else:
            cmd = (
                "zypper --non-interactive source-install "
                "--build-deps-only bcc"
            )

        result = process.run(cmd, shell=True, ignore_status=True, sudo=True)

        if result.exit_status != 0:
            self.log.warning("Some build dependencies may be missing: %s"
                             % result.stderr.decode())

        # Determine the LLVM major version to pass to rpmbuild.
        # On SLES 15.x we use self.sles_llvm_ver which was set in setUp() to
        # match the clang/llvm packages that were actually installed (e.g. "7").
        # This avoids the mismatch where llvm-config reports "19" but only
        # clang7-devel is available in the repos.
        # On SLES 16+ / RHEL we fall back to llvm-config.
        llvm_version = getattr(self, 'sles_llvm_ver', None)
        if llvm_version:
            self.log.info(
                "Using SLES-resolved LLVM version for build: %s" % llvm_version)
        else:
            self.log.info("Detecting LLVM version via llvm-config...")
            llvm_ver_cmd = "llvm-config --version 2>/dev/null | cut -d. -f1"
            llvm_result = process.run(llvm_ver_cmd, shell=True, ignore_status=True)
            if llvm_result.exit_status == 0 and llvm_result.stdout:
                llvm_version = llvm_result.stdout.decode().strip()
                self.log.info("Detected LLVM version: %s" % llvm_version)
            else:
                self.log.warning(
                    "Could not detect LLVM version, trying without version define")

        self.log.info("Building BCC package...")
        if llvm_version:
            # The bcc.spec on SLES uses %{llvm_major_version} to form package
            # names like clang7-devel, llvm7-devel, llvm7-gold.
            # Pass both the SLES macro name and the common alias so the spec
            # resolves correctly regardless of which name it uses internally.
            cmd = (
                "rpmbuild -bc --noclean "
                "--define 'llvm_major_version %s' "
                "--define 'product_libs_llvm_ver %s' "
                "bcc.spec" % (llvm_version, llvm_version)
            )
        else:
            cmd = "rpmbuild -bc --noclean bcc.spec"

        result = process.run(cmd, shell=True, ignore_status=True, sudo=True,
                             timeout=3600)  # 1 hour timeout for build

        if result.exit_status != 0:
            self.fail("Failed to build BCC: %s" % result.stderr.decode())

        self.log.info("BCC built successfully")

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
                    self.log.info("Found BCC source root (nested): %s" % nested_path)
                    return nested_path

        self.log.error("Contents of %s:" % build_dir)
        for item in os.listdir(build_dir):
            self.log.error("  - %s" % item)
        self.fail("BCC source directory (CMakeLists.txt) not found in %s" % build_dir)

    def run_bcc_tests(self, build_dir):
        """
        Run BCC test suite
        """
        self.log.info("============== Running BCC tests =================")

        bcc_source_path = self._find_bcc_source_path(build_dir)

        # Use a fresh subdirectory for the test build so we never collide
        # with the rpmbuild-generated CMake cache inside 'build/'.  That
        # cache was configured for the libbpf-tools build and causes cmake
        # to fail with "unknown component LLVMBitWriter" when LLVM >= 17
        # is installed (LLVMBitWriter was merged into LLVMCore in LLVM 17+).
        bcc_test_build_path = os.path.join(bcc_source_path, "build_tests")
        os.makedirs(bcc_test_build_path, exist_ok=True)
        os.chdir(bcc_test_build_path)
        self.log.info("Using fresh test build directory: %s" % bcc_test_build_path)

        # Detect installed LLVM major version so we can pass compatibility
        # flags that avoid the LLVMBitWriter component lookup on LLVM >= 17.
        llvm_ver_cmd = "llvm-config --version 2>/dev/null | cut -d. -f1"
        llvm_ver_result = process.run(llvm_ver_cmd, shell=True, ignore_status=True)
        llvm_version = None
        if llvm_ver_result.exit_status == 0 and llvm_ver_result.stdout:
            llvm_version = llvm_ver_result.stdout.decode().strip()
            self.log.info("Detected LLVM version: %s" % llvm_version)

        # -DCMAKE_USE_LIBBPF_PACKAGE=TRUE — use system libbpf-devel instead
        # of the bundled libbpf submodule (which is absent in source tarballs
        # from dnf/zypper; only present in full git checkouts).
        # -DENABLE_LLVM_SHARED=ON links against the shared libLLVM, which
        # bypasses the per-component enumeration that triggers the
        # LLVMBitWriter error on LLVM 17+.
        # -DLLVM_INCLUDE_TESTS=OFF stops cmake from trying to resolve LLVM
        # internal test components that no longer exist as standalone libs.
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

        self.log.info("Configuring tests with cmake...")
        cmake_cmd = "cmake %s .." % cmake_flags
        result = process.run(cmake_cmd, shell=True, ignore_status=True, sudo=True,
                             timeout=300)

        if result.exit_status != 0:
            cmake_err = result.stderr.decode()
            self.log.error("cmake configuration failed: %s" % cmake_err)
            self.fail(
                "cmake failed to configure BCC test build. "
                "Ensure llvm-devel, clang-devel, and libbpf-devel are "
                "installed and match the installed LLVM version.\n"
                "cmake error: %s" % cmake_err
            )

        # Build tests
        self.log.info("Building test suite...")
        result = process.run("make -j$(nproc)", shell=True, ignore_status=True, sudo=True,
                             timeout=1800)  # 30 minutes timeout for build

        if result.exit_status != 0:
            self.log.error("Build failed: %s" % result.stderr.decode())
            self.fail("Failed to build BCC tests")

        # Log files stored in self.logdir so they appear alongside debug.log
        # in the Avocado job results directory and are included in reports.
        first_run_log = os.path.join(self.logdir, "bcc_test_output.log")
        rerun_log = os.path.join(self.logdir, "bcc_failed_tests_rerun.log")

        # ── First run ────────────────────────────────────────────────────────
        # Pass --timeout to ctest so slow tools tests (py_test_tools_smoke,
        # py_test_tools_memleak) get enough time per test. Without this ctest
        # uses a default of 1500s which is fine, but combined with 37 tests
        # the total can exceed the Avocado process timeout of 1800s.
        # Use CTEST_PARALLEL_LEVEL=1 to run tests serially — BPF tests share
        # kernel resources and fail non-deterministically when parallelised.
        self.log.info("Running BCC test suite...")
        cmd = (
            "set -o pipefail; "
            "SUDO='' CTEST_PARALLEL_LEVEL=1 make test ARGS='--timeout 600 -j1'"
            " 2>&1 | tee %s" % first_run_log
        )
        result = process.run(cmd, shell=True, ignore_status=True, sudo=True,
                             timeout=3600)  # 60 min — 37 tests × up to ~600s each

        first_run_output = result.stdout.decode()
        passed_first, failed_first = self._parse_ctest_results(first_run_output)

        if result.exit_status == 0:
            self.log.info("All BCC tests PASSED on first run!")
            self.log.info("Log: %s" % first_run_log)
            return

        # ── Rerun failed tests ───────────────────────────────────────────────
        self.log.info(
            "%d test(s) failed on first run. Re-running with verbose output..."
            % len(failed_first)
        )
        rerun_cmd = (
            "set -o pipefail; "
            "SUDO='' ctest --rerun-failed --output-on-failure --timeout 600 -j1"
            " 2>&1 | tee %s" % rerun_log
        )
        rerun_result = process.run(rerun_cmd, shell=True, ignore_status=True,
                                   sudo=True, timeout=3600)

        rerun_output = rerun_result.stdout.decode()
        passed_rerun, failed_rerun = self._parse_ctest_results(rerun_output)

        # Classify outcomes
        recovered = [t for t in failed_first if t in passed_rerun]
        still_failed = [t for t in failed_first if t not in passed_rerun]

        # ── Rerun result table ───────────────────────────────────────────────
        self.log.info("")
        self.log.info("============ Rerun Results ============")
        for name in failed_first:
            if name in passed_rerun:
                self.log.info("  [PASS] %s" % name)
            else:
                self.log.warning("  [FAIL] %s" % name)
        self.log.info("")
        self.log.info("Recovered  : %d / %d" % (len(recovered), len(failed_first)))
        self.log.info("Still FAIL : %d / %d" % (len(still_failed), len(failed_first)))
        if still_failed:
            for t in still_failed:
                self.log.error("    %s" % t)
        self.log.info("Logs:")
        self.log.info("  First run : %s" % first_run_log)
        self.log.info("  Rerun     : %s" % rerun_log)
        self.log.info("=======================================")

        if still_failed:
            self.log.error("Rerun verbose output:\n%s" % rerun_output)
            self.fail(
                "%d BCC test(s) still failed after rerun: %s"
                % (len(still_failed), ', '.join(still_failed))
            )
        else:
            self.log.info(
                "All failures recovered on rerun "
                "(%d flaky test(s): %s)"
                % (len(recovered), ', '.join(recovered))
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
        try:
            src_rpm = self.download_bcc_source()
            self.install_source_rpm(src_rpm)
            build_dir = self.build_bcc()
            self.run_bcc_tests(build_dir)
            self.log.info("===== BCC test completed successfully =====")

        except Exception as e:
            self.fail("BCC test failed with exception: %s" % str(e))

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
        self.log.info("Cleaning up test environment")

        # Clean only the working directory, leave rpmbuild artifacts for debugging
        if hasattr(self, 'build_dir') and self.build_dir and os.path.exists(self.build_dir):
            shutil.rmtree(self.build_dir, ignore_errors=True)
