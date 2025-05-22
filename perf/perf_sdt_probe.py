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
# Copyright: 2018 IBM.
# Author: Kamalesh Babulal <kamalesh@linux.vnet.ibm.com>
# Modified And tested : Praveen K Pandey <praveen@linux.vnet.ibm.com>

import os
import platform
import re
import tempfile
import time

from avocado import Test
from avocado.utils import distro
from avocado.utils import process
from avocado.utils.software_manager.manager import SoftwareManager


class PerfSDT(Test):

    """
    Test userspace SDT markers
    :avocado: tags=privileged,perf,sdtprobe,probe
    """

    def run_cmd(self, cmd):
        if process.system(cmd, sudo=True, shell=True):
            self.is_fail += 1
        return

    @staticmethod
    def run_cmd_out(cmd):
        return process.system_output(cmd, shell=True,
                                     sudo=True).decode("utf-8")

    def add_library(self):
        """
        Find the libpthread path, it differs for distros
        example:
        libpthread.so.0 (libc6,64bit, OS ABI: Linux 3.10.0) =>
            /lib/powerpc64le-linux-gnu/libpthread.so.0
        """
        self.libpthread = self.run_cmd_out("ldconfig -p")
        for line in str(self.libpthread).splitlines():
            if re.search('libpthread.so', line, re.IGNORECASE):
                if 'lib64' in line:
                    self.libpthread = line.split("=>")[1]
            if re.search('libc.so', line, re.IGNORECASE):
                if 'lib64' in line:
                    self.libc = line.split("=>")[1]
        if not self.libpthread:
            self.fail("Library %s not found" % self.libpthread)
        if not self.libc:
            self.fail("Library %s not found" % self.libc)
        val = 0
        result = self.run_cmd_out("perf list")
        for line in str(result).splitlines():
            if 'SDT' in line:
                val = val + 1
        # Add the libpthread.so.0 to perf
        perf_add = "perf buildid-cache -v --add %s" % self.libpthread
        self.is_fail = 0
        self.run_cmd(perf_add)
        if self.is_fail:
            self.fail("Unable to add %s to builid-cache" % self.libpthread)
        time.sleep(30)
        # Add the libc.so.6 to perf
        perf_libc_add = "perf buildid-cache -v --add %s" % self.libc
        self.is_fail = 0
        self.run_cmd(perf_libc_add)
        if self.is_fail:
            self.fail("Unable to add %s to builid-cache" % self.libc)
        time.sleep(30)
        # Check if libpthread has valid SDT markers
        new_val = 0
        result = self.run_cmd_out("perf list")
        for line in str(result).splitlines():
            if 'SDT' in line:
                new_val = new_val + 1
        if val == new_val:
            self.fail("No SDT markers available in the %s" % self.libpthread)

    def remove_library(self, param):
        perf_remove = "perf buildid-cache -v --remove %s" % param
        self.is_fail = 0
        self.run_cmd(perf_remove)
        if self.is_fail:
            self.fail("Unable to remove %s from builid-cache" % param)

    def enable_sdt_marker_probe(self):
        self.sdt_events = process.system_output(
            "perf list --raw-dump sdt", shell=True).decode().split()
        for self.event in self.sdt_events:
            self.event = self.event.split('@')[0].strip()
            try:
                self.run_cmd("perf probe --add %s" % self.event)
            except Exception as e:
                error_message = str(e)
                if ('File exists' in error_message or
                        'already exists' in error_message):
                    self.log.info(
                        f"Event {self.event} already exists, skipping.")
                else:
                    self.fail(
                        f"Failed to add event {self.event}: {error_message}")

    def disable_sdt_marker_probe(self):
        disable_sdt_probe = "perf probe -d \\*"
        self.is_fail = 0
        self.run_cmd(disable_sdt_probe)
        if self.is_fail:
            self.fail("Unable to remove SDT marker event probe %s"
                      % self.sdt_marker)

    def record_sdt_marker_probe(self):
        record_sdt_probe = "perf record -o %s -e %s -aR sleep 1" % (
            self.temp_file, self.event)
        self.is_fail = 0
        self.run_cmd(record_sdt_probe)
        if self.is_fail or not os.path.exists(self.temp_file):
            self.disable_sdt_marker_probe()
            self.fail("Perf record of SDT marker event %s failed"
                      % self.event)

    def setUp(self):
        """
        Setting up the env for SDT markers
        """
        smg = SoftwareManager()
        self.libpthread = []
        self.libc = []
        self.temp_file = tempfile.NamedTemporaryFile().name
        detected_distro = distro.detect()
        if 'ppc' not in distro.detect().arch:
            self.cancel("Test supported only on  ppc64 arch")
        deps = ['gcc', 'make']
        if 'Ubuntu' in detected_distro.name:
            deps.extend(['libc-dev', 'libc-bin', 'linux-tools-common',
                         'linux-tools-%s' % platform.uname()[2]])
        elif detected_distro.name in ['rhel', 'SuSE', 'fedora', 'centos']:
            deps.extend(['perf', 'glibc', 'glibc-devel'])
        else:
            self.cancel("Install the package for perf supported by %s"
                        % detected_distro.name)
        for package in deps:
            if not smg.check_installed(package) and not smg.install(package):
                self.cancel('%s is needed for the test to be run' % package)

    def test(self):
        self.add_library()
        self.enable_sdt_marker_probe()
        self.record_sdt_marker_probe()
        self.disable_sdt_marker_probe()

    def tearDown(self):
        'cleanup'
        self.remove_library(self.libpthread)
        self.remove_library(self.libc)
        if os.path.exists(self.temp_file):
            os.remove(self.temp_file)
