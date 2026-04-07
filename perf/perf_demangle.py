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

import os
import re
from avocado import Test
from avocado.utils import distro, process, git, build
from avocado.utils.software_manager.manager import SoftwareManager


class demangle(Test):
    """
    This is a test class for demangle feature in perf record report for C++ workloads.
    """

    def setUp(self):
        '''
        Install the basic packages to support perf
        '''
        smm = SoftwareManager()
        detected_distro = distro.detect()
        if 'ppc64' not in detected_distro.arch:
            self.cancel('This test is not supported on %s architecture'
                        % detected_distro.arch)
        process.run("dmesg -C")
        deps = ["cmake", "make", "git", "perf"]
        if "sles" in detected_distro.name.lower():
            major_version = int(detected_distro.version.split('.')[0])
            if major_version > 15:
                deps += ["libclang13", "libLLVM17"]
            else:
                deps += ["llvm7", "clang7"]
        else:
            deps += ["clang", "llvm"]
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel(f"{package} is needed for the test to be run")

    def run_cmd(self, cmd):
        """
        run command on SUT as root
        """
        result = process.run(cmd, shell=True)
        output = result.stdout_text + result.stderr_text
        return output

    def _install_google_benchmark(self):
        """
        Install Google benchmark and Googletest
        """
        benchmark_path = os.path.join(self.workdir, "benchmark")
        git.get_repo('https://github.com/google/benchmark.git',
                     branch='main', destination_dir=benchmark_path)
        gtest_path = os.path.join(benchmark_path, "googletest")
        git.get_repo('https://github.com/google/googletest.git',
                     branch='main', destination_dir=gtest_path)
        build_dir = os.path.join(benchmark_path, "build")
        os.makedirs(build_dir, exist_ok=True)
        os.chdir(build_dir)
        self.run_cmd(
            "cmake -DCMAKE_BUILD_TYPE=Release -DBENCHMARK_DOWNLOAD_DEPENDENCIES=ON ..")
        build.make('.')
        build.make('.', extra_args='install')

        # Return to data working directory
        os.chdir(self.workdir)

    def _compile_benchmark(self):
        source_path = self.get_data('benchmark_main.cpp')
        self.run_cmd(
            f"clang++ {source_path} -o main -fno-omit-frame-pointer -O0 -lpthread -lbenchmark")

    def _record_perf(self):
        self.run_cmd("perf record -g -o perf_output.data ./main")

    def _get_perf_report(self):
        return self.run_cmd(
            "perf report --sort dso,symbol --no-children -i perf_output.data --stdio").splitlines()

    def _is_mangled(self, symbol):
        return re.match(r'^_Z[\w\d_]*$', symbol)

    def _analyze_symbols(self, symbols):
        mangled = sum(1 for s in symbols if self._is_mangled(s))
        total = len(symbols)
        demangled = total - mangled
        return (
            (mangled / total) * 100 if total else 0,
            (demangled / total) * 100 if total else 0
        )

    def _parse_report_and_test(self, lines):
        symbols = []
        for line in lines:
            match = re.search(r'\[\.\]\s+(.+)', line)
            if match:
                symbols.append(match.group(1).strip())

        mangled_pct, demangled_pct = self._analyze_symbols(symbols)
        self.log.info(f"\n[*] Total symbols: {len(symbols)}")
        self.log.info(
            f"[+] Mangled: {mangled_pct:.2f}%, Demangled: {demangled_pct:.2f}%")

        self.assertGreaterEqual(
            demangled_pct,
            70,
            "[FAIL] Symbols appear to be mostly mangled.")

    def test_demangle(self):
        self._install_google_benchmark()
        self._compile_benchmark()
        self._record_perf()
        report_lines = self._get_perf_report()
        self._parse_report_and_test(report_lines)

    def tearDown(self):
        """
        tear down function to clear dmesg and other files.
        """
        self.run_cmd("dmesg -T")
        for path in ["perf_output.data", "main"]:
            if os.path.exists(path):
                os.remove(path)
