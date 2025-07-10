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
import shutil
from avocado import Test
from avocado.utils import distro, process, genio, cpu
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils.ssh import Session


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
        if 'PowerNV' in genio.read_file('/proc/cpuinfo'):
            self.cancel('This test is only supported on LPAR')
        process.run("dmesg -C")
        deps=["cmake"]
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

    def run_cmd(self, cmd):
        """
        run command on SUT as root
        """
        result = process.run(cmd, shell=True, ignore_status=True)
        output = result.stdout_text + result.stderr_text
        return output

    def install_google_benchmark(self):
        self.run_cmd("git clone https://github.com/google/benchmark.git")
        os.chdir("benchmark")
        self.run_cmd("git clone https://github.com/google/googletest.git")
        os.makedirs("build", exist_ok=True)
        os.chdir("build")
        self.run_cmd("cmake -DCMAKE_BUILD_TYPE=Release -DBENCHMARK_DOWNLOAD_DEPENDENCIES=ON ..")
        self.run_cmd(f"make -j$(nproc)")
        self.run_cmd("sudo make install")
        os.chdir("../../")

    def write_test_cpp(self):
        cpp_code = """
#include <benchmark/benchmark.h>

static __attribute__ ((noinline)) int my_really_big_function()
{
    for(size_t i = 0; i < 1000; ++i)
    {
        benchmark::DoNotOptimize(i % 5);
    }
    return 0;
}

static __attribute__ ((noinline)) void caller1()
{
    for(size_t i = 0; i < 1000; ++i)
    {
        benchmark::DoNotOptimize(my_really_big_function());
        benchmark::DoNotOptimize(i % 5);
    }
}

static __attribute__ ((noinline)) void myfun(benchmark::State& state)
{
    while(state.KeepRunning())
    {
        caller1();
    }
}

BENCHMARK(myfun);
BENCHMARK_MAIN();
"""
        with open("main.cpp", "w") as f:
            f.write(cpp_code)

    def compile_benchmark(self):
        self.run_cmd("clang++ main.cpp -o main -fno-omit-frame-pointer -O0 -lpthread -lbenchmark")

    def record_perf(self):
        self.run_cmd("perf record -g -o perf_output.data ./main")

    def get_perf_report(self):
        return self.run_cmd("perf report --sort dso,symbol --no-children -i perf_output.data --stdio").splitlines()

    def is_mangled(self, symbol):
        return re.match(r'^_Z[\w\d_]*$', symbol)

    def analyze_symbols(self, symbols):
        mangled = sum(1 for s in symbols if self.is_mangled(s))
        total = len(symbols)
        demangled = total - mangled
        return (
            (mangled / total) * 100 if total else 0,
            (demangled / total) * 100 if total else 0
        )

    def parse_report_and_test(self, lines):
        symbols = []
        for line in lines:
            match = re.search(r'\[\.\]\s+(.+)', line)
            if match:
                symbols.append(match.group(1).strip())

        mangled_pct, demangled_pct = self.analyze_symbols(symbols)
        print(f"\n[*] Total symbols: {len(symbols)}")
        print(f"[+] Mangled: {mangled_pct:.2f}%, Demangled: {demangled_pct:.2f}%")

        self.assertGreaterEqual(demangled_pct, 35, "[FAIL] Symbols appear to be mostly mangled.")

    def cleanup(self):
        for path in ["benchmark", "main.cpp", "main", "perf.data"]:
            if os.path.exists(path):
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)

    def test_demangle(self):
        self.install_google_benchmark()
        self.write_test_cpp()
        self.compile_benchmark()
        self.record_perf()
        report_lines = self.get_perf_report()
        self.parse_report_and_test(report_lines)

    def tearDown(self):
        """
        tear down function to remove non root user.
        """
        self.run_cmd("dmesg -T")
        self.cleanup()