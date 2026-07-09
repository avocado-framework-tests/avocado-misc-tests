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
# Author: Harish <harisrir@linux.vnet.ibm.com>
# Modified by: Samir <samir@linux.ibm.com>
#
# Based on code by Sudhir Kumar <skumar@linux.vnet.ibm.com>
#   copyright: 2009 IBM
#   https://github.com/autotest/autotest-client-tests/tree/master/ebizzy

import os
import json
import re
import platform
import math

from avocado import Test
from avocado.utils import archive
from avocado.utils import distro
from avocado.utils import process
from avocado.utils import build
from avocado.utils import cpu
from avocado.utils.software_manager.manager import SoftwareManager


class Ebizzy(Test):

    '''
    ebizzy is designed to generate a workload resembling common web application
    server workloads. It is highly threaded, has a large in-memory working set,
    and allocates and deallocates memory frequently.

    :avocado: tags=cpu
    '''

    def setUp(self):
        '''
        Build ebizzy
        Source:
        https://sourceforge.net/projects/ebizzy/files/ebizzy/0.3
        /ebizzy-0.3.tar.gz
        '''
        sm = SoftwareManager()
        distro_name = distro.detect().name
        deps = ['gcc', 'make', 'patch', 'numactl']
        if 'Ubuntu' in distro_name:
            deps.extend(['linux-tools-common', 'linux-tools-%s' %
                         platform.uname()[2]])
        elif distro_name in ['rhel', 'SuSE', 'fedora', 'centos']:
            deps.extend(['perf'])
        else:
            self.cancel("Install the package for perf supported \
                         by %s" % distro_name)

        for package in deps:
            if not sm.check_installed(package) and not sm.install(package):
                self.cancel("%s is needed for the test to be run" % package)
        url = 'http://sourceforge.net/projects/ebizzy/files/ebizzy/' \
              '0.3/ebizzy-0.3.tar.gz'
        tarball = self.fetch_asset(self.params.get("ebizy_url", default=url))
        archive.extract(tarball, self.workdir)
        version = os.path.basename(tarball.split('.tar.')[0])
        self.sourcedir = os.path.join(self.workdir, version)

        patch = self.params.get(
            'patch', default='Fix-build-issues-with-ebizzy.patch')
        patch_cmd = 'patch -p0 < %s' % os.path.abspath((self.get_data(patch)))
        os.chdir(self.sourcedir)
        process.run(patch_cmd, shell=True)
        process.run('[ -x configure ] && ./configure', shell=True)
        build.make(self.sourcedir)

        # Get CPU information
        self.cpu_count = cpu.online_count()
        self.log.info(f"Detected {self.cpu_count} online CPUs")

        # Get the arguments for ebizzy workload from YAML file
        self.iterations = self.params.get('iterations', default=10)

    def _get_numa_nodes(self):
        """
        Detect available NUMA nodes and their CPU lists
        Returns: dict with node_id: cpu_list mapping
        """
        numa_nodes = {}
        try:
            output = process.system_output(
                "numactl --hardware", shell=True).decode()
            for line in output.splitlines():
                if line.startswith("node") and "cpus:" in line:
                    match = re.match(r'node (\d+) cpus: (.*)', line)
                    if match:
                        node_id = int(match.group(1))
                        cpus = match.group(2).strip()
                        numa_nodes[node_id] = cpus
            self.log.info(f"Detected NUMA nodes: {numa_nodes}")
        except Exception as e:
            self.log.warning(f"Failed to detect NUMA nodes: {e}")
        return numa_nodes

    def _parse_ebizzy_output(self, output):
        """
        Parse ebizzy output to extract records/sec
        """
        records_per_sec = []
        for line in output.splitlines():
            if "records/s" in line:
                match = re.search(r'(\d+\.?\d*)\s+records/s', line)
                if match:
                    records_per_sec.append(float(match.group(1)))
        return records_per_sec

    def _create_test_directory(self, test_dir_name):
        """
        Create a directory for storing test results

        Args:
            test_dir_name: Name of the directory to create

        Returns:
            Full path to the created directory
        """
        test_dir = os.path.join(self.logdir, test_dir_name)
        if not os.path.exists(test_dir):
            os.makedirs(test_dir)
        return test_dir

    def _save_iteration_results(self, test_dir, iteration, data):
        """
        Save iteration results to JSON file

        Args:
            test_dir: Directory to save results
            iteration: Iteration number
            data: Dictionary containing iteration data
        """
        json_file = os.path.join(test_dir, f"ebizzy[{iteration}].json")
        try:
            with open(json_file, 'w') as f:
                json.dump(data, f, indent=4)
            self.log.info(
                f"Saved iteration {iteration} results to {json_file}")
        except Exception as e:
            self.log.error(
                f"Failed to save iteration {iteration} results: {e}")

    def _save_summary_log(self, test_dir, test_name, results):
        """
        Save summary statistics to log file

        Args:
            test_dir: Directory to save log
            test_name: Name of the test
            results: Dictionary containing all results
        """
        log_file = os.path.join(test_dir, "ebizzy.log")
        try:
            with open(log_file, 'w') as f:
                f.write(f"{'='*60}\n")
                f.write(f"Summary for {test_name}\n")
                f.write(f"{'='*60}\n\n")

                for metric, values in results.items():
                    if values:
                        avg = sum(values) / len(values)
                        min_val = min(values)
                        max_val = max(values)
                        f.write(f"{metric}:\n")
                        f.write(f"  Average: {avg:.2f}\n")
                        f.write(f"  Min: {min_val:.2f}\n")
                        f.write(f"  Max: {max_val:.2f}\n")
                        f.write(f"  All values: {values}\n\n")

                f.write(f"{'='*60}\n")

            self.log.info(f"Saved summary log to {log_file}")
        except Exception as e:
            self.log.error(f"Failed to save summary log: {e}")

    def _run_ebizzy_with_perf(self, threads, cpu_list, test_name,
                              iterations=10, test_dir_name=None):
        """
        Run ebizzy with perf stat for performance metrics collection

        Args:
            threads: Number of threads to use
            cpu_list: CPU list for taskset (e.g., "0" or "0-3")
            test_name: Name of the test for logging
            iterations: Number of iterations to run
            test_dir_name: Directory name for storing results (optional)
        """
        results = {
            'records_per_sec': [],
            'cpu_usage': [],
            'execution_time': [],
            'context_switches': []
        }

        # Create test directory if specified
        test_dir = None
        if test_dir_name:
            test_dir = self._create_test_directory(test_dir_name)

        for i in range(iterations):
            self.log.info(f"{test_name} - Iteration {i+1}/{iterations}")

            # Build the command with perf stat and taskset
            cmd = (f"perf stat -a taskset -c {cpu_list} "
                   f"{self.sourcedir}/ebizzy -m -n 1000 -P -R -s 512000 \
                           -S 100 -t {threads}")

            iteration_data = {
                'iteration': i,
                'test_name': test_name,
                'threads': threads,
                'cpu_list': cpu_list,
                'command': cmd
            }

            try:
                result = process.run(cmd, shell=True, ignore_status=True,
                                     timeout=300, verbose=True)

                # Parse ebizzy output for records/sec
                stdout = result.stdout_text if hasattr(
                    result, 'stdout_text') else result.stdout.decode()
                stderr = result.stderr_text if hasattr(
                    result, 'stderr_text') else result.stderr.decode()

                iteration_data['stdout'] = stdout
                iteration_data['stderr'] = stderr
                iteration_data['exit_code'] = result.exit_status

                records = self._parse_ebizzy_output(stdout)
                if records:
                    avg_records = sum(records) / len(records)
                    results['records_per_sec'].append(avg_records)
                    iteration_data['records_per_sec'] = avg_records
                    self.log.info(f"  Records/sec: {avg_records:.2f}")

                # Parse perf stat output for metrics
                cpu_usage = None
                exec_time = None
                ctx_switches = None

                for line in stderr.splitlines():
                    # CPU usage
                    if "CPUs utilized" in line:
                        match = re.search(r'(\d+\.?\d*)\s+CPUs utilized', line)
                        if match:
                            cpu_usage = float(match.group(1))
                            results['cpu_usage'].append(cpu_usage)

                    # Execution time
                    if "seconds time elapsed" in line:
                        match = re.search(
                            r'(\d+\.?\d*)\s+seconds time elapsed', line)
                        if match:
                            exec_time = float(match.group(1))
                            results['execution_time'].append(exec_time)

                    # Context switches
                    if "context-switches" in line:
                        match = re.search(r'([\d,]+)\s+context-switches', line)
                        if match:
                            ctx_switches = int(match.group(1).replace(',', ''))
                            results['context_switches'].append(ctx_switches)

                iteration_data['cpu_usage'] = cpu_usage
                iteration_data['execution_time'] = exec_time
                iteration_data['context_switches'] = ctx_switches

                # Save iteration results to JSON file
                if test_dir:
                    self._save_iteration_results(test_dir, i, iteration_data)

            except Exception as e:
                self.log.error(f"Iteration {i+1} failed: {e}")
                iteration_data['error'] = str(e)
                if test_dir:
                    self._save_iteration_results(test_dir, i, iteration_data)
                continue

        # Save summary log
        if test_dir:
            self._save_summary_log(test_dir, test_name, results)

        # Calculate and log summary statistics
        self._log_summary(test_name, results)
        return results

    def _log_summary(self, test_name, results):
        """
        Log summary statistics for the test results
        """
        self.log.info(f"\n{'='*60}")
        self.log.info(f"Summary for {test_name}")
        self.log.info(f"{'='*60}")

        for metric, values in results.items():
            if values:
                avg = sum(values) / len(values)
                min_val = min(values)
                max_val = max(values)
                self.log.info(f"{metric}:")
                self.log.info(f"  Average: {avg:.2f}")
                self.log.info(f"  Min: {min_val:.2f}")
                self.log.info(f"  Max: {max_val:.2f}")

        self.log.info(f"{'='*60}\n")

    def create_json_dump(self, stdout_output):
        # Define regex patterns to capture the data
        patterns = {
            'cpu_clock': r'([\d.]+)\s+msec cpu-clock',
            'context_switches': r'([\d.]+)\s+context-switches',
            'cpu_migrations': r'([\d.]+)\s+cpu-migrations',
            'page_faults': r'([\d.]+)\s+page-faults',
            'cycles': r'([\d.]+)\s+cycles',
            'instructions': r'([\d.]+)\s+instructions',
            'branches': r'([\d.]+)\s+branches',
            'branch_misses': r'([\d.]+)\s+branch-misses',
            'elapsed_time': r'([\d.]+)\s+seconds elapsed'
        }

        # Extract data using regex
        extracted_data = {}
        for key, pattern in patterns.items():
            match = re.search(pattern, stdout_output)
            if match:
                extracted_data[key] = float(match.group(1))

        return extracted_data

    def test(self):
        ebizzy_payload = []
        ebizzy_dir = self.logdir + "/ebizzy_workload"
        os.makedirs(ebizzy_dir, exist_ok=True)
        iterations = self.params.get('iterations', default=2)
        perfstat = self.params.get('perfstat', default='')
        if perfstat:
            perfstat = 'perf stat ' + perfstat
        taskset = self.params.get('taskset', default='')
        if taskset:
            taskset = 'taskset -c ' + taskset
        args = self.params.get('args', default='')
        num_chunks = self.params.get('num_chunks', default=1000)
        chunk_size = self.params.get('chunk_size', default=512000)
        seconds = self.params.get('seconds', default=100)
        num_threads = self.params.get('num_threads', default=100)
        args2 = '-m -n %s -P -R -s %s -S %s -t %s' % (num_chunks, chunk_size,
                                                      seconds, num_threads)
        args = args + ' ' + args2

        os.makedirs(os.path.join(self.logdir, "ebizzy_run"))
        for ite in range(iterations):
            results = process.run('%s %s %s/ebizzy %s'
                                  % (perfstat, taskset, self.sourcedir, args))
            stderr_output = results.stderr
            stdout_output = results.stdout
            ebizzy_payload = ebizzy_dir + "/ebizzy.log"
            with open(ebizzy_payload, "a") as payload:
                payload.write("==================Iteration {}============= \
                        \n".format(str(ite)))
                lines = stdout_output.splitlines()
                lines1 = stderr_output.splitlines()
                ebizzy_payload = lines + lines1
                for line in ebizzy_payload:
                    decoded_string = line.decode('utf-8')
                    cleaned_string = decoded_string.lstrip('\t')
                    payload.write(cleaned_string + '\n')

            pattern = re.compile(r"(.*?) records/s")
            records = pattern.findall(stdout_output.decode("utf-8"))[0]
            pattern = re.compile(r"real (.*?) s")
            real = pattern.findall(stdout_output.decode("utf-8"))[0].strip()
            pattern = re.compile(r"user (.*?) s")
            usr_time = pattern.findall(
                stdout_output.decode("utf-8"))[0].strip()
            pattern = re.compile(r"sys (.*?) s")
            sys_time = pattern.findall(
                stdout_output.decode("utf-8"))[0].strip()
            perf_stat = self.create_json_dump(stderr_output.decode("utf-8"))
            json_object = json.dumps({'records': records,
                                      'real_time': real,
                                      'user': usr_time,
                                      'sys': sys_time,
                                      'perf_stat': perf_stat})

            logfile = os.path.join(
                self.logdir, "ebizzy_run", "run_%s.json" % (ite + 1))
            ebizzy_log = ebizzy_dir + "/ebizzy[" + str(ite) + "].json"
            with open(ebizzy_log, "w") as outfile:
                outfile.write(json_object)

    def test_ebizzy_50_percent_load(self):
        """
        Test ebizzy with 50% CPU load
        Calculate threads = (CPU_count * 0.5)
        Pin to specific CPUs using taskset
        Run 10 iterations
        Collect: records/sec, CPU usage, execution time
        """
        threads = max(1, int(self.cpu_count * 0.5))
        cpu_list = f"0-{threads-1}" if threads > 1 else "0"

        self.log.info(
            f"Running 50% load test with {threads} threads on CPUs {cpu_list}")

        results = self._run_ebizzy_with_perf(
            threads=threads,
            cpu_list=cpu_list,
            test_name="50% CPU Load",
            iterations=self.iterations,
            test_dir_name="ebizzy_workload"
        )

        # Verify we got results
        if not results['records_per_sec']:
            self.fail("No performance data collected for 50% load test")

    def test_ebizzy_100_percent_load(self):
        """
        Test ebizzy with 100% CPU load
        Calculate threads = CPU_count
        Pin to all available CPUs
        Run 10 iterations
        Collect same metrics
        """
        threads = self.cpu_count
        cpu_list = f"0-{self.cpu_count-1}"

        self.log.info(
            f"Running 100% load test with {threads} threads on CPUs \
                    {cpu_list}")

        results = self._run_ebizzy_with_perf(
            threads=threads,
            cpu_list=cpu_list,
            test_name="100% CPU Load",
            iterations=self.iterations,
            test_dir_name="ebizzy_workload"
        )

        # Verify we got results
        if not results['records_per_sec']:
            self.fail("No performance data collected for 100% load test")

    def test_ebizzy_120_percent_overcommit(self):
        """
        Test ebizzy with 120% CPU overcommit
        Calculate threads = (CPU_count * 1.2)
        Pin to all CPUs (overcommitted)
        Run 10 iterations
        Collect same metrics + context switches
        """
        threads = max(1, int(math.ceil(self.cpu_count * 1.2)))
        cpu_list = f"0-{self.cpu_count-1}"

        self.log.info(
            f"Running 120% overcommit test with {threads} threads on CPUs \
                    {cpu_list}")
        self.log.info(
            f"Overcommit ratio: {threads}/{self.cpu_count} = \
                    {threads/self.cpu_count:.2f}")

        results = self._run_ebizzy_with_perf(
            threads=threads,
            cpu_list=cpu_list,
            test_name="120% CPU Overcommit",
            iterations=self.iterations,
            test_dir_name="ebizzy_workload"
        )

        # Verify we got results
        if not results['records_per_sec']:
            self.fail("No performance data collected for 120% overcommit test")

        # Log context switch information for overcommit analysis
        if results['context_switches']:
            avg_ctx_switches = sum(
                results['context_switches']) / len(results['context_switches'])
            self.log.info(f"Average context switches: {avg_ctx_switches:.0f}")

    def test_ebizzy_single_cpu_pinning(self):
        """
        Enhanced single CPU pinning test
        Pin all threads to CPU0
        Multiple thread counts: 1, 2, 4, 8
        Collect contention metrics
        """
        thread_counts = [1, 2, 4, 8]
        cpu_list = "0"

        for threads in thread_counts:
            self.log.info(
                f"\nRunning single CPU pinning test with {threads} \
                        threads on CPU {cpu_list}")

            results = self._run_ebizzy_with_perf(
                threads=threads,
                cpu_list=cpu_list,
                test_name=f"Single CPU Pinning ({threads} threads)",
                iterations=self.iterations,
                test_dir_name="ebizzy_workload"
            )

            # Analyze contention
            if results['context_switches']:
                avg_ctx_switches = sum(
                    results['context_switches']) / \
                    len(results['context_switches'])
                self.log.info(
                    f"Contention metric - Avg context switches: \
                            {avg_ctx_switches:.0f}")

            # Verify we got results
            if not results['records_per_sec']:
                self.log.warning(
                    f"No performance data collected for {threads} \
                            threads on single CPU")

    def test_ebizzy_numa_node_pinning(self):
        """
        Test ebizzy with NUMA node pinning
        Detect NUMA nodes
        Pin threads to specific NUMA nodes
        Test cross-node vs same-node performance
        """
        numa_nodes = self._get_numa_nodes()

        if not numa_nodes:
            self.cancel("No NUMA nodes detected, skipping NUMA pinning test")

        if len(numa_nodes) < 2:
            self.log.warning(
                "Only one NUMA node detected, limited NUMA testing possible")

        # Test 1: Pin to first NUMA node
        for node_id, cpu_list in numa_nodes.items():
            cpus = cpu_list.split()
            if not cpus:
                continue

            # Calculate threads based on CPUs in this node
            node_cpu_count = len(cpus)
            threads = max(1, node_cpu_count)

            # Create CPU range for taskset
            cpu_range = cpu_list.replace(' ', ',')

            self.log.info(f"\nRunning NUMA node {node_id} pinning test")
            self.log.info(f"CPUs in node: {cpu_list}")
            self.log.info(f"Using {threads} threads")

            results = self._run_ebizzy_with_perf(
                threads=threads,
                cpu_list=cpu_range,
                test_name=f"NUMA Node {node_id} Pinning",
                iterations=self.iterations,
                test_dir_name="ebizzy_workload"
            )

            # Verify we got results
            if not results['records_per_sec']:
                self.log.warning(
                    f"No performance data collected for NUMA node {node_id}")

        # Test 2: Cross-node test if multiple NUMA nodes exist
        if len(numa_nodes) >= 2:
            self.log.info("\nRunning cross-NUMA node test")

            # Use half threads from each of first two nodes
            node_ids = sorted(numa_nodes.keys())[:2]
            all_cpus = []
            total_threads = 0

            for node_id in node_ids:
                cpus = numa_nodes[node_id].split()
                node_cpu_count = len(cpus)
                threads_per_node = max(1, node_cpu_count // 2)
                all_cpus.extend(cpus[:threads_per_node])
                total_threads += threads_per_node

            cpu_range = ','.join(all_cpus)

            self.log.info(f"Cross-node CPUs: {cpu_range}")
            self.log.info(f"Total threads: {total_threads}")

            results = self._run_ebizzy_with_perf(
                threads=total_threads,
                cpu_list=cpu_range,
                test_name="Cross-NUMA Node",
                iterations=self.iterations,
                test_dir_name="ebizzy_workload"
            )

            # Verify we got results
            if not results['records_per_sec']:
                self.log.warning(
                    "No performance data collected for cross-NUMA test")
