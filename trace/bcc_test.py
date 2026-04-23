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
#
# Test to validate BCC (BPF Compiler Collection) Test Suite

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
        smm = SoftwareManager()
        self.detected_distro = distro.detect()
        self.distro_name = self.detected_distro.name

        self.is_rhel = self.distro_name in ['rhel', 'centos', 'fedora']
        self.is_sles = (
            "sles" in self.distro_name.lower() or self.distro_name == 'SuSE'
        )
        if not (self.is_rhel or self.is_sles):
            self.cancel(
                "BCC test is currently supported only on "
                "RHEL/CentOS/Fedora and SLES"
            )

        self.log.info("Detected distribution: %s" % self.distro_name)

        deps = [
            'rpm-build', 'rpmdevtools', 'netperf',
            'gcc', 'gcc-c++', 'make', 'automake', 'autoconf', 'libtool',
            'bison', 'clang-devel', 'cmake', 'flex', 'llvm-devel',
            'ncurses-devel', 'libxml2-devel'
        ]

        # Add distribution-specific dependencies
        if self.is_rhel:
            deps.extend([
                'dnf-plugins-core', 'pkgconfig', 'bpftool',
                'elfutils-debuginfod-client-devel', 'elfutils-libelf-devel',
                'libbpf-devel', 'libbpf-static', 'libbpf', 'iperf3'
            ])
        else:  # SLES
            deps.extend(['pkg-config', 'libelf-devel', 'iperf'])

        self.log.info(
            "Installing BCC dependencies for %s..." % self.distro_name)
        failed_packages = []

        for package in deps:
            if not smm.check_installed(package):
                self.log.info("Installing package: %s" % package)
                if not smm.install(package):
                    self.log.warning("Failed to install %s" % package)
                    failed_packages.append(package)

        if failed_packages:
            self.cancel("Failed to install required packages: %s. "
                        % ', '.join(failed_packages))

        self.log.info("Installing Python dependencies...")
        pip_cmd = "pip3 install pyroute2 netaddr"
        result = process.run(
            pip_cmd, shell=True, ignore_status=True, sudo=True
        )

        if result.exit_status != 0:
            self.cancel(
                "Failed to install pyroute2: %s"
                % result.stderr.decode()
            )
        else:
            self.log.info("pyroute2 installed successfully")

        # Set up build directory
        self.build_dir = os.path.join(self.workdir, 'bcc_build')
        os.makedirs(self.build_dir, exist_ok=True)
        os.chdir(self.build_dir)

        self.log.info("Setup completed successfully")

    def download_bcc_source(self):
        """
        Download BCC source RPM
        """
        self.log.info("==== Downloading BCC source RPM ====")

        if self.is_rhel:
            cmd = "dnf --source download bcc"
        else:
            cmd = "zypper source-install -d bcc"

        result = process.run(cmd, shell=True, ignore_status=True, sudo=True)

        if result.exit_status != 0:
            self.fail(
                "Failed to download BCC source RPM: %s"
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

        # Get the home directory for rpmbuild
        home_dir = os.path.expanduser("~")
        specs_dir = os.path.join(home_dir, "rpmbuild", "SPECS")

        if not os.path.exists(specs_dir):
            self.fail("rpmbuild/SPECS directory not found at %s" % specs_dir)

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

        self.log.info("Building BCC package...")
        cmd = "rpmbuild -bc --noclean bcc.spec"
        result = process.run(cmd, shell=True, ignore_status=True, sudo=True,
                             timeout=3600)  # 1 hour timeout for build

        if result.exit_status != 0:
            self.fail("Failed to build BCC: %s" % result.stderr.decode())

        self.log.info("BCC built successfully")

        build_dir = os.path.join(home_dir, "rpmbuild", "BUILD")
        return build_dir

    def run_bcc_tests(self, build_dir):
        """
        Run BCC test suite
        """
        self.log.info("============== Running BCC tests =================")

        # Find the BCC build directory
        bcc_dirs = [d for d in os.listdir(build_dir) if d.startswith('bcc-')]

        if not bcc_dirs:
            self.fail("BCC build directory not found in %s" % build_dir)

        bcc_base_path = os.path.join(build_dir, bcc_dirs[0])

        # Try different build directory names based on distribution
        possible_build_dirs = [
            "redhat-linux-build",  # RHEL/CentOS/Fedora
            "suse-linux-build",    # SLES
            "build"                # Generic fallback
        ]

        bcc_build_path = None
        for build_subdir in possible_build_dirs:
            test_path = os.path.join(bcc_base_path, build_subdir)
            if os.path.exists(test_path):
                bcc_build_path = test_path
                self.log.info("Found build directory: %s" % build_subdir)
                break

        if not bcc_build_path:
            # If none of the standard directories exist, list what's available
            self.log.error("Available directories in %s:" % bcc_base_path)
            for item in os.listdir(bcc_base_path):
                self.log.error("  - %s" % item)
            self.fail(
                "BCC build directory not found. Tried: %s"
                % ', '.join(possible_build_dirs)
            )

        os.chdir(bcc_build_path)
        self.log.info("Changed to BCC build directory: %s" % bcc_build_path)

        self.log.info("Running BCC test suite...")
        cmd = "make test"
        result = process.run(cmd, shell=True, ignore_status=True, sudo=True,
                             timeout=1800)  # 30 minutes timeout for tests

        self.log.info("Test output:\n%s" % result.stdout.decode())

        if result.exit_status != 0:
            self.log.error("Test stderr:\n%s" % result.stderr.decode())
            self.fail(
                "BCC tests failed with exit code %d"
                % result.exit_status
            )

        self.log.info("BCC tests completed successfully")

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
        """
        self.log.info("Cleaning up test environment")

        if os.path.exists(self.build_dir):
            shutil.rmtree(self.build_dir, ignore_errors=True)
