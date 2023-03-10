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
# Copyright: 2021 IBM
# Author: Shirisha Ganta <shirisha.ganta1@ibm.com>
# Author: Sachin Sant <sachinp@linux.ibm.com>

import os
from avocado import Test
from avocado.utils import process, distro, build, archive
from avocado import skipIf
from avocado.utils.software_manager.manager import SoftwareManager

IS_KVM_GUEST = 'qemu' in open('/proc/cpuinfo', 'r').read()


class RASToolsPpcdiag(Test):
    """
    Test case to validate RAS tools bundled as a part of ppc64-diag
    package/repository.

    :avocado: tags=privileged,ras,ppc64le
    """
    fail_cmd = list()

    def run_cmd(self, cmd):
        if process.system(cmd, ignore_status=True, sudo=True, shell=True):
            self.fail_cmd.append(cmd)
        return

    @staticmethod
    def run_cmd_out(cmd):
        return process.system_output(cmd, shell=True,
                                     ignore_status=True,
                                     sudo=True).decode("utf-8").strip()

    def setUp(self):
        """
        Ensure corresponding packages are installed
        """
        self.run_type = self.params.get('type', default='distro')
        self.sm = SoftwareManager()
        deps = ["ppc64-diag"]
        for pkg in deps:
            if not self.sm.check_installed(pkg) and not \
                    self.sm.install(pkg):
                self.cancel("Fail to install %s required for this test." %
                            pkg)

    def test_build_upstream(self):
        """
        For upstream target download and compile source code
        Caution : This function will overwrite system installed
        ppc64-diag package binaries with upstream code.
        """
        if self.run_type == 'upstream':
            self.detected_distro = distro.detect()
            deps = ['gcc', 'make', 'automake', 'autoconf', 'bison', 'flex',
                    'libtool', 'zlib-devel', 'ncurses-devel', 'librtas-devel',
                    'libservicelog-devel']
            if 'SuSE' in self.detected_distro.name:
                deps.extend(['libvpd2-devel'])
            elif self.detected_distro.name in ['centos', 'fedora', 'rhel']:
                deps.extend(['libvpd-devel'])
            else:
                self.cancel("Unsupported Linux distribution")
            for package in deps:
                if not self.sm.check_installed(package) and not \
                        self.sm.install(package):
                    self.cancel("Fail to install %s required for this test." %
                                package)
            url = self.params.get(
                    'ppcdiag_url', default='https://github.com/power-ras/'
                    'ppc64-diag/archive/refs/heads/master.zip')
            tarball = self.fetch_asset('ppcdiag.zip', locations=[url],
                                       expire='7d')
            archive.extract(tarball, self.workdir)
            self.sourcedir = os.path.join(self.workdir, 'ppc64-diag-master')
            os.chdir(self.sourcedir)
            self.run_cmd('./autogen.sh')
            # TODO : For now only this test is marked as failed.
            # Additional logic should be added to skip all the remaining
            # test_() functions for upstream target if source code
            # compilation fails. This will require a way to share
            # variable/data across test_() functions.
            self.run_cmd('./configure --prefix=/usr')
            if self.fail_cmd:
                self.fail("Source code compilation error")
            build.make(self.sourcedir)
            build.make(self.sourcedir, extra_args='install')
        else:
            self.cancel("This test is supported with upstream as a target")

    def test_nvsetenv(self):
        """
        Change/view Open Firmware environment variables
        """
        self.log.info("===Executing nvsetenv tool====")
        self.run_cmd("nvsetenv")
        value = self.params.get('nvsetenv_list', default=[
                                'load-base', 'load-base 7000'])
        for list_item in value:
            self.run_cmd('nvsetenv  %s ' % list_item)
        if self.fail_cmd:
            self.fail("%s command(s) failed to execute  "
                      % self.fail_cmd)

    @skipIf(IS_KVM_GUEST, "This test is not supported on KVM guest platform")
    def test_usysattn(self):
        """
        View and manipulate the system attention and fault indicators (LEDs)
        """
        self.log.info("=====Executing usysattn tool test======")
        value = self.params.get('usysattn_list', default=['-h', '-V', '-P'])
        for list_item in value:
            self.run_cmd('usysattn  %s ' % list_item)
        loc_code = self.run_cmd_out("usysattn -P| awk 'NR==1{print $1}'")
        self.run_cmd("usysattn -l %s -s normal -t" % loc_code)
        if self.fail_cmd:
            self.fail("%s command(s) failed to execute  "
                      % self.fail_cmd)

    @skipIf(IS_KVM_GUEST, "This test is not supported on KVM guest platform")
    def test_usysfault(self):
        """
        View and manipulate the system attention and fault indicators (LEDs)
        """
        self.log.info("======Executing usysfault tool test======")
        value = self.params.get('usysfault_list', default=['-h', '-V', '-P'])
        for list_item in value:
            self.run_cmd('usysfault  %s ' % list_item)
        loc_code = self.run_cmd_out("usysfault -P | awk 'NR==1{print $1}'")
        self.run_cmd("usysfault -l %s -s normal -t" % loc_code)
        if self.fail_cmd:
            self.fail("%s command(s) failed to execute  "
                      % self.fail_cmd)

    @skipIf(IS_KVM_GUEST, "This test is not supported on KVM guest platform")
    def test_usysident(self):
        """
        This tests to turn on device identify indicators and other help
        options of usysident  ppc64-diag
        """
        if 'not supported' in self.run_cmd_out("usysident"):
            self.cancel(
                "The identify indicators are not supported on this system")
        value = self.params.get('usysident_list', default=['-h', '-V', '-P'])
        for list_item in value:
            self.run_cmd('usysident %s' % list_item)
        loc_code = self.run_cmd_out("usysident -P | awk 'NR==1{print $1}'")
        cmd = "usysident -l %s -s normal" % loc_code
        self.run_cmd(cmd)
        cmd = "usysident -l %s -s identify" % loc_code
        if 'on' not in self.run_cmd_out(cmd):
            self.fail_cmd.append(cmd)
        if self.fail_cmd:
            self.fail("%s command(s) failed to execute  "
                      % self.fail_cmd)
