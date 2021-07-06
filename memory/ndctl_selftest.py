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
# Copyright: 2019 IBM
# Author: Harish <harish@linux.vnet.ibm.com>
#
#

import os
import json

from avocado import Test
from avocado.utils import process, build, distro, git, genio
from avocado.utils.software_manager import SoftwareManager


class NdctlTest(Test):
    """
    Ndctl is a user space tool to manage persistent memory devices
    This test uses the selftests of the userspace tool to sanity check the
    persistent memory
    """

    def get_bus_ids(self):
        """
        Get the provider IDs for each pmem device
        """
        bus_ids = []
        os.chdir(self.sourcedir)
        json_op = json.loads(process.system_output(
            './ndctl/ndctl list -B', shell=True))
        for nid in json_op:
            for key, value in nid.items():
                if key == 'provider':
                    bus_ids.append(value)
        return bus_ids

    def setUp(self):
        """
        Prequisite for ndctl selftest on non-NFIT devices
        """
        nstype_file = "/sys/bus/nd/devices/region0/nstype"
        if not os.path.isfile(nstype_file):
            self.cancel("Not found required sysfs file: %s." % nstype_file)
        nstype = genio.read_file(nstype_file).rstrip("\n")
        if nstype == "4":
            self.cancel("Test not supported on legacy hardware")

        smg = SoftwareManager()
        self.url = self.params.get(
            'url', default="https://github.com/pmem/ndctl.git")
        self.branch = self.params.get('branch', default='master')
        deps = ['gcc', 'make', 'automake', 'autoconf', 'patch', 'jq']
        detected_distro = distro.detect()
        if detected_distro.name in ['SuSE', 'rhel']:
            if detected_distro.name == 'SuSE':
                deps.extend(['libkmod-devel', 'libudev-devel',
                             'keyutils-devel', 'libuuid-devel-static',
                             'libjson-c-devel', 'systemd-devel',
                             'kmod-bash-completion', 'bash-completion-devel'])
            else:
                deps.extend(['kmod-devel', 'libuuid-devel', 'json-c-devel',
                             'systemd-devel', 'keyutils-libs-devel', 'jq',
                             'parted', 'libtool'])
        else:
            # TODO: Add RHEL when support arrives
            self.cancel('Unsupported OS %s' % detected_distro.name)

        for package in deps:
            if not smg.check_installed(package) and not smg.install(package):
                self.cancel(
                    "Fail to install %s required for this test." % (package))

        git.get_repo(self.url, branch=self.branch,
                     destination_dir=self.teststmpdir)

        self.sourcedir = self.teststmpdir
        os.chdir(self.sourcedir)

        # TODO: remove patches once merged upstream
        upstream_patch = self.fetch_asset("upstream.patch", locations=[
            "https://patchwork.kernel.org/series/177255/mbox/"], expire='7d')

        process.run('patch -p1 < %s' % upstream_patch, shell=True)
        if detected_distro.arch in ["ppc64", "ppc64le"]:
            process.run('patch -p1 < %s' %
                        self.get_data('ppc.patch'), shell=True)

        process.run('./autogen.sh', sudo=True, shell=True)
        process.run(
            "./configure CFLAGS='-g -O2' --prefix=/usr "
            "--disable-docs "
            "--sysconfdir=/etc --libdir=/usr/lib64 "
            "--enable-destructive", shell=True, sudo=True)

        build.make(self.sourcedir)

        bus_ids = self.get_bus_ids()
        os.environ['WITHOUT_NFIT'] = "y"
        os.environ['BUS_PROVIDER0'] = bus_ids[0]
        if len(bus_ids) > 1:
            os.environ['BUS_PROVIDER1'] = bus_ids[1]

    def test(self):
        """
        Selftests for non-NFIT devices
        """
        self.log.info("Running NDCTL selftests")
        failed_tests = []
        output = build.run_make(
            self.sourcedir, extra_args='check -j 1', process_kwargs={"ignore_status": True})
        for line in output.stdout.decode('utf-8').splitlines():
            if "Testsuite summary" in line:
                break
            if "PASS" in line:
                self.log.info("Passed test %s", line)
            if "FAIL" in line:
                failed_tests.append(line)
        if failed_tests:
            self.fail("%s" % failed_tests)
