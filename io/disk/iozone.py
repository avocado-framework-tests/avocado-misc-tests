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

# Based on code by:
#   author: Ying Tao <yingtao@cn.ibm.com>
#   author: Lucas Meneghel Rodrigues <lmr@redhat.com>
#   copyright: 2006 IBM
#   copyright: 2008 Red Hat, Inc.

import os
import re
import json
import logging

from avocado import Test
from avocado import main
from avocado.utils import archive
from avocado.utils import process
from avocado.utils import build
from avocado.utils import distro
from avocado.utils import data_structures
from avocado.utils import astring
from avocado.utils.software_manager import SoftwareManager


_LABELS = ['file_size', 'record_size', 'write', 'rewrite', 'read', 'reread',
           'randread', 'randwrite', 'bkwdread', 'recordrewrite', 'strideread',
           'fwrite', 'frewrite', 'fread', 'freread']


class IOzoneAnalyzer(object):

    """
    Analyze an unprocessed IOzone file, and generate the following types of
    report:

    * Summary of throughput for all file and record sizes combined
    * Summary of throughput for all file sizes
    * Summary of throughput for all record sizes

    If more than one file is provided to the analyzer object, a comparison
    between the two runs is made, searching for regressions in performance.
    """

    def __init__(self, log, list_files, output_dir):
        self.list_files = list_files
        if not os.path.isdir(output_dir):
            os.makedirs(output_dir)
        self.output_dir = output_dir
        self.log = log
        self.log.info("Results will be stored in %s", output_dir)

    @staticmethod
    def average_performance(results, size=None):
        """
        Flattens a list containing performance results.
        :param results: List of n lists containing data from performance runs.
        :param size: Numerical value of a size (say, file_size) that was used
                     to filter the original results list.
        :return: List with 1 list containing average data from the performance
                 run.
        """
        average_line = []
        if size is not None:
            average_line.append(size)
        for i in range(2, 15):
            average = data_structures.geometric_mean(
                [line[i] for line in results]) / 1024.0
            average = int(average)
            average_line.append(average)
        return average_line

    def process_results(self, results, label=None):
        """
        Process a list of IOzone results according to label.

        :label: IOzone column label that we'll use to filter and compute
                geometric mean results, in practical term either 'file_size'
                or 'record_size'.
        :result: A list of n x m columns with original iozone results.
        :return: A list of n-? x (m-1) columns with geometric averages for
                values of each label (ex, average for all file_sizes).
        """
        performance = []
        if label is not None:
            index = _LABELS.index(label)
            sizes = data_structures.ordered_list_unique(
                [line[index] for line in results])
            for size in sizes:
                r_results = [line for line in results if line[index] == size]
                performance.append(self.average_performance(r_results, size))
        else:
            performance.append(self.average_performance(results))

        return performance

    @staticmethod
    def parse_file(p_file):
        """
        Parse an IOzone results file.

        :param file: File object that will be parsed.
        :return: Matrix containing IOzone results extracted from the file.
        """
        lines = []
        for line in p_file.readlines():
            fields = line.split()
            if len(fields) != 15:
                continue
            try:
                lines.append([int(i) for i in fields])
            except ValueError:
                continue
        return lines

    def report(self, overall_results, record_size_results, file_size_results):
        """
        Generates analysis data for IOZone run.

        Generates a report to both logs (where it goes with nice headers) and
        output files for further processing (graph generation).

        :param overall_results: 1x15 Matrix containing IOzone results for all
                file sizes
        :param record_size_results: nx15 Matrix containing IOzone results for
                each record size tested.
        :param file_size_results: nx15 Matrix containing file size results
                for each file size tested.
        """

        formatter = logging.Formatter("")

        self.log.info("")
        self.log.info("TABLE:  SUMMARY of ALL FILE and RECORD SIZES           "
                      "Results in MB/sec")
        self.log.info("")
        overall_results[0].insert(0, "ALL")
        header_list = ['FILE & RECORD SIZES (KB)', 'INIT WRITE', 'RE WRITE',
                       'READ', 'RE READ', 'RANDOM READ', 'RANDOM WRITE',
                       'BACKWD READ', 'RECRE WRITE', 'STRIDE READ', 'F WRITE',
                       'FRE WRITE', 'F READ', 'FRE READ']
        self.log.info("\n%s", astring.tabular_output(
            overall_results, header=header_list))
        self.log.info("")

        self.log.info("DRILLED DATA:")

        self.log.info("")
        self.log.info("TABLE:  RECORD Size against all FILE Sizes             "
                      "Results in MB/sec")
        self.log.info("")
        foutput_path = os.path.join(self.output_dir, '2d-datasource-file')
        if os.path.isfile(foutput_path):
            os.unlink(foutput_path)
        foutput = logging.FileHandler(foutput_path)
        foutput.setFormatter(formatter)
        self.log.addHandler(foutput)

        header_list = ['RECORD SIZE (KB)', 'INIT WRITE', 'RE WRITE', 'READ',
                       'RE READ', 'RANDOM READ', 'RANDOM WRITE', 'BACKWD READ',
                       'RECRE WRITE', 'STRIDE READ', 'F WRITE', 'FRE WRITE',
                       'F READ', 'FRE READ']
        self.log.info("\n%s", astring.tabular_output(
            record_size_results, header=header_list))
        self.log.removeHandler(foutput)

        self.log.info("")
        self.log.info("TABLE:  FILE Size against all RECORD Sizes             "
                      "Results in MB/sec")
        self.log.info("")
        routput_path = os.path.join(self.output_dir, '2d-datasource-record')
        if os.path.isfile(routput_path):
            os.unlink(routput_path)
        routput = logging.FileHandler(routput_path)
        routput.setFormatter(formatter)
        self.log.addHandler(routput)

        self.log.info("\n%s", astring.tabular_output(
            file_size_results, header=header_list))
        self.log.removeHandler(routput)

        self.log.info("")

    def report_comparison(self, record, files):
        """
        Generates comparison data for 2 IOZone runs.

        It compares 2 sets of nxm results and outputs a table with differences.
        If a difference higher or smaller than 5% is found, a warning is
        triggered.

        :param record: Tuple with 4 elements containing results for record
        size.
        :param file: Tuple with 4 elements containing results for file size.
        """
        (record_size, record_improvements, record_regressions,
         record_total) = record
        (file_size, file_improvements, file_regressions,
         file_total) = files
        header_list = ['RECORD SIZE (KB)', 'INIT WRITE', 'RE WRITE', 'READ',
                       'RE READ', 'RANDOM READ', 'RANDOM WRITE', 'BACKWD READ',
                       'RECRE WRITE', 'STRIDE READ', 'F WRITE', 'FRE WRITE',
                       'F READ', 'FRE READ']
        self.log.info("\n%s", astring.tabular_output(
            record_size, header=header_list))

        self.log.info("ANALYSIS of DRILLED DATA:")

        self.log.info("")
        self.log.info("TABLE:  RECsize Difference between runs              "
                      "Results are % DIFF")
        self.log.info("")
        self.log.info("REGRESSIONS: %d (%.2f%%)    Improvements: %d (%.2f%%)",
                      record_regressions,
                      (100 * record_regressions / float(record_total)),
                      record_improvements,
                      (100 * record_improvements / float(record_total)))
        self.log.info("")

        self.log.info("")
        self.log.info("TABLE:  FILEsize Difference between runs               "
                      "Results are % DIFF")
        self.log.info("")

        self.log.info("\n%s", astring.tabular_output(
            file_size, header=header_list))
        self.log.info("REGRESSIONS: %d (%.2f%%)    Improvements: %d (%.2f%%)",
                      file_regressions,
                      (100 * file_regressions / float(file_total)),
                      file_improvements,
                      (100 * file_improvements / float(file_total)))
        self.log.info("")

    def analyze(self):
        """
        Analyzes and eventually compares sets of IOzone data.
        """
        overall = []
        record_size = []
        file_size = []
        for path in self.list_files:
            c_file = open(path, 'r')
            self.log.info('FILE: %s', path)

            results = self.parse_file(c_file)

            overall_results = self.process_results(results)
            record_size_results = self.process_results(results, 'record_size')
            file_size_results = self.process_results(results, 'file_size')
            self.report(overall_results, record_size_results,
                        file_size_results)

            if len(self.list_files) == 2:
                overall.append(overall_results)
                record_size.append(record_size_results)
                file_size.append(file_size_results)

        if len(self.list_files) == 2:
            record_comparison = data_structures.compare_matrices(*record_size)
            file_comparison = data_structures.compare_matrices(*file_size)
            self.report_comparison(record_comparison, file_comparison)


class IOzonePlotter(object):

    """
    Plots graphs based on the results of an IOzone run.

    Plots graphs based on the results of an IOzone run. Uses gnuplot to
    generate the graphs.
    """

    def __init__(self, log, results_file, output_dir):
        self.active = True
        s_mg = SoftwareManager()
        self.log = log
        if not s_mg.check_installed("gnuplot") and not s_mg.install("gnuplot"):
            self.log.warn("Command gnuplot not found, disabling graph "
                          "generation")
            self.active = False

        if not os.path.isdir(output_dir):
            os.makedirs(output_dir)
        self.output_dir = output_dir

        if not os.path.isfile(results_file):
            self.log.error("Invalid file %s provided, disabling graph "
                           "generation", results_file)
            self.active = False
            self.results_file = None
        else:
            self.results_file = results_file
            self.generate_data_source()

    def generate_data_source(self):
        """
        Creates data file without headers for gnuplot consumption.
        """
        results_file = open(self.results_file, 'r')
        self.datasource = os.path.join(self.output_dir, '3d-datasource')
        datasource = open(self.datasource, 'w')
        values = []
        for line in results_file.readlines():
            fields = line.split()
            if len(fields) != 15:
                continue
            try:
                values.append([int(i) for i in fields])
                datasource.write(line)
            except ValueError:
                continue
        datasource.close()

    def plot_2d_graphs(self):
        """
        For each one of the throughput parameters, generate a set of gnuplot
        commands that will create a parametric surface with file size vs.
        record size vs. throughput.
        """
        datasource_2d = os.path.join(self.output_dir, '2d-datasource-file')
        for index, label in zip(range(2, 15), _LABELS[2:]):
            commands_path = os.path.join(self.output_dir, '2d-%s.do' % label)
            commands = ""
            commands += "set title 'Iozone performance: %s'\n" % label
            commands += "set logscale x\n"
            commands += "set xlabel 'File size (KB)'\n"
            commands += "set ylabel 'Througput (MB/s)'\n"
            commands += "set terminal png small size 450 350\n"
            commands += "set output '%s'\n" % os.path.join(self.output_dir,
                                                           '2d-%s.png' % label)
            commands += ("plot '%s' using 1:%s title '%s' with lines \n" %
                         (datasource_2d, index, label))
            commands_file = open(commands_path, 'w')
            commands_file.write(commands)
            commands_file.close()
            try:
                process.system("gnuplot \"%s\"" % commands_path, shell=True)
            except process.CmdError:
                self.log.error("Problem plotting from commands file %s",
                               commands_path)

    def plot_3d_graphs(self):
        """
        For each one of the throughput parameters, generate a set of gnuplot
        commands that will create a parametric surface with file size vs.
        record size vs. throughput.
        """
        # FIXME:Creating 3d-graphs - to be updated with new version of gnuplot
        for index, label in zip(range(1, 14), _LABELS[2:]):
            commands_path = os.path.join(self.output_dir, '%s.do' % label)
            commands = ""
            commands += "set title 'Iozone performance: %s'\n" % label
            commands += "set grid lt 2 lw 1\n"
            commands += "set surface\n"
            commands += "set parametric\n"
            commands += "set xtics\n"
            commands += "set ytics\n"
            commands += "set logscale x 2\n"
            commands += "set logscale y 2\n"
            commands += "set logscale z\n"
            commands += "set xrange [2.**5:2.**24]\n"
            commands += "set xlabel 'File size (KB)'\n"
            commands += "set ylabel 'Record size (KB)'\n"
            commands += "set zlabel 'Througput (KB/s)'\n"
            commands += "set style data lines\n"
            commands += "set dgrid3d 80,80, 3\n"
            commands += "set terminal png small size 900 700\n"
            commands += "set output '%s'\n" % os.path.join(self.output_dir,
                                                           '%s.png' % label)
            commands += ("splot '%s' using 1:2:%s title '%s'\n" %
                         (self.datasource, index, label))
            commands_file = open(commands_path, 'w')
            commands_file.write(commands)
            commands_file.close()
            try:
                process.system("gnuplot \"%s\"" % commands_path, shell=True)
            except process.CmdError:
                self.log.error("Problem plotting from commands file %s",
                               commands_path)

    def plot_all(self):
        """
        Plot all graphs that are to be plotted, provided that we have gnuplot.
        """
        if self.active:
            self.plot_2d_graphs()
            self.plot_3d_graphs()


class IOZone(Test):

    '''
    IOzone is a filesystem benchmark tool. The benchmark generates and measures
    a variety of file operations. Iozone has been ported to many machines and
    runs under many operating systems.
    '''

    def setUp(self):
        '''
        Build IOZone
        Source:
        http://www.iozone.org/src/current/iozone3_434.tar
        '''

        self.base_dir = os.path.abspath(self.basedir)
        smm = SoftwareManager()
        for package in ['gcc', 'make', 'patch']:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel("%s is needed for the test to be run" % package)
        tarball = self.fetch_asset(
            'http://www.iozone.org/src/current/iozone3_434.tar')
        archive.extract(tarball, self.teststmpdir)
        version = os.path.basename(tarball.split('.tar')[0])
        self.sourcedir = os.path.join(self.teststmpdir, version)

        make_dir = os.path.join(self.sourcedir, 'src', 'current')
        os.chdir(make_dir)
        patch = self.params.get('patch', default='makefile.patch')
        patch = self.get_data(patch)
        process.run('patch -p3 < %s' % patch, shell=True)

        d_distro = distro.detect()
        arch = d_distro.arch
        if arch == 'ppc':
            build.make(make_dir, extra_args='linux-powerpc')
        elif arch == 'ppc64' or arch == 'ppc64le':
            build.make(make_dir, extra_args='linux-powerpc64')
        elif arch == 'x86_64':
            build.make(make_dir, extra_args='linux-AMD64')
        else:
            build.make(make_dir, extra_args='linux')

    @staticmethod
    def __get_section_name(desc):
        """
        Returns section name with '_' replacing ' '
        """
        return desc.strip().replace(' ', '_')

    def generate_keyval(self):
        """
        Generating key-value list from results and recording it in JSON file
        """
        keylist = {}

        if self.auto_mode:
            labels = ('write', 'rewrite', 'read', 'reread', 'randread',
                      'randwrite', 'bkwdread', 'recordrewrite',
                      'strideread', 'fwrite', 'frewrite', 'fread', 'freread')
            for line in self.results.splitlines():
                fields = line.split()
                if len(fields) != 15:
                    continue
                try:
                    fields = tuple([int(i) for i in fields])
                except ValueError:
                    continue
                for lin, val in zip(labels, fields[2:]):
                    key_name = "%d-%d-%s" % (fields[0], fields[1], lin)
                    keylist[key_name] = val
        else:
            child_regexp = re.compile(r'Children see throughput for[s]+'
                                      r'([d]+)s+([-w]+[-ws]*)=[s]+([d.]*) '
                                      'KB/sec')
            parent_regexp = re.compile(r'Parent sees throughput for[s]+'
                                       r'([d]+)s+([-w]+[-ws]*)=[s]+([d.]*) '
                                       'KB/sec')

            kbsec_regexp = re.compile(r'=[s]+([d.]*) KB/sec')
            kbval_regexp = re.compile(r'=[s]+([d.]*) KB')

            section = None
            w_count = 0

            for line in self.results.splitlines():
                line = line.strip()

                # Check for the beginning of a new result section
                match = child_regexp.search(line)
                if match:
                    # Extract the section name and the worker count
                    w_count = int(match.group(1))
                    section = self.__get_section_name(match.group(2))

                    # Output the appropriate keyval pair
                    key_name = '%s-%d-kids' % (section, w_count)
                    keylist[key_name] = match.group(3)
                    continue

                # Check for any other interesting lines
                if '=' in line:
                    # Is it something we recognize? First check for parent.
                    match = parent_regexp.search(line)
                    if match:
                        # The section name and the worker count better match
                        p_count = int(match.group(1))
                        p_secnt = self.__get_section_name(match.group(2))
                        if p_secnt != section or p_count != w_count:
                            continue

                        # Set the base name for the keyval
                        basekey = 'parent'
                    else:
                        # Check for the various 'throughput' values
                        if line[3:26] == ' throughput per thread ':
                            basekey = line[0:3]
                            match_x = kbsec_regexp
                        else:
                            # The only other thing we expect is 'Min xfer'
                            if not line.startswith('Min xfer '):
                                continue
                            basekey = 'MinXfer'
                            match_x = kbval_regexp

                        match = match_x.search(line)
                        if match:
                            result = match.group(1)
                            key_name = "%s-%d-%s" % (section, w_count, basekey)
                            keylist[key_name] = result
        self.whiteboard = json.dumps(keylist, indent=1)

    def test(self):
        '''
        Test method for performing IOZone test and analysis.
        '''
        directory = self.params.get('dir', default=None)
        args = self.params.get('args', default=None)
        previous_results = self.params.get('previous_results', default=None)

        if not directory:
            directory = self.base_dir
        os.chdir(directory)

        if not args:
            args = '-a'

        cmd = os.path.join(self.sourcedir, 'src', 'current', 'iozone')
        self.results = process.system_output('%s %s' % (cmd, args))
        self.auto_mode = ("-a" in args)
        results_path = os.path.join(self.outputdir,
                                    'raw_output')
        analysisdir = os.path.join(self.outputdir,
                                   'analysis')
        with open(results_path, 'w') as r_file:
            r_file.write(self.results)

        self.generate_keyval()
        if self.auto_mode:
            if previous_results:
                analysis = IOzoneAnalyzer(self.log,
                                          list_files=[results_path,
                                                      previous_results],
                                          output_dir=analysisdir)
                analysis.analyze()
            else:
                analysis = IOzoneAnalyzer(self.log, list_files=[results_path],
                                          output_dir=analysisdir)
                analysis.analyze()
            plotter = IOzonePlotter(self.log, results_file=results_path,
                                    output_dir=analysisdir)
            plotter.plot_2d_graphs()


if __name__ == "__main__":
    main()
