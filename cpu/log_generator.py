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
# Copyright: 2023 IBM
# Author: Samir A Mulani <samir@linux.vnet.ibm.com>


import os
from avocado import Test
from avocado.utils import process
from avocado.utils import git
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils import linux_modules


class log_generator(Test):
    def setUp(self):
        """
        Here in this test case we are running any cpu intensive workload
        and capturing the disfferent logs,
        Ex: perf_stat, strace and sched_scoreboard etc.
        """
        pkgs = []
        directory_name = "sched-scoreboard"
        self.sched_scoreboard_dir = os.path.expanduser(f"~/{directory_name}")
        self.uname = linux_modules.platform.uname()[2]
        self.kernel_ver = "kernel-devel-%s" % self.uname
        smm = SoftwareManager()
        pkgs.extend(["strace", "perf", "trace-cmd", "git", "bpftrace"])
        for pkg in pkgs:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel("Not able to install %s" % pkg)

        self.user_command = self.params.get('user_command', default="sleep 10")
        self.repeat = int(self.params.get('repeat', default="10"))

        cmd = "command -v bpftrace &>/dev/null"
        info = process.system_output(cmd, ignore_status=True)
        if not info:
            self.cancel(
                "bpftrace is not installed. Please install it \
                        for sched-scoreboard to work.")

        if os.path.exists(self.sched_scoreboard_dir) and os.path.isdir(
                self.sched_scoreboard_dir):
            os.chdir(self.sched_scoreboard_dir)
            cmd = "git pull"
            process.run(cmd, ignore_status=True, sudo=True, shell=True)
        else:
            os.mkdir(self.sched_scoreboard_dir)
            os.chdir(self.sched_scoreboard_dir)
            git.get_repo('https://github.com/AMDESE/sched-scoreboard.git',
                         branch='main',
                         destination_dir=self.sched_scoreboard_dir)

            # Create symbolic link to bpftrace
            cmd = 'ln -s "$(which bpftrace)" "%s/bpftrace"' % \
                (self.sched_scoreboard_dir)
            process.run(cmd, ignore_status=True, sudo=True, shell=True)

    def test_sched_scoreboard_setup(self):
        """_summary_
        Here in this test case we are cloning the sched_scoreboard
        repo and prepareing the sched_scoreboard to run.
        """
        scoreboard_setup_log_file = self.logdir + "/sched_scoreboard_setup"
        os.mkdir(scoreboard_setup_log_file)

        log_file = "%s/sched_scoreboard_command_output_%s.log" % (
            scoreboard_setup_log_file, self.kernel_ver)
        cmd = 'echo "Using command: %s >> %s" 2>&1' % (
            self.user_command, log_file)
        process.run(cmd, ignore_status=True, sudo=True, shell=True)

        cmd = 'lscpu >> "%s" 2>&1' % (log_file)
        process.run(cmd, ignore_status=True, sudo=True, shell=True)
        cmd = 'echo >> "%s" 2>&1' % (log_file)
        process.run(cmd, ignore_status=True, sudo=True, shell=True)

        # Execute the command and append the output to the log file
        for i in range(self.repeat):
            cmd = 'eval "$user_command" >> "%s" 2>&1' % (log_file)
            process.run(cmd, ignore_status=True, sudo=True, shell=True)

        cmd = 'echo >> "%s" 2>&1' % (log_file)
        process.run(cmd, ignore_status=True, sudo=True, shell=True)

        for i in range(self.repeat):
            # Execute the command and append the output to the log file
            cmd = '/usr/bin/time -v $(echo %s) >> "%s" 2>&1' % (
                self.user_command, log_file)
            process.run(cmd, ignore_status=True, sudo=True, shell=True)

    def test_strace_cmd(self):
        """
        Run the strace command
        """
        strace_log_file = self.logdir + "/strace"
        os.mkdir(strace_log_file)

        log_file = "%s/strace_command_output_%s.log" % (
            strace_log_file, self.kernel_ver)
        cmd = 'strace -c $(echo %s) >> "%s" 2>&1' % (self.user_command,
                                                     log_file)
        for i in range(2):
            process.run(cmd, ignore_status=True, sudo=True, shell=True)

    def test_perf_stat_cmd(self):
        """_summary_
        Run the workload command with perf stat.
        """
        perf_log_file = self.logdir + "/perf_stat"
        os.mkdir(perf_log_file)

        log_file = "%s/perf_stat_command_output_%s.log" % (
            perf_log_file, self.kernel_ver)
        cmd = 'perf stat -r %d -d -d -d -- $(echo %s) >> "%s" 2>&1' % (
            self.repeat, self.user_command, log_file)
        process.run(cmd, ignore_status=True, sudo=True, shell=True)

        cmd = 'echo >> "%s" 2>&1' % (log_file)
        process.run(cmd, ignore_status=True, sudo=True, shell=True)

        cmd = 'perf stat -r %d -d -d -d --all-kernel -- $(echo %s) \
                >> "%s" 2>&1' % (
            self.repeat, self.user_command, log_file)
        process.run(cmd, ignore_status=True, sudo=True, shell=True)

        cmd = 'echo >> "%s" 2>&1' % (log_file)
        process.run(cmd, ignore_status=True, sudo=True, shell=True)

        cmd = 'perf stat -r %d -d -d -d --all-user -- $(echo %s) \
                >> "%s" 2>&1' % (
            self.repeat, self.user_command, log_file)
        process.run(cmd, ignore_status=True, sudo=True, shell=True)

    def test_sched_scoreboard_cmd(self):
        """_summary_
        Here we are running the sched_scoreboard to capture and report
        all the data related to the Linux Kernel Scheduler.
        """
        sched_log_file = self.logdir + "/sched_scoreboard"
        os.mkdir(sched_log_file)
        log_file = "%s/sched_scoreboard_command_output_%s.log" % (
            sched_log_file, self.kernel_ver)
        cmd = 'bash %s/sched-scoreboard.sh --logdir "%s" -e -d --workload \
                "%s" >> "%s" 2>&1' % (self.sched_scoreboard_dir,
                                      sched_log_file, self.user_command,
                                      log_file)
        process.run(cmd, ignore_status=True, sudo=True, shell=True)

    def test_trace_cmd(self):
        """_summary_
        Here we are running the workload command with trace command.
        """
        trace_log_file = self.logdir + "/trace"
        os.mkdir(trace_log_file)

        log_file = "%s/trace_command_output_%s.dat" % (
            trace_log_file, self.kernel_ver)
        cmd = 'trace-cmd record -e sched -o "%s" -- $(echo %s) >> "%s" \
                2>&1' % (trace_log_file, self.user_command, log_file)
        process.run(cmd, ignore_status=True, sudo=True, shell=True)
