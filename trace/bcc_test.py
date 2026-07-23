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
#
# Test to validate BCC (BPF Compiler Collection) Test Suite with RHEL and SLES Support

import os
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

        # Base dependencies common to all distributions
        deps = [
            'rpm-build', 'rpmdevtools',
            'gcc', 'gcc-c++', 'make', 'automake', 'autoconf', 'libtool',
            'bison', 'clang-devel', 'cmake', 'flex', 'llvm-devel',
            'ncurses-devel', 'libxml2-devel'
        ]

        # Add distribution-specific dependencies
        if self.is_rhel:
            deps.extend([
                'dnf-plugins-core', 'pkgconfig',
                'elfutils-debuginfod-client-devel', 'elfutils-libelf-devel',
                'libbpf-devel', 'libbpf-static', 'libbpf', 'iperf3', 'netperf'
            ])
            # bpftool availability depends on RHEL version
            if self.distro_major >= 9:
                deps.append('bpftool')
        else:  # SLES
            deps.extend(['pkg-config', 'libelf-devel', 'iperf', 'wget',
                        'libbpf-devel'])

        self.log.info(
            "Installing BCC dependencies for %s..." % self.distro_name)
        failed_packages = []

        for package in deps:
            if not smm.check_installed(package):
                self.log.info("Installing package: %s" % package)
                if not smm.install(package):
                    self.log.warning("Failed to install %s" % package)
                    failed_packages.append(package)

        # Only fail if critical packages are missing
        critical_packages = ['gcc', 'gcc-c++', 'make', 'cmake', 'clang-devel',
                             'llvm-devel', 'flex', 'bison', 'rpm-build']
        critical_failed = [
            pkg for pkg in failed_packages if pkg in critical_packages]

        if critical_failed:
            self.cancel("Failed to install critical packages: %s"
                        % ', '.join(critical_failed))
        elif failed_packages:
            self.log.warning("Some optional packages failed to install: %s. Continuing..."
                             % ', '.join(failed_packages))

        self.log.info("Installing Python dependencies...")
        pip_cmd = "pip3 install pyroute2 netaddr"
        result = process.run(
            pip_cmd, shell=True, ignore_status=True, sudo=True
        )

        if result.exit_status != 0:
            self.log.warning(
                "Failed to install pyroute2: %s (continuing anyway)"
                % result.stderr.decode()
            )
        else:
            self.log.info("pyroute2 installed successfully")

        # Set up build directory
        self.build_dir = os.path.join(self.workdir, 'bcc_build')
        os.makedirs(self.build_dir, exist_ok=True)
        os.chdir(self.build_dir)

        # Set rpmbuild directory based on distribution
        if self.is_rhel:
            self.rpmbuild_dir = os.path.join(
                os.path.expanduser("~"), "rpmbuild")
        else:  # SLES
            self.rpmbuild_dir = "/usr/src/packages"

        self.log.info("Setup completed successfully")

    def download_bcc_source(self):
        """
        Download BCC source RPM
        """
        self.log.info("==== Downloading BCC source RPM ====")

        if self.is_rhel:
            cmd = "dnf --source download bcc"
            result = process.run(
                cmd, shell=True, ignore_status=True, sudo=True)

            if result.exit_status != 0:
                self.fail(
                    "Failed to download BCC source RPM: %s"
                    % result.stderr.decode()
                )
        else:  # SLES
            # Try zypper first, fallback to wget with auto-discovery or parameter
            cmd = "zypper source-install -d bcc"
            result = process.run(
                cmd, shell=True, ignore_status=True, sudo=True)

            if result.exit_status != 0:
                self.log.warning("zypper source-install failed, trying wget")

                # Get URL from test parameter or use auto-discovery
                bcc_url = self.params.get('bcc_sles_source_url', default=None)

                if not bcc_url:
                    # Auto-discover BCC package from OpenSUSE repository
                    self.log.info(
                        "No URL parameter provided, attempting auto-discovery")
                    base_url = "https://download.opensuse.org/source/distribution/leap/16.1/repo/oss/src/"

                    # Try to list directory and find bcc package
                    self.log.info(
                        "Searching for BCC package at: %s" % base_url)
                    cmd = "wget -q -O - %s | grep -oP 'bcc-[0-9]+\\.[0-9]+\\.[0-9]+-[0-9]+\\.[0-9]+\\.[0-9]+\\.src\\.rpm' | head -1" % base_url
                    result = process.run(
                        cmd, shell=True, ignore_status=True, sudo=True)

                    if result.exit_status == 0 and result.stdout:
                        bcc_filename = result.stdout.decode().strip()
                        bcc_url = base_url + bcc_filename
                        self.log.info(
                            "Auto-discovered BCC package: %s" % bcc_url)
                    else:
                        self.fail(
                            "Failed to auto-discover BCC package and no 'bcc_sles_source_url' "
                            "parameter provided. Please provide the parameter:\n"
                            "avocado run bcc.py -p bcc_sles_source_url=<URL_to_BCC_source_RPM>\n"
                            "Or check if the package exists at: %s" % base_url
                        )

                self.log.info("Downloading BCC from: %s" % bcc_url)
                cmd = "wget %s" % bcc_url
                result = process.run(
                    cmd, shell=True, ignore_status=True, sudo=True)

                if result.exit_status != 0:
                    self.fail(
                        "Failed to download BCC source RPM via wget: %s"
                        % result.stderr.decode()
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

        # Auto-detect LLVM version
        self.log.info("Detecting LLVM version...")
        llvm_ver_cmd = "llvm-config --version 2>/dev/null | cut -d. -f1"
        llvm_result = process.run(llvm_ver_cmd, shell=True, ignore_status=True)

        llvm_version = None
        if llvm_result.exit_status == 0 and llvm_result.stdout:
            llvm_version = llvm_result.stdout.decode().strip()
            self.log.info("Detected LLVM version: %s" % llvm_version)
        else:
            self.log.warning(
                "Could not auto-detect LLVM version, trying without version define")

        self.log.info("Building BCC package...")
        if llvm_version:
            cmd = "rpmbuild -bc --noclean --define 'product_libs_llvm_ver %s' bcc.spec" % llvm_version
        else:
            cmd = "rpmbuild -bc --noclean bcc.spec"

        result = process.run(cmd, shell=True, ignore_status=True, sudo=True,
                             timeout=3600)  # 1 hour timeout for build

        if result.exit_status != 0:
            self.fail("Failed to build BCC: %s" % result.stderr.decode())

        self.log.info("BCC built successfully")

        build_dir = os.path.join(self.rpmbuild_dir, "BUILD")
        return build_dir

    def run_bcc_tests(self, build_dir):
        """
        Run BCC test suite
        """
        self.log.info("============== Running BCC tests =================")

        # Find the BCC source directory using pattern matching
        # SLES: /usr/src/packages/BUILD/bcc-*-build/bcc-*/build
        # RHEL: /root/rpmbuild/BUILD/bcc-*/redhat-linux-build

        bcc_dirs = [d for d in os.listdir(build_dir) if 'bcc-' in d]

        if not bcc_dirs:
            self.fail("BCC build directory not found in %s" % build_dir)

        # Sort to prioritize -build directories (SLES structure)
        bcc_dirs.sort(reverse=True)

        bcc_source_path = None

        # Search for the actual source directory
        for bcc_dir in bcc_dirs:
            candidate_path = os.path.join(build_dir, bcc_dir)

            if not os.path.isdir(candidate_path):
                continue

            # Check if this is a -build wrapper directory (SLES pattern: bcc-*-build)
            if bcc_dir.endswith('-build'):
                # Look for nested bcc-* directory inside
                nested_dirs = [d for d in os.listdir(candidate_path)
                               if d.startswith('bcc-') and os.path.isdir(os.path.join(candidate_path, d))]
                if nested_dirs:
                    bcc_source_path = os.path.join(
                        candidate_path, nested_dirs[0])
                    self.log.info("Found SLES nested structure: %s" %
                                  bcc_source_path)
                    break
            else:
                # Direct structure (RHEL pattern: bcc-*)
                bcc_source_path = candidate_path
                self.log.info("Found RHEL structure: %s" % bcc_source_path)
                break

        if not bcc_source_path:
            self.log.error("Available directories in %s:" % build_dir)
            for item in os.listdir(build_dir):
                self.log.error("  - %s" % item)
            self.fail("BCC source directory not found in %s" % build_dir)

        # Navigate to build directory (both SLES and RHEL use 'build/')
        bcc_build_path = os.path.join(bcc_source_path, "build")

        if not os.path.exists(bcc_build_path):
            self.log.error("Available directories in %s:" % bcc_source_path)
            for item in os.listdir(bcc_source_path):
                self.log.error("  - %s" % item)
            self.fail("BCC build directory not found at: %s" % bcc_build_path)

        os.chdir(bcc_build_path)
        self.log.info("Changed to BCC build directory: %s" % bcc_build_path)

        # Configure tests with cmake
        self.log.info("Configuring tests with cmake...")
        cmake_cmd = "cmake -DENABLE_TESTS=ON .."
        result = process.run(cmake_cmd, shell=True, ignore_status=True, sudo=True,
                             timeout=300)  # 5 minutes timeout for cmake

        if result.exit_status != 0:
            self.log.warning("cmake configuration had issues: %s" %
                             result.stderr.decode())
            self.log.info("Attempting to continue...")

        # Build tests
        self.log.info("Building test suite...")
        make_cmd = "make"
        result = process.run(make_cmd, shell=True, ignore_status=True, sudo=True,
                             timeout=1800)  # 30 minutes timeout for build

        if result.exit_status != 0:
            self.log.error("Build failed: %s" % result.stderr.decode())
            self.fail("Failed to build BCC tests")

        # Run tests with output logging
        self.log.info("Running BCC test suite...")
        cmd = "make test 2>&1 | tee bcc_test_output.log"
        result = process.run(cmd, shell=True, ignore_status=True, sudo=True,
                             timeout=1800)  # 30 minutes timeout for tests

        self.log.info("Test output saved to: bcc_test_output.log")
        self.log.info("Test output:\n%s" % result.stdout.decode())

        if result.exit_status != 0:
            self.log.warning(
                "Some tests failed. Re-running failed tests with detailed output...")

            # Rerun only failed tests with detailed output
            rerun_cmd = "ctest --rerun-failed --output-on-failure 2>&1 | tee bcc_failed_tests_rerun.log"
            rerun_result = process.run(rerun_cmd, shell=True, ignore_status=True, sudo=True,
                                       timeout=1800)  # 30 minutes timeout for rerun

            self.log.info(
                "Failed tests rerun output saved to: bcc_failed_tests_rerun.log")
            self.log.error("Failed tests output:\n%s" %
                           rerun_result.stdout.decode())

            self.fail(
                "BCC tests failed. Check logs:\n"
                "  - All tests: bcc_test_output.log\n"
                "  - Failed tests details: bcc_failed_tests_rerun.log"
            )

        self.log.info("BCC tests completed successfully")
        self.log.info("Test log available at: bcc_test_output.log")

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
