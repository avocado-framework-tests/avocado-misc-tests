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
# Copyright: 2024 IBM
# Author: Sachin Sant <sachinp@linux.ibm.com>
# Author(Modified): Samir <samir@linux.ibm.com>
#


import os
import shutil
import pathlib
import csv
import glob
from sys import version_info

from avocado import Test
from avocado import skipIf
from avocado.utils import process, build, archive, distro
from avocado.utils.software_manager.manager import SoftwareManager

VERSION_CHK = version_info[0] < 4 and version_info[1] < 7


class WillItScaleTest(Test):
    """
    Will It Scale takes a testcase and runs n parallel copies to see if the
    testcase will scale.
    Source - https://github.com/antonblanchard/will-it-scale

    :avocado: tags=kernel,ppc64le
    """
    fail_cmd = list()

    def parse_and_log_csv_summary(self, csv_file):
        """
        Parse will-it-scale CSV file and log complete performance data matrix.
        CSV format: tasks,processes,processes_idle,threads,threads_idle,linear
        """
        try:
            if not os.path.exists(csv_file):
                self.log.warning(f"CSV file not found: {csv_file}")
                return

            with open(csv_file, 'r') as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            if len(rows) < 1:
                self.log.warning(f"CSV file has no data: {csv_file}")
                return

            # Extract test name from filename
            test_name = os.path.basename(csv_file).replace('.csv', '')

            # Log complete performance data matrix
            self.log.info("")
            self.log.info("=" * 120)
            self.log.info(f"PERFORMANCE MATRIX: {test_name.upper()}")
            self.log.info("=" * 120)
            self.log.info(
                f"{'Tasks':<8} {'Processes':<13} {'Proc Idle%':<12} "
                f"{'Threads':<13} {'Thread Idle%':<13} {'Linear':<13} "
                f"{'Proc vs Lin%':<13} {'Thread vs Lin%':<13}"
            )
            self.log.info("-" * 120)

            # Track statistics
            max_process_ops = 0
            max_thread_ops = 0
            max_process_tasks = 0
            max_thread_tasks = 0
            total_rows = 0

            # Parse and display all data rows
            for row in rows:
                try:
                    tasks = row.get('tasks', '0')
                    processes = row.get('processes', '0')
                    processes_idle = row.get('processes_idle', '0')
                    threads = row.get('threads', '0')
                    threads_idle = row.get('threads_idle', '0')
                    linear = row.get('linear', '0')

                    # Calculate percentage difference vs linear scaling
                    proc_vs_linear = "N/A"
                    thread_vs_linear = "N/A"
                    try:
                        if linear != '0' and float(linear) > 0:
                            proc_val = float(processes)
                            thread_val = float(threads)
                            linear_val = float(linear)
                            proc_vs_linear = \
                                f"{((proc_val / linear_val)*100):.2f}%"
                            thread_vs_linear = \
                                f"{((thread_val / linear_val)*100):.2f}%"
                    except (ValueError, ZeroDivisionError):
                        pass

                    # Format and log the row
                    self.log.info(
                        f"{tasks:<8} {processes:<13} {processes_idle:<12} "
                        f"{threads:<13} {threads_idle:<13} {linear:<13} "
                        f"{proc_vs_linear:<13} {thread_vs_linear:<13}"
                    )

                    total_rows += 1

                    # Track maximum values (skip row 0 which is baseline)
                    if tasks != '0':
                        try:
                            proc_val = float(processes)
                            thread_val = float(threads)
                            task_num = int(tasks)

                            if proc_val > max_process_ops:
                                max_process_ops = proc_val
                                max_process_tasks = task_num

                            if thread_val > max_thread_ops:
                                max_thread_ops = thread_val
                                max_thread_tasks = task_num
                        except ValueError:
                            pass

                except Exception as e:
                    self.log.debug(f"Error parsing row: {row} - {e}")
                    continue

            # Log summary statistics
            self.log.info("-" * 120)
            self.log.info("SUMMARY STATISTICS:")
            self.log.info(f"  Total data points: {total_rows}")
            if max_process_ops > 0:
                self.log.info(
                    f"  Peak Processes:    {max_process_ops:,.0f} \
                            ops/sec @ {max_process_tasks} tasks")
            if max_thread_ops > 0:
                self.log.info(
                    f"  Peak Threads:      {max_thread_ops:,.0f} \
                            ops/sec @ {max_thread_tasks} tasks")

            # Calculate scalability efficiency
            if max_process_ops > 0 and max_process_tasks > 0:
                single_proc = float(rows[1].get(
                    'processes', '0')) if len(rows) > 1 else 0
                if single_proc > 0:
                    efficiency = (max_process_ops /
                                  (single_proc * max_process_tasks)) * 100
                    self.log.info(
                        f"  Process Scalability Efficiency: {efficiency:.2f}%")

            if max_thread_ops > 0 and max_thread_tasks > 0:
                single_thread = float(rows[1].get(
                    'threads', '0')) if len(rows) > 1 else 0
                if single_thread > 0:
                    efficiency = (max_thread_ops /
                                  (single_thread * max_thread_tasks)) * 100
                    self.log.info(
                        f"  Thread Scalability Efficiency:  {efficiency:.2f}%")

            self.log.info("=" * 120)
            self.log.info("")

        except Exception as e:
            self.log.error(f"Error parsing CSV file {csv_file}: {e}")
            import traceback
            self.log.debug(traceback.format_exc())

    def run_cmd(self, cmd):
        if process.system(cmd, ignore_status=True, sudo=True, shell=True):
            self.fail_cmd.append(cmd)
        return

    def get_libhw(self):
        """
        SLES does not contain hwloc-devel package, get the source and
        compile it to be linked to will-it-scale binaries.

        Source - https://github.com/open-mpi/hwloc/
        """
        hwloc_url = ('https://github.com/open-mpi/hwloc/archive/refs/'
                     'heads/master.zip')
        tarball = self.fetch_asset('hwloc.zip', locations=hwloc_url,
                                   expire='7d')
        archive.extract(tarball, self.workdir)
        self.sourcedir = os.path.join(self.workdir, 'hwloc-master')
        os.chdir(self.sourcedir)
        self.run_cmd('./autogen.sh')
        self.run_cmd('./configure --prefix=/usr')
        if self.fail_cmd:
            self.fail('Configure failed, please check debug logs')
        if build.make(self.sourcedir):
            self.fail('make failed, please check debug logs')
        if build.make(self.sourcedir, extra_args='install'):
            self.fail('make install failed, please check debug logs')
        # Create a symlink with name libhwloc.so.0
        if not pathlib.Path("/usr/lib/libhwloc.so.0").is_symlink():
            self.run_cmd('ln -s /usr/lib/libhwloc.so.0.0.0 '
                         '/usr/lib/libhwloc.so.0')
            if self.fail_cmd:
                self.warn('libhwloc softlink failed, program may not run')

    @skipIf(VERSION_CHK, "Test requires Python 3.7+")
    def setUp(self):
        """
        To execute test using git copy
          make
          ./runalltests

        To generate graphical results
          ./postprocess.py
        """
        self.distro_rel = distro.detect()
        smm = SoftwareManager()
        deps = ['gcc', 'make']
        if self.distro_rel.name.lower() in ['fedora', 'redhat', 'rhel']:
            deps.extend(['hwloc-devel'])
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is required for this test' % package)
        # Compile and install libhwloc library
        if 'suse' in self.distro_rel.name.lower():
            self.get_libhw()

        self.postprocess = self.params.get('postprocess', default=True)
        self.testcase = self.params.get('name', default='brk1')
        url = self.params.get(
            'willit_url', default='https://github.com/antonblanchard/'
            'will-it-scale/archive/refs/heads/master.zip')
        tarball = self.fetch_asset('willit.zip', locations=[url],
                                   expire='7d')
        archive.extract(tarball, self.workdir)
        self.sourcedir = os.path.join(self.workdir, 'will-it-scale-master')
        os.chdir(self.sourcedir)
        # Modify the makefile to point to installed libhwloc
        if 'suse' in self.distro_rel.name.lower():
            makefile_patch = 'patch -p1 < %s' % self.get_data('makefile.patch')
            process.run(makefile_patch, shell=True)
        if build.make(self.sourcedir):
            self.fail('make failed, please check debug logs')

    def test_scaleitall(self):
        """
        Invoke and execute test(s)
        """
        os.chdir(self.sourcedir)
        self.log.info("Starting test...")

        # Identify the test to be executed
        if self.testcase in 'All':
            cmd = './runalltests'
        else:
            cmd = './runtest.py %s > %s.csv' % (self.testcase, self.testcase)

        # Execute the test(s)
        if process.system(cmd, shell=True, sudo=True, ignore_status=True) != 0:
            self.fail('Please check the logs for failure')

        # Generate graphical results if postprocessing is enabled
        if self.postprocess:
            cmd = './postprocess.py'
            if process.system(cmd, shell=True, ignore_status=True) != 0:
                self.warn('Post processing failed, graph may not be generated')

        # Create a subdirectory for test results
        results_dir = os.path.join(
            self.logdir, f"will-it-scale-{self.testcase}")
        os.makedirs(results_dir, exist_ok=True)
        self.log.info(f"Created results directory: {results_dir}")

        # Copy CSV and HTML files to the results subdirectory
        if self.testcase not in 'All':
            # Single test case - copy specific files
            csv_file = f"{self.testcase}.csv"
            html_file = f"{self.testcase}.html"
            if os.path.exists(csv_file):
                # Parse and log complete CSV data to debug.log
                self.parse_and_log_csv_summary(csv_file)
                shutil.copy(csv_file, results_dir)
                self.log.info(f"Copied {csv_file} to {results_dir}")
            if os.path.exists(html_file):
                shutil.copy(html_file, results_dir)
                self.log.info(f"Copied {html_file} to {results_dir}")
        else:
            # All tests - copy all generated CSV and HTML files
            csv_files = glob.glob("*.csv")
            html_files = glob.glob("*.html")
            for csv_file in csv_files:
                # Parse and log complete CSV data to debug.log
                self.parse_and_log_csv_summary(csv_file)
                shutil.copy(csv_file, results_dir)
                self.log.info(f"Copied {csv_file} to {results_dir}")
            for html_file in html_files:
                shutil.copy(html_file, results_dir)
                self.log.info(f"Copied {html_file} to {results_dir}")
