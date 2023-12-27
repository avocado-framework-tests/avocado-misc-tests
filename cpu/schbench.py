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
# Author: Abhishek Goel<huntbag@linux.vnet.ibm.com>
# Update: Aboorva Devarajan<aboorvad@linux.vnet.ibm.com>

import json
import os
import platform
import re

from avocado import Test
from avocado.utils import process
from avocado.utils import build, distro, git
from avocado.utils.software_manager.manager import SoftwareManager


class Schbench(Test):

    '''
    schbench is designed to provide detailed latency distributions for scheduler
    wakeups.

    :avocado: tags=cpu
    '''

    def setUp(self):
        '''
        Build schbench
        Source:
        https://git.kernel.org/pub/scm/linux/kernel/git/mason/schbench.git
        '''
        sm = SoftwareManager()
        distro_name = distro.detect().name
        deps = ['gcc', 'make']
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
        url = 'https://git.kernel.org/pub/scm/linux/kernel/git/mason/schbench.git'
        schbench_url = self.params.get("schbench_url", default=url)

        git.get_repo(schbench_url, destination_dir=self.workdir)
        os.chdir(self.workdir)
        build.make(self.workdir)

    def parse_schbench_data(self, data):
        results = {}
        current_category = None
        current_percentiles = None
        category_mapping = {
            "Wakeup Latencies percentiles": "wakeup_latencies_percentiles",
            "Request Latencies percentiles": "request_latencies_percentiles",
            "RPS percentiles (requests)": "rps_percentiles",
        }
        # Find the last occurrence of "Wakeup Latencies percentiles"
        last_occurrence_index = -1
        for i, line in enumerate(data):
            if "Wakeup Latencies percentiles" in line:
                last_occurrence_index = i
        # Process data starting from the last occurrence
        if last_occurrence_index != -1:
            current_category = None
            current_percentiles = None
            data = data[last_occurrence_index:]
            for line in data:
                for category_name, category_key in category_mapping.items():
                    if category_name in line:
                        current_category = category_key
                        current_percentiles = results.setdefault(
                            current_category, {
                                "percentiles": [],
                                "min_max": {}
                            })
                        break  # Exit the loop once a match is found
                if current_category and line.strip():
                    match = re.match(
                        r'\s*(\*?)\s*(\d+\.\d+)th: (\d+)\s+\((\d+) samples\)',
                        line)
                    if match:
                        percentile, latency, samples = match.group(
                            2), match.group(3), match.group(4)
                        current_percentile = {
                            f"percentile_{percentile}": {
                                "latency": latency,
                                "samples": samples
                            }
                        }
                        current_percentiles["percentiles"].append(
                            current_percentile)
                    elif "min=" in line:
                        min_max_match = re.match(r'\s*min=(\d+), max=(\d+)',
                                                 line)
                        if min_max_match:
                            current_percentiles["min_max"][
                                "min"] = min_max_match.group(1)
                            current_percentiles["min_max"][
                                "max"] = min_max_match.group(2)
                    elif "average rps:" in line:
                        average_rps_match = re.match(
                            r'average rps: (\d+\.\d+)', line)
                        if average_rps_match:
                            results["average_rps"] = float(
                                average_rps_match.group(1))
        return results

    def parse_perf_data(self, data):
        # Initialize variables to store parsed data
        results = {}
        in_performance_stats = False
        # Use regular expressions to extract the desired information
        for line in data:
            if "Performance counter stats" in line:
                in_performance_stats = True
                continue
            if in_performance_stats and line.strip():
                match = re.match(
                    r'\s*([\d,.]+)\s+([^#]+)\s+#\s*([\d,.]+)\s*([^#]+)?', line)
                if match:
                    raw_value = match.group(1).replace(',', '').strip()
                    key = match.group(2).strip()
                    unit_value = match.group(3).replace(',', '').strip()
                    unit = match.group(4).strip() if match.group(4) else ""
                    if key not in results:
                        results[key] = {}
                    results[key]["raw"] = float(raw_value)
                    if unit:
                        results[key][unit] = float(unit_value)
        # Print the JSON data
        return results

    def test(self):
        # Extract parameters from self.params with defaults
        perf_stat = self.params.get('perf_stat', default='')
        taskset = self.params.get('taskset', default='')
        locking_enabled = self.params.get('locking', default=False)
        num_threads = self.params.get('num_threads', default=1)
        num_workers = self.params.get('num_workers', default=1)
        cache_footprint = self.params.get('cache_footprint', default=256)
        num_operations = self.params.get('num_operations', default=5)
        byte_size = self.params.get('bytes', default=0)
        requests_per_second = self.params.get('rps', default=100)
        runtime = self.params.get('runtime', default=5)
        warmup_time = self.params.get('warmuptime', default=0)
        autobench_enabled = self.params.get('autobench', default=False)
        # Construct the args string using a formatted string
        args = (
            f'-m {num_threads} -t {num_workers} -p {byte_size} -r {runtime} '
            f'-i {runtime} -F {cache_footprint} -n {num_operations} -R {requests_per_second} '
            f'-w {warmup_time} {"-A" if autobench_enabled else ""} {"-L" if locking_enabled else ""}'
        )
        # Build the command string for running the benchmark
        cmd = " ".join(
            filter(None, [
                'perf stat' if perf_stat else None,
                f'taskset -c {taskset}' if taskset else None,
                f"{self.workdir}/schbench", args
            ])
        )
        # Run the benchmark command
        res = process.run(cmd, ignore_status=True, shell=True)
        # Check for failure and handle accordingly
        if res.exit_status:
            self.fail(f"The test failed. Failed command is {cmd}")
        # Parse schbench data
        data = res.stderr.decode().splitlines()
        result = self.parse_schbench_data(data)
        # Include perf data if perf_stat is enabled
        if perf_stat:
            result.update(self.parse_perf_data(data))
        # Write result to JSON file
        json_object = json.dumps(result, indent=4)
        logfile = os.path.join(self.logdir, "schbench.json")
        with open(logfile, "w") as outfile:
            outfile.write(json_object)
