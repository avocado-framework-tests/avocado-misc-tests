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
# Copyright: 2016 IBM
# Author: Abdul Haleem <abdhalee@linux.vnet.ibm.com>

import os
import platform
import re
import glob
import shutil

from avocado import Test
from avocado.utils import build, process
from avocado.utils import distro
from avocado.utils import archive, git, linux_modules
from avocado.utils.software_manager.manager import SoftwareManager


class kselftest(Test):
    """
    Linux Kernel Selftest available as a part of kernel source code.
    run the selftest available at tools/testing/selftest

    :see: https://www.kernel.org/doc/Documentation/kselftest.txt
    :source: https://github.com/torvalds/linux/archive/master.zip

    :avocado: tags=kernel
    """
    testdir = 'tools/testing/selftests'

    def find_match(self, match_str, line):
        match = re.search(match_str, line)
        if match:
            self.error = True
            failed_test = match.group(0)
            # Clean up the test name for better readability
            failed_test = failed_test.strip()
            if failed_test not in self.failed_tests:
                self.failed_tests.append(failed_test)
            self.log.info("Testcase failed. Log from debug: %s" % failed_test)

    def setUp(self):
        """
        Resolve the packages dependencies and download the source.
        """
        smg = SoftwareManager()
        self.comp = self.params.get('comp', default='')
        self.kexec_symlink_created = False
        self.kexec_kernel_version = None
        self.subtest = self.params.get('subtest', default='')
        self._overlay_loaded = False
        if self.comp == "mm" and self.subtest == "ksm_tests":
            self.test_type = self.params.get('test_type', default='-H')
            self.Size_flag = self.params.get('Size', default='-s')
            self.Dup_MM_Area = self.params.get('Dup_MM_Area', default='100')
        if self.comp == "cpufreq":
            self.test_mode = self.params.get('test_mode', default='')
            self.testdir = 'tools/testing/selftests/cpufreq'
        if self.comp == "bpf":
            self.test_mode = self.params.get('test_mode', default='')
            self.testdir = 'tools/testing/selftests/bpf'

        self.build_option = self.params.get('build_option', default='-bp')
        self.run_type = self.params.get('type', default='upstream')
        self.detected_distro = distro.detect()
        if self.detected_distro.name == 'Ubuntu':
            self.distro_ver = int(self.detected_distro.version.split('.')[0])
        else:
            self.distro_ver = int(self.detected_distro.version)
        deps = ['gcc', 'make', 'automake', 'autoconf', 'rsync']
        if (self.comp == "powerpc"):
            if 'ppc' not in self.detected_distro.arch:
                self.cancel("Testing on a non powerpc platform")
        if self.detected_distro.name in ['Ubuntu', 'debian']:
            deps.extend(['libpopt0', 'libc6', 'libc6-dev', 'libcap-dev',
                         'libpopt-dev', 'libcap-ng0', 'libcap-ng-dev',
                         'libnuma-dev', 'libfuse-dev', 'elfutils', 'libelf-dev',
                         'libhugetlbfs-dev'])
        elif 'SuSE' in self.detected_distro.name:
            deps.extend(['glibc', 'glibc-devel', 'popt-devel', 'sudo',
                         'libcap2', 'libcap-devel', 'libcap-ng-devel',
                         'fuse', 'fuse-devel', 'glibc-devel-static',
                         'traceroute', 'iproute2', 'socat', 'libnuma-devel',
                         'coreutils'])
            if self.distro_ver >= 15:
                deps.extend(['libhugetlbfs-devel'])
            else:
                deps.extend(['libhugetlbfs-libhugetlb-devel'])
            if self.distro_ver >= 16:
                deps.extend(['libclang13'])
            else:
                deps.extend(['clang7'])
        elif self.detected_distro.name in ['centos', 'fedora', 'rhel']:
            deps.extend(['popt', 'glibc', 'glibc-devel', 'glibc-static',
                         'libcap-ng', 'libcap', 'libcap-devel',
                         'libcap-ng-devel', 'popt-devel',
                         'libhugetlbfs-devel', 'clang', 'traceroute',
                         'iproute-tc', 'socat', 'numactl-devel'])
            if self.detected_distro.name == 'rhel' and self.distro_ver >= 9:
                packages_remove = ['libhugetlbfs-devel']
                deps = list(set(deps)-set(packages_remove))
                deps.extend(['fuse3-devel', 'libasan'])
            else:
                deps.extend(['fuse-devel'])

        for package in deps:
            if not smg.check_installed(package) and not smg.install(package):
                self.cancel(
                    "Fail to install %s package" % (package))

        if self.run_type == 'custom' or self.run_type == 'upstream':
            if self.run_type == 'custom':
                linux_dir = self.params.get('linux_dir', default=None)
                if not linux_dir or not os.path.exists(linux_dir):
                    self.cancel(
                        "Custom kernel source directory %s does not exist" % (linux_dir))
                linux_dir = os.path.abspath(os.path.expanduser(linux_dir))
                if not os.path.exists(os.path.join(linux_dir, "tools/testing/selftests")):
                    self.cancel(
                        "Custom kernel source directory %s is not a valid kernel source" % linux_dir)
                if not os.path.exists(os.path.join(linux_dir, "Makefile")):
                    self.cancel(
                        "Custom kernel source directory %s lacks a Makefile" % linux_dir)
                path = [linux_dir]
            if self.run_type == 'upstream':
                location = self.params.get('location', default='https://github.c'
                                           'om/torvalds/linux/archive/master.zip')
                if re.match(r'^https|^git', location):
                    git_branch = self.params.get('branch', default='master')
                    path = ''
                    match = next(
                        (ext for ext in [".zip", ".tar", ".gz"] if ext in location), None)
                    if match:
                        tarball = self.fetch_asset("kselftest%s" % match,
                                                   locations=[location], expire='1d')
                        extracted_dir = archive.uncompress(
                            tarball, self.workdir)
                        path = glob.glob(os.path.join(
                            self.workdir, extracted_dir))
                    else:
                        git.get_repo(location, branch=git_branch,
                                     destination_dir=self.workdir)
                        path = glob.glob(self.workdir)
            for l_dir in path:
                if os.path.isdir(l_dir) and 'Makefile' in os.listdir(l_dir):
                    self.buldir = os.path.join(self.workdir, l_dir)
                    break
            self.sourcedir = os.path.join(self.buldir, self.testdir)
            if (self.comp != "cpufreq" and self.comp != "bpf"):
                if self.comp.startswith('filesystems'):
                    process.system("make headers_install -C %s" % self.buldir,
                                   shell=True, sudo=True, ignore_status=True)
                else:
                    process.system("make headers -C %s" % self.buldir,
                                   shell=True, sudo=True)
                # Only run 'make install' if no specific component is selected
                # Component-specific builds will be done later in the build phase
                if not self.comp:
                    process.system("make install -C %s" % self.sourcedir,
                                   shell=True, sudo=True)
            else:
                self.buldir = self.params.get('location', default='')
        else:
            # Make sure kernel source repo is configured
            if self.detected_distro.name in ['centos', 'fedora', 'rhel']:
                src_name = 'kernel'
                if self.detected_distro.name == 'rhel':
                    # Check for "el*a" where ALT always ends with 'a'
                    if platform.uname()[2].split(".")[-2].endswith('a'):
                        self.log.info('Using ALT as kernel source')
                        src_name = 'kernel-alt'
                self.buldir = smg.get_source(
                    src_name, self.workdir, self.build_option)
                self.buldir = os.path.join(
                    self.buldir, os.listdir(self.buldir)[0])
            elif self.detected_distro.name in ['Ubuntu', 'debian']:
                self.buldir = smg.get_source('linux', self.workdir)
            elif 'SuSE' in self.detected_distro.name:
                if not smg.check_installed("kernel-source") and not\
                        smg.install("kernel-source"):
                    self.cancel(
                        "Failed to install kernel-source for this test.")
                if not os.path.exists("/usr/src/linux"):
                    self.cancel("kernel source missing after install")
                self.buldir = "/usr/src/linux"

        self.sourcedir = os.path.join(self.buldir, self.testdir)
        if self.subtest == 'pmu/event_code_tests':
            pmu_test_dir = os.path.join(
                self.sourcedir, 'powerpc/pmu/event_code_tests')
            if not os.path.exists(pmu_test_dir):
                self.cancel("selftest not supported on distro")
        # cmsg_* tests from net/ subdirectory takes a lot of time to complete.
        # Until they have been root caused skip them.
        if self.comp == 'net':
            make_path = self.sourcedir + "/net/Makefile"
            process.system("sed -i 's/^.*cmsg_so_mark.sh/#&/g' %s" % make_path,
                           shell=True, sudo=True)
            process.system("sed -i 's/^.*cmsg_time.sh/#&/g' %s" % make_path,
                           shell=True, sudo=True)
        if (self.comp != "cpufreq" and self.comp != "bpf"):
            if self.comp.startswith('filesystems'):
                if self.comp == 'filesystems/mount-notify':
                    if (linux_modules.check_kernel_config('CONFIG_FANOTIFY')
                            == linux_modules.ModuleConfig.NOT_SET):
                        self.cancel("mount-notify requires CONFIG_FANOTIFY=y "
                                    "in the running kernel")
                if self.comp == 'filesystems/binderfs':
                    for mod, cfg in [('binder_linux', 'CONFIG_ANDROID_BINDER_IPC'),
                                     ('binderfs', 'CONFIG_ANDROID_BINDERFS')]:
                        status = linux_modules.check_kernel_config(cfg)
                        if status == linux_modules.ModuleConfig.NOT_SET:
                            self.cancel("binderfs requires %s in the running kernel" % cfg)
                        if status == linux_modules.ModuleConfig.MODULE:
                            if not linux_modules.module_is_loaded(mod):
                                if not linux_modules.load_module(mod):
                                    self.cancel("Failed to load module %s %s" % (mod, cfg))
                if self.comp == 'filesystems/overlayfs':
                    result = process.run("lsmod | grep -w overlay",
                                         shell=True, ignore_status=True)
                    if result.exit_status != 0:
                        process.system("modprobe overlay", shell=True, sudo=True)
                        self._overlay_loaded = True
            else:
                # Run make headers before building
                process.system("make headers -C %s" % self.buldir, shell=True,
                               sudo=True)
                build_str = '-C %s' % self.comp if self.comp else ''
                if build.make(self.sourcedir, extra_args='%s' % build_str):
                    self.fail("Compilation failed, Please check the build logs !!")
        # Fix for kexec test: Create vmlinuz symlink if only vmlinux exists
        # This handles SUSE systems that use vmlinux instead of vmlinuz
        if self.comp == "kexec":
            kernel_version = platform.uname()[2]
            vmlinuz_path = f"/boot/vmlinuz-{kernel_version}"
            vmlinux_path = f"/boot/vmlinux-{kernel_version}"
            if not os.path.exists(vmlinuz_path) and os.path.exists(vmlinux_path):
                self.log.info(f"Creating symlink {vmlinuz_path} -> {vmlinux_path} for kexec test")
                result = process.system(f"ln -sf {vmlinux_path} {vmlinuz_path}", shell=True, sudo=True, ignore_status=True)
                if result == 0:
                    self.kexec_symlink_created = True
                    self.kexec_kernel_version = kernel_version
                    self.log.info(f"Successfully created symlink for kernel version {kernel_version}")

    def test(self):
        """
        Execute the kernel selftest
        """
        self.error = False
        self.failed_tests = []
        kself_args = self.params.get("kself_args", default='')
        if self.comp == "bpf":
            self.bpf()
        elif self.comp == "cpufreq":
            self.cpufreq()
        else:
            if self.subtest == "ksm_tests":
                self.ksmtest()
            elif self.subtest == "mremap_test":
                self.mremaptest()
            else:
                if self.subtest:
                    test_comp = self.comp + "/" + self.subtest
                else:
                    test_comp = self.comp
                make_cmd = 'make -C %s %s -C %s run_tests' % (
                    self.sourcedir, kself_args, test_comp)
                self.result = process.run(
                    make_cmd, shell=True, ignore_status=True)
        log_output = (self.result.stdout + self.result.stderr).decode('utf-8')
        results_path = os.path.join(self.outputdir, 'raw_output')
        with open(results_path, 'w') as r_file:
            r_file.write(log_output)
        for line in open(results_path).readlines():
            if self.run_type == 'upstream':
                # Match both overall test failures and individual test failures
                self.find_match(r'not ok (.*) selftests:(.*)', line)
                self.find_match(r'# not ok \d+ .* # exit=\d+', line)
            elif self.run_type == 'distro':
                if self.detected_distro.name == 'SuSE' and\
                        self.distro_ver == 12:
                    self.find_match(r'selftests:(.*)\[FAIL\]', line)
                else:
                    # Match both overall test failures and individual test failures
                    self.find_match(r'not ok (.*) selftests:(.*)', line)
                    self.find_match(r'# not ok \d+ .* # exit=\d+', line)
        if self.result.exit_status != 0 and not self.error:
            self.fail("make run_tests exited with status %d (build or runtime "
                      "error — check raw_output for details)"
                      % self.result.exit_status)

        if self.error:
            # Build the summary message
            summary_lines = [
                "",
                "="*70,
                "FAILED SELFTESTS SUMMARY:",
                "="*70
            ]
            for idx, failed_test in enumerate(self.failed_tests, 1):
                summary_lines.append(f"{idx}. {failed_test}")
            summary_lines.extend([
                "="*70,
                f"Total failed tests: {len(self.failed_tests)}",
                "="*70,
                ""
            ])

            # Log the summary once in error log
            summary_msg = "\n".join(summary_lines)
            self.log.error(summary_msg)

            # Fail with a concise message (detailed summary already logged above)
            self.fail(f"Testcase failed during selftests. Total failed tests: {len(self.failed_tests)}")

    def run_cmd(self, cmd):
        """
        Run the command:
        Ex: ./ksm_tests -M
        """
        try:
            self.result = process.run(cmd, ignore_status=False, sudo=True)
            self.log.info(self.result)
        except process.CmdError as details:
            self.fail("Command %s failed: %s" % (cmd, details))

    def ksmtest(self):
        """
        Run the different ksm test types:
        Ex: -M (page merging)
        """
        ksm_test_dir = self.sourcedir + "/mm"
        ksm_test_bin = ksm_test_dir+"/ksm_tests"
        self.test_list = ["-M", "-Z", "-N", "-U", "-C"]
        if os.path.exists(ksm_test_bin):
            os.chdir(ksm_test_dir)
            if (self.test_type in ["-H", "-P"]):
                arg_payload = " ".join(["./ksm_tests", self.test_type,
                                       self.Size_flag, self.Dup_MM_Area])
                self.run_cmd(arg_payload)
            elif (self.test_type in self.test_list):
                arg_payload = " ".join(["./ksm_tests", self.test_type])
                self.run_cmd(arg_payload)
            else:
                self.cancel("Invalid test_type for ksm_tests:- {}"
                            .format(self.test_type))
        else:
            self.cancel("Invalid ksm_tests build path:- {}"
                        .format(ksm_test_dir))

    def mremaptest(self):
        """
        Run mremap test and validate performance for the PMD-source aligned and 4MB cases.
        Asserts that the src+dst PMD-aligned case is the fastest.
        """
        mremap_test_dir = os.path.join(self.sourcedir, "mm")
        mremap_test_bin = os.path.join(mremap_test_dir, "mremap_test")
        if not os.path.exists(mremap_test_bin):
            self.cancel("mremap_test binary not found at: %s" % mremap_test_bin)
        self.log.info("Running mremap_test from %s", mremap_test_dir)
        os.chdir(mremap_test_dir)
        try:
            self.result = process.run('./mremap_test',
                                      ignore_status=True,
                                      sudo=True)
        except process.CmdError as details:
            self.fail("Command ./mremap_test failed: %s" % details)
        output = self.result.stdout.decode('utf-8')
        self.log.info("Test output:\n%s", output)
        times = self.parse_mremap_times(output)
        if not times:
            self.log.warning("No 4MB PMD-source timing lines found in output")
            if self.result.exit_status != 0:
                self.fail("mremap_test failed with exit code: %d" % self.result.exit_status)
            return
        pmd_src_and_dest = {desc: ns for desc, ns in times.items()
                            if 'Destination PMD-aligned' in desc}
        pmd_src_only = {desc: ns for desc, ns in times.items()
                        if 'Destination PMD-aligned' not in desc}
        self.log.info("=" * 80)
        self.log.info("4MB mremap cases with Source PMD-aligned:")
        for desc, ns in sorted(times.items()):
            self.log.info("  %s: %d ns", desc, ns)
        self.log.info("=" * 80)
        if not pmd_src_and_dest:
            self.log.warning("'Source PMD-aligned, Destination PMD-aligned' 4MB case not found")
            if self.result.exit_status != 0:
                self.fail("mremap_test failed with exit code: %d" % self.result.exit_status)
            return
        time_pmd_both = min(pmd_src_and_dest.values())
        failures = []
        for desc, ns in pmd_src_only.items():
            if ns < time_pmd_both:
                msg = ("FAIL: '%s' (%d ns) is faster than "
                       "'Source PMD-aligned, Destination PMD-aligned' (%d ns)"
                       % (desc, ns, time_pmd_both))
                self.log.error(msg)
                failures.append(msg)
        if failures:
            self.log.error("=" * 80)
            self.log.error("PERFORMANCE VALIDATION FAILED:")
            self.log.error("For 4MB PMD-source mremap, the PMD+PMD case must be fastest!")
            for failure in failures:
                self.log.error("  - %s", failure)
            self.log.error("=" * 80)
            self.fail("Source+Dest PMD-aligned 4MB mremap is not the fastest. "
                      "See failures above.")
        else:
            self.log.info("=" * 80)
            self.log.info("SUCCESS: Source+Dest PMD-aligned 4MB mremap is fastest!")
            self.log.info("  PMD+PMD time : %d ns", time_pmd_both)
            if pmd_src_only:
                min_src_only = min(pmd_src_only.values())
                self.log.info("  Non-PMD-dest min time : %d ns", min_src_only)
                if time_pmd_both > 0:
                    self.log.info("  Performance improvement: %.2fx faster",
                                  min_src_only / time_pmd_both)
                else:
                    self.log.warning("Cannot calculate improvement: PMD+PMD time is zero")
            self.log.info("=" * 80)

    def parse_mremap_times(self, output):
        """
        Parse mremap_test output and return timings for the
        '4MB mremap - Source PMD-aligned' cases.
        Returns dict: test description -> time_ns
        """
        times = {}
        lines = output.split('\n')
        for i, line in enumerate(lines):
            if '4MB mremap - Source PMD-aligned' not in line:
                continue
            tap_match = re.search(r'^ok\s+\d+\s+(.+)', line)
            if not tap_match:
                continue
            test_desc = tap_match.group(1).strip()
            for next_line in lines[i + 1:i + 4]:
                time_match = re.search(r'mremap time:\s+(\d+)ns', next_line)
                if time_match:
                    time_ns = int(time_match.group(1))
                    times[test_desc] = time_ns
                    self.log.info("Found: %s = %d ns", test_desc, time_ns)
                    break
        return times

    def bpf(self):
        """
        Execute the kernel bpf selftests
        """
        self.sourcedir = os.path.join(self.buldir, self.testdir)
        os.chdir(self.sourcedir)
        build.make(self.sourcedir)
        build.make(self.sourcedir, extra_args='run_tests')

    def cpufreq(self):
        """
        Execute the kernel cpufreq selftests
        """
        os.chdir(self.sourcedir)
        cmd = "./main.sh -t " + self.test_mode
        self.run_cmd(cmd)

    def tearDown(self):
        self.log.info('Cleaning up')
        # Only remove the symlink if we created it and we have the exact kernel version
        if (getattr(self, 'kexec_symlink_created', False) and getattr(self, 'kexec_kernel_version', None) and self.comp == "kexec"):
            vmlinuz_path = f"/boot/vmlinuz-{self.kexec_kernel_version}"
            if os.path.islink(vmlinuz_path):
                self.log.info(f"Removing kexec symlink {vmlinuz_path} for kernel version {self.kexec_kernel_version}")
                process.system(f"rm -f {vmlinuz_path}",
                               shell=True, sudo=True, ignore_status=True)
            else:
                self.log.warning(f"Symlink {vmlinuz_path} no longer exists or is not a symlink, skipping removal")
        if getattr(self, '_overlay_loaded', False):
            process.system("rmmod overlay", shell=True, sudo=True,
                           ignore_status=True)
        if os.path.exists(self.workdir):
            shutil.rmtree(self.workdir)
