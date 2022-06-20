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
import shutil

from avocado import Test
from avocado.utils import process, build, distro, git, genio
from avocado.utils.git import GitRepoHelper
from avocado.utils.software_manager.manager import SoftwareManager


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

    def copyutil(self, file_name, iniparser_dir):
        shutil.copy(file_name, iniparser_dir)

    def autotools_build_system(self):
        # Check if /usr/include/iniparser directory is present or not
        # If not present then create it and then  copy the iniparser.h
        # and dictionary.h headers to /usr/include/iniparser/

        # Skip this code for releases which ships required header files
        # as a part of /usr/include/iniparser/ directory.
        if not self.detected_distro.name == 'rhel':
            iniparser_dir = "/usr/include/iniparser/"
            if not os.path.exists(iniparser_dir):
                os.makedirs(iniparser_dir)

            for file_name in ['/usr/include/iniparser.h',
                              '/usr/include/dictionary.h']:
                self.copyutil(file_name, iniparser_dir)

        process.run('./autogen.sh', sudo=True, shell=True)
        process.run("./configure CFLAGS='-g -O2' --prefix=/usr "
                    "--disable-docs "
                    "--sysconfdir=/etc --libdir="
                    "/usr/lib64", shell=True, sudo=True)
        build.make(".")

        self.ndctl = os.path.abspath('./ndctl/ndctl')
        self.daxctl = os.path.abspath('./daxctl/daxctl')

    def meson_build_system(self, deps):
        deps.extend(['xmlto', 'libuuid-devel', 'meson', 'cmake'])
        if self.detected_distro.name == 'SuSE':
            deps.extend(['libgudev-1_0-devel', 'libiniparser-devel',
                         'libiniparser1', 'ruby2.5-rubygem-asciidoctor-doc',
                         'systemd-rpm-macros', 'pkg-config'])
        elif self.detected_distro.name == 'rhel':
            deps.extend(['libgudev-devel', 'rubygem-asciidoctor'])

        for pkg in deps:
            if not self.smg.check_installed(pkg) \
                    and not self.smg.install(pkg):
                self.cancel('%s is needed for the test to be run' % pkg)

        process.run("meson setup build", sudo=True, shell=True)
        process.run("meson install -C build", sudo=True, shell=True)
        self.ndctl = os.path.abspath('/usr/bin/ndctl')
        self.daxctl = os.path.abspath('/usr/bin/daxctl')

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

        self.smg = SoftwareManager()
        self.url = self.params.get(
            'url', default="https://github.com/pmem/ndctl.git")
        self.branch = self.params.get('branch', default='main')
        ndctl_project_version = self.params.get(
            'ndctl_project_version', default='')
        deps = ['gcc', 'make', 'automake', 'autoconf', 'patch', 'jq']
        self.detected_distro = distro.detect()
        if self.detected_distro.name in ['SuSE', 'rhel']:
            if self.detected_distro.name == 'SuSE':
                # Cancel this for now, due to non-availibility of
                # dependent packages for suse versions below sles15sp3.
                if self.detected_distro.release < 3:
                    self.cancel("Cancelling the test due to "
                                "non-availability of dependent packages.")
                else:
                    deps.extend(['libkmod-devel', 'libudev-devel',
                                 'keyutils-devel', 'libuuid-devel-static',
                                 'libjson-c-devel', 'systemd-devel',
                                 'kmod-bash-completion',
                                 'bash-completion-devel'])
            else:
                deps.extend(['kmod-devel', 'libuuid-devel', 'json-c-devel',
                             'systemd-devel', 'keyutils-libs-devel', 'jq',
                             'parted', 'libtool', 'iniparser',
                             'iniparser-devel'])
        else:
            # TODO: Add RHEL when support arrives
            self.cancel('Unsupported OS %s' % self.detected_distro.name)

        for package in deps:
            if not self.smg.check_installed(package) \
                    and not self.smg.install(package):
                self.cancel(
                    "Fail to install %s required for this test." % (package))

        git.get_repo(self.url, branch=self.branch,
                     destination_dir=self.teststmpdir)
        self.sourcedir = self.teststmpdir
        os.chdir(self.sourcedir)

        if ndctl_project_version:
            ndctl_tag_name = "v" + ndctl_project_version

            # Checkout the desired tag
            git_helper = GitRepoHelper(
                self.url, destination_dir=self.teststmpdir)
            git_helper.checkout(branch=ndctl_tag_name, commit=None)

            if (float(ndctl_project_version) < 73):
                self.autotools_build_system()
            else:
                self.meson_build_system(deps)
        else:
            self.meson_build_system(deps)

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
        output = build.run_make(self.sourcedir,
                                extra_args='check -j 1',
                                process_kwargs={"ignore_status": True})
        for line in output.stdout.decode('utf-8').splitlines():
            if "Testsuite summary" in line:
                break
            if "PASS" in line:
                self.log.info("Passed test %s", line)
            if "FAIL" in line:
                failed_tests.append(line)
        if failed_tests:
            self.fail("%s" % failed_tests)
