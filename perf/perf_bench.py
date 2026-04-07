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
# Author: Nageswara R Sastry <rnsastry@linux.vnet.ibm.com>

import platform
from avocado import Test
from avocado.utils import distro, process, dmesg
from avocado.utils.software_manager.manager import SoftwareManager


class perf_bench(Test):

    """
    Tests perf bench and it's options
    :avocado: tags=perf,bench
    """

    def setUp(self):
        '''
        Install the basic packages to support perf
        '''

        # Check for basic utilities
        smm = SoftwareManager()
        detected_distro = distro.detect()
        self.distro_name = detected_distro.name

        deps = ['gcc', 'make']
        if 'Ubuntu' in self.distro_name:
            deps.extend(['linux-tools-common', 'linux-tools-%s' %
                         platform.uname()[2]])
        elif self.distro_name in ['rhel', 'SuSE', 'fedora', 'centos']:
            deps.extend(['perf'])
        else:
            self.cancel("Install the package for perf supported \
                         by %s" % detected_distro.name)
        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel('%s is needed for the test to be run' % package)

        # Getting the parameters from yaml file
        self.optname = self.params.get('name', default='all')
        self.option = self.params.get('option', default='')

        # Clear the dmesg, by that we can capture the delta at the end of the test.
        dmesg.clear_dmesg()

    def verify_dmesg(self):
        self.whiteboard = process.system_output("dmesg").decode("utf-8")
        pattern = ['WARNING: CPU:', 'Oops',
                   'Segfault', 'soft lockup', 'Unable to handle']
        for fail_pattern in pattern:
            if fail_pattern in self.whiteboard:
                self.fail("Test Failed : %s in dmesg" % fail_pattern)

    def run_cmd(self, cmd):
        err_ln = "Assertion `!(ret)' failed"
        try:
            op = process.run(cmd, ignore_status=False, sudo=True)
        except process.CmdError as details:
            self.fail("Command %s failed: %s" % (cmd, details))
        output = op.stdout.decode() + op.stderr.decode()
        if err_ln in output:
            self.fail("command %s failed with assertion code" % cmd)

    def test_bench(self):
        # perf bench command
        bench_cmd = "perf bench %s %s" % (self.optname, self.option)
        self.run_cmd(bench_cmd)
        self.verify_dmesg()
